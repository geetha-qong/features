#!/bin/bash
# Autonomous YOLO v1-10 training script.
# Run on the g5.2xlarge instance via SSM. Pulls dataset from S3, trains for up
# to 8h, exports ONNX, uploads artifacts, then auto-terminates the instance.
#
# Status reporting: every 5 min the training log + results.csv are pushed to
# s3://qong-pid-archive-2026-06-02/training/v1-10/ so progress can be monitored
# from outside without SSM access. STATUS file is written at the very end.
#
# Safety: timeout 8h on the actual yolo command bounds maximum cost (~$10 at
# g5.2xlarge on-demand pricing). shutdown -h now at the end relies on
# --instance-initiated-shutdown-behavior=terminate set at launch time, so the
# EC2 dies (not just stops).
set -e
LOG=/var/log/qong-train.log
exec > "$LOG" 2>&1
echo "[train] === Started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo "[train] hostname: $(hostname), uptime: $(uptime)"

S3_BASE="s3://qong-pid-archive-2026-06-02/training/v1-10"
WORK=/opt/qong/training
mkdir -p "$WORK" && cd "$WORK"
chown -R ubuntu:ubuntu "$WORK"

# Wait for user-data bootstrap to finish installing ultralytics
echo "[train] Waiting for ultralytics install..."
for i in $(seq 1 60); do
  if [ -f /var/log/qong-bootstrap.log ] && grep -q "bootstrap.* done" /var/log/qong-bootstrap.log 2>/dev/null; then
    echo "[train] Bootstrap complete."
    break
  fi
  sleep 10
done
which yolo || pip install ultralytics==8.3.40 onnx==1.16.2 onnxruntime
which yolo

# Background log uploader — pushes log + results.csv to S3 every 5 min so user
# can monitor without SSM access. Killed at the end of the script.
upload_status() {
  while true; do
    sleep 300
    aws s3 cp "$LOG" "$S3_BASE/training.log" --region ap-south-1 2>/dev/null || true
    if [ -f "$WORK/runs/v1-10/results.csv" ]; then
      aws s3 cp "$WORK/runs/v1-10/results.csv" "$S3_BASE/results.csv" --region ap-south-1 2>/dev/null || true
    fi
    if [ -f "$WORK/runs/v1-10/results.png" ]; then
      aws s3 cp "$WORK/runs/v1-10/results.png" "$S3_BASE/results.png" --region ap-south-1 2>/dev/null || true
    fi
  done
}
upload_status &
UPLOAD_PID=$!
echo "[train] Background log uploader PID=$UPLOAD_PID (5-min cadence)"

# Pull dataset from S3
echo "[train] === Downloading dataset ==="
aws s3 cp "$S3_BASE/dataset_v1-10.tar" dataset.tar --region ap-south-1
ls -lh dataset.tar
tar -xf dataset.tar
ls dataset_v1-10/
echo "[train] Dataset extracted."

# GPU sanity check
echo "[train] === GPU check ==="
nvidia-smi

# Smoke test (1 epoch, tiny model, 60-sec budget) — catches broken data.yaml
# or dependency errors before the real run.
echo "[train] === Smoke test (1 epoch yolov8n) ==="
timeout 600 yolo train \
  data=dataset_v1-10/data.yaml \
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
  data=dataset_v1-10/data.yaml \
  model=yolov8s.pt \
  epochs=100 imgsz=640 batch=32 device=0 \
  project="$WORK/runs" name=v1-10 \
  patience=20 save_period=10 \
  exist_ok=True verbose=True 2>&1 | tail -200 || {
  echo "[train] FULL TRAIN FAILED — checking for partial best.pt"
  if [ -f "$WORK/runs/v1-10/weights/best.pt" ]; then
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
BEST="$WORK/runs/v1-10/weights/best.pt"
echo "[train] === ONNX export from $BEST ==="
ls -lh "$BEST"
yolo export model="$BEST" format=onnx imgsz=640 opset=12 simplify=True
ls -lh "$WORK/runs/v1-10/weights/"

# Final upload of all artifacts
echo "[train] === Uploading final artifacts ==="
aws s3 cp --recursive "$WORK/runs/v1-10/" "$S3_BASE/runs/" --region ap-south-1
aws s3 cp "$WORK/runs/v1-10/weights/best.pt" "$S3_BASE/best.pt" --region ap-south-1
aws s3 cp "$WORK/runs/v1-10/weights/best.onnx" "$S3_BASE/best.onnx" --region ap-south-1
aws s3 cp "$LOG" "$S3_BASE/training.log" --region ap-south-1

# Final SHA + size for verification
SHA=$(sha256sum "$WORK/runs/v1-10/weights/best.onnx" | awk '{print $1}')
SIZE=$(stat -c%s "$WORK/runs/v1-10/weights/best.onnx")
cat <<EOF | aws s3 cp - "$S3_BASE/STATUS" --region ap-south-1
STATUS=DONE
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
best_onnx_sha256=$SHA
best_onnx_size_bytes=$SIZE
EOF

echo "[train] === DONE at $(date) — shutting down in 60s ==="
kill $UPLOAD_PID 2>/dev/null || true
sleep 60
sudo shutdown -h now
