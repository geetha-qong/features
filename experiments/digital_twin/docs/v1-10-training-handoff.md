# v1-10 YOLO Training — Autonomous Run Handoff

**Started:** 2026-06-05 ~22:28 IST (16:58 UTC) — second attempt; first attempt failed on smoke test due to two script bugs now fixed in commit `89be82c`.
**Expected finish:** ~01:30-02:45 IST (a 100-epoch yolov8s on g5.2xlarge usually clocks ~2-3h, plus ~10 min setup + ~5 min ONNX export + ~5 min upload + auto-terminate).
**Instance:** `i-0f1ab2fd0a46c4d60` (g5.2xlarge, on-demand, ap-south-1b)
**Prior failed instance:** `i-0ec47e4aaa9ad364b` (terminated). Ran ~45 min, cost ~$0.90 — counted toward total budget. Lessons logged in FEATURES #30 and commit `89be82c`.
**Cost:** ~$1.21/hr × ~3 hours ≈ **$3.50–4.50 total**
**Auto-terminate:** YES — instance shuts down + terminates via `--instance-initiated-shutdown-behavior=terminate` after script ends. Verify in console next morning.

## What's running

The training script (`experiments/digital_twin/scripts/ec2_train_v1-10.sh`) is detached on the instance via `nohup`. It:

1. Downloads `dataset_v1-10.tar` (258 MB) from S3
2. Runs a 1-epoch yolov8n smoke test (~1-2 min) to validate `data.yaml` + dependencies
3. Trains yolov8s for up to 100 epochs (early-stop patience=20, save every 10)
4. Exports `best.pt` → `best.onnx` (opset 12, simplified)
5. Uploads everything to `s3://qong-pid-archive-2026-06-02/training/v1-10/`
6. Writes a `STATUS` file (sentinel + SHA256 of best.onnx)
7. Calls `sudo shutdown -h now`

A background loop on the instance pushes `training.log` + `results.csv` + `results.png` to S3 every 5 minutes so you can monitor without SSM access.

## When you come back — check status

```bash
# Quick status check
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/STATUS - \
  --region ap-south-1 --profile tnbqong

# What you want to see:
# STATUS=DONE
# finished_at=2026-06-05T...
# best_onnx_sha256=...
# best_onnx_size_bytes=45264343  (~45 MB, similar to v1-9)
```

If `STATUS` file isn't there yet, training is still running. Check progress:

```bash
# Latest training log (updated every 5 min while running)
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/training.log - \
  --region ap-south-1 --profile tnbqong | tail -50

# Per-epoch metrics
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/results.csv - \
  --region ap-south-1 --profile tnbqong | tail -20

# Visual loss/mAP curves (downloads PNG to current dir)
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/results.png ./v1-10-results.png \
  --region ap-south-1 --profile tnbqong
```

## When training is DONE — review metrics

The headline numbers live in `results.csv`. What to look at:

| Column | Good | Concerning |
|---|---|---|
| `metrics/mAP50(B)` (last epoch) | ≥0.50 | <0.40 |
| `metrics/mAP50-95(B)` | ≥0.30 | <0.20 |
| `train/box_loss` trajectory | trending down to <1.5 | flat or rising |
| `val/box_loss` | tracks train, gap <0.5 | gap >1.0 = overfitting |

For comparison, v1-9 was mAP50 = 0.404. **v1-10 should match or beat this** since we have more data and cleaner labels. If it doesn't, suspect:

- The 23-class schema diluted training signal vs v1-9's 20-class (more classes = harder)
- Per-class imbalance hurt minority classes (connector_in @ 55 instances, etc.)

You can see per-class mAP in the log file (search for `Class` then look for per-class lines near end of training).

## Pulling the model back to local

```bash
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/best.onnx \
  experiments/digital_twin/models/v1-10.onnx \
  --region ap-south-1 --profile tnbqong

# verify SHA matches STATUS file
sha256sum experiments/digital_twin/models/v1-10.onnx
```

## If metrics look good — promote to production

This is the part that was deliberately NOT automated (needs your judgment):

1. **Create a GitHub release** — tag `model-v1-10` on `Qong-Systems/qong_product`, attach `best.onnx` renamed to `v1-10.onnx`. Use the PAT in SSM `/may26aws/qong-shared/github-pat-model-release`. See FEATURES #28 and the Dockerfile recipe.

2. **Compute SHA256** of the uploaded asset and update `Dockerfile`:
   ```dockerfile
   TAG="model-v1-10"
   ASSET_NAME="v1-10.onnx"
   MODEL_SHA="<new-sha-here>"
   DEST=/app/models/v1-10.onnx
   ```

3. **Update `CLASS_NAMES` in `webapp/inference.py`** to the 23-class list (see `experiments/digital_twin/data/dataset_v1-10/data.yaml` or the `CLASSES` constant in `experiments/digital_twin/scripts/export_ls_dataset.py`).

4. **Update CONF_THRESH** if needed — start with the existing 0.5 from v1-9; revisit after smoke-testing on real PDFs.

5. **Commit + push to `dev`** — `deploy-dev.yml` triggers automatically, rebuilds the image with v1-10 baked in, deploys to dev.qongsystems.com.

6. **Smoke test** — upload a sample PDF on dev, verify both valve bboxes (existing) and arrow bboxes (new) appear in the Studio canvas. Run a "valve list" job and verify the CSV pipeline still works (CSVs are extractor-API-based, not YOLO, so they shouldn't be affected — but worth confirming).

## If training failed

Check the STATUS file — `SMOKE_FAILED` or `TRAIN_FAILED` will indicate which phase. Then pull the log:

```bash
aws s3 cp s3://qong-pid-archive-2026-06-02/training/v1-10/training.log - \
  --region ap-south-1 --profile tnbqong | tail -200
```

Most common failure modes:
- **CUDA OOM on smoke**: batch=16 too big for some reason — drop to batch=8 in the script, re-run.
- **Image format errors on val**: rare, but possible if some downloaded tile is corrupt — manifest.json has per-task records; cross-reference.
- **NaN losses**: likely a bad annotation (degenerate bbox). Look at training.log for the offending image/label, then patch and re-export.

## If you need to kill the instance manually

```bash
aws ec2 terminate-instances --instance-ids i-0f1ab2fd0a46c4d60 \
  --region ap-south-1 --profile tnbqong
```

The instance has `--instance-initiated-shutdown-behavior=terminate` set, so `shutdown -h now` from inside also terminates (not just stops). Belt + braces.

## What was NOT done autonomously

1. GitHub release `model-v1-10` — needs your eyes on the metrics first
2. Dockerfile SHA update — depends on above
3. `webapp/inference.py CLASS_NAMES` update — depends on above
4. `dev` deployment — depends on above

These are queued as a single follow-up task once you confirm v1-10 is shippable.

## Quick links

- Dataset: `s3://qong-pid-archive-2026-06-02/training/v1-10/dataset_v1-10.tar` (258 MB)
- Status: `s3://qong-pid-archive-2026-06-02/training/v1-10/STATUS`
- Logs: `s3://qong-pid-archive-2026-06-02/training/v1-10/training.log`
- Final model: `s3://qong-pid-archive-2026-06-02/training/v1-10/best.onnx` (after STATUS=DONE)
- All run artefacts: `s3://qong-pid-archive-2026-06-02/training/v1-10/runs/`
