#!/bin/bash
# Autonomous YOLO v1-11 training script.
# Replays the proven v1-10 flow (FEATURES #30) on a g5.2xlarge, with one
# addition: after training v1-11 it ALSO evaluates the deployed v1-10 model
# on the SAME held-out val split, so we get a leak-free apples-to-apples
# comparison ("did the model improve?").
#
# Run on the g5.2xlarge instance via SSM/user-data. Pulls dataset from S3,
# trains, exports ONNX, evaluates v1-11 + v1-10 on the v1-11 val split,
# uploads artifacts + a COMPARISON file, then auto-terminates.
#
# Safety: timeout 8h on the train command bounds cost (~$10). shutdown -h now
# at the end + --instance-initiated-shutdown-behavior=terminate => EC2 dies.
set -eo pipefail
LOG=/var/log/qong-train.log
exec > "$LOG" 2>&1
echo "[train] === Started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "[train] hostname: $(hostname), uptime: $(uptime)"

S3_BASE="s3://qong-pid-archive-2026-06-02/training/v1-11"
S3_V110="s3://qong-pid-archive-2026-06-02/training/v1-10"   # source of v1-10 best.pt for comparison
WORK=/opt/qong/training
mkdir -p "$WORK" && cd "$WORK"
chown -R ubuntu:ubuntu "$WORK"

echo "[train] Waiting for ultralytics install..."
for i in $(seq 1 60); do
  if [ -f /var/log/qong-bootstrap.log ] && grep -q "bootstrap.* done" /var/log/qong-bootstrap.log 2>/dev/null; then
    echo "[train] Bootstrap complete."
    break
  fi
  sleep 10
done
which yolo || pip install ultralytics==8.3.40 onnx==1.16.2 onnxruntime
# onnxscript required by torch.onnx.export on PyTorch 2.7+ (FEATURES #30).
pip install --quiet onnxscript
which yolo

# Background log uploader — pushes log + results.csv to S3 every 5 min.
upload_status() {
  while true; do
    sleep 300
    aws s3 cp "$LOG" "$S3_BASE/training.log" --region ap-south-1 2>/dev/null || true
    if [ -f "$WORK/runs/v1-11/results.csv" ]; then
      aws s3 cp "$WORK/runs/v1-11/results.csv" "$S3_BASE/results.csv" --region ap-south-1 2>/dev/null || true
    fi
    if [ -f "$WORK/runs/v1-11/results.png" ]; then
      aws s3 cp "$WORK/runs/v1-11/results.png" "$S3_BASE/results.png" --region ap-south-1 2>/dev/null || true
    fi
  done
}
upload_status &
UPLOAD_PID=$!
echo "[train] Background log uploader PID=$UPLOAD_PID (5-min cadence)"

# Pull dataset from S3
echo "[train] === Downloading dataset ==="
aws s3 cp "$S3_BASE/dataset_v1-11.tar" dataset.tar --region ap-south-1
ls -lh dataset.tar
tar -xf dataset.tar
ls dataset_v1-11/

# Overwrite data.yaml with ABSOLUTE path (Ultralytics resolves relative `path:`
# against settings.json datasets_dir, not the yaml location — FEATURES #30 bug).
cat > dataset_v1-11/data.yaml <<YAML
path: $WORK/dataset_v1-11
train: images/train
val: images/val

nc: 23
names:
  0: valve_bv
  1: valve_ncbv
  2: valve_gt
  3: valve_bf
  4: valve_ck
  5: valve_db
  6: valve_relief_safety
  7: valve_gl
  8: valve_3way_relief
  9: inst_field
  10: inst_bpcs
  11: Motor
  12: Pump/Dwg Pump
  13: inst_sis
  14: SIS-R
  15: interlock
  16: inst_local_panel
  17: arrow_up
  18: arrow_left
  19: arrow_right
  20: arrow_down
  21: connector_out
  22: connector_in
YAML
echo "[train] Dataset extracted; data.yaml rewritten with absolute path."
head -4 dataset_v1-11/data.yaml

echo "[train] === GPU check ==="
nvidia-smi

# Smoke test (1 epoch, tiny model) — catches broken data.yaml / deps fast.
echo "[train] === Smoke test (1 epoch yolov8n) ==="
timeout 600 yolo train \
  data=dataset_v1-11/data.yaml \
  model=yolov8n.pt \
  epochs=1 imgsz=640 batch=16 device=0 \
  project="$WORK/runs" name=smoke exist_ok=True verbose=False 2>&1 | tail -30 || {
  echo "[train] SMOKE FAILED — aborting"
  echo "STATUS=SMOKE_FAILED $(date -u +%Y-%m-%dT%H:%M:%SZ)" | aws s3 cp - "$S3_BASE/STATUS" --region ap-south-1
  kill $UPLOAD_PID 2>/dev/null || true
  sleep 60 && sudo shutdown -h now
  exit 1
}
echo "[train] Smoke OK."

# Full training run
echo "[train] === Full training (yolov8s, 100 epochs) ==="
timeout 28800 yolo train \
  data=dataset_v1-11/data.yaml \
  model=yolov8s.pt \
  epochs=100 imgsz=640 batch=32 device=0 \
  project="$WORK/runs" name=v1-11 \
  patience=20 save_period=10 \
  exist_ok=True verbose=True 2>&1 | tail -200 || {
  echo "[train] FULL TRAIN FAILED — checking for partial best.pt"
  if [ -f "$WORK/runs/v1-11/weights/best.pt" ]; then
    echo "[train] Found partial best.pt — proceeding with export"
  else
    echo "STATUS=TRAIN_FAILED $(date -u +%Y-%m-%dT%H:%M:%SZ)" | aws s3 cp - "$S3_BASE/STATUS" --region ap-south-1
    aws s3 cp "$LOG" "$S3_BASE/training.log" --region ap-south-1 || true
    kill $UPLOAD_PID 2>/dev/null || true
    sleep 60 && sudo shutdown -h now
    exit 1
  fi
}

# ONNX export
BEST="$WORK/runs/v1-11/weights/best.pt"
echo "[train] === ONNX export from $BEST ==="
ls -lh "$BEST"
yolo export model="$BEST" format=onnx imgsz=640 opset=12 simplify=True
ls -lh "$WORK/runs/v1-11/weights/"

# === Comparison eval: v1-11 vs deployed v1-10 on the SAME (v1-11) val split ===
# Split is deterministic by sha1(task_id)%10 and stable across exports, so
# v1-10 never trained on these val tasks — leak-free comparison.
echo "[train] === Comparison eval (v1-11 vs v1-10 on v1-11 val split) ==="
yolo val model="$BEST" data=dataset_v1-11/data.yaml imgsz=640 \
  project="$WORK/runs" name=val_v1-11 exist_ok=True verbose=True 2>&1 | tee val_v1-11.txt | tail -60 || true

if aws s3 cp "$S3_V110/best.pt" v1-10_best.pt --region ap-south-1 2>/dev/null; then
  echo "[train] Pulled v1-10 best.pt — evaluating on the SAME val split"
  yolo val model=v1-10_best.pt data=dataset_v1-11/data.yaml imgsz=640 \
    project="$WORK/runs" name=val_v1-10 exist_ok=True verbose=True 2>&1 | tee val_v1-10.txt | tail -60 || true
else
  echo "[train] WARN: v1-10 best.pt not in S3 ($S3_V110/best.pt) — skipping v1-10 eval"
  echo "v1-10 best.pt unavailable for comparison" > val_v1-10.txt
fi

# ONNX export + comparison artifacts upload
echo "[train] === Uploading artifacts + comparison ==="
aws s3 cp --recursive "$WORK/runs/v1-11/" "$S3_BASE/runs/" --region ap-south-1
aws s3 cp "$WORK/runs/v1-11/weights/best.pt" "$S3_BASE/best.pt" --region ap-south-1
aws s3 cp "$WORK/runs/v1-11/weights/best.onnx" "$S3_BASE/best.onnx" --region ap-south-1
aws s3 cp val_v1-11.txt "$S3_BASE/val_v1-11.txt" --region ap-south-1 || true
aws s3 cp val_v1-10.txt "$S3_BASE/val_v1-10.txt" --region ap-south-1 || true
aws s3 cp --recursive "$WORK/runs/val_v1-11/" "$S3_BASE/val_v1-11/" --region ap-south-1 2>/dev/null || true
aws s3 cp --recursive "$WORK/runs/val_v1-10/" "$S3_BASE/val_v1-10/" --region ap-south-1 2>/dev/null || true
aws s3 cp "$LOG" "$S3_BASE/training.log" --region ap-south-1

# Final SHA + size + headline comparison
SHA=$(sha256sum "$WORK/runs/v1-11/weights/best.onnx" | awk '{print $1}')
SIZE=$(stat -c%s "$WORK/runs/v1-11/weights/best.onnx")
V11_MAP=$(grep -E '^\s+all\s' val_v1-11.txt | tail -1 | awk '{print $5}')
V10_MAP=$(grep -E '^\s+all\s' val_v1-10.txt | tail -1 | awk '{print $5}')
cat <<EOF | aws s3 cp - "$S3_BASE/STATUS" --region ap-south-1
STATUS=DONE
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
best_onnx_sha256=$SHA
best_onnx_size_bytes=$SIZE
v1-11_mAP50_all=$V11_MAP
v1-10_mAP50_all_same_valset=$V10_MAP
EOF

echo "[train] === DONE at $(date) — shutting down in 60s ==="
kill $UPLOAD_PID 2>/dev/null || true
sleep 60
sudo shutdown -h now
