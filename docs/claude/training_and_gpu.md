# Training, Detector, Label Studio, GPU Worker

Annotation, training pipeline, offline detector, Label Studio sync, and Phase A4/A5 GPU worker. See `CLAUDE.md` for top-level rules.

## Annotation Status (feature/own-system branch)

- 45 tiles ready in `annotate/tiles/` (exported from 5 P&IDs)
- `datasets/pid_valves/` — 45 annotated tiles in `images/train/` + `labels/train/`; 9 in `val/`; training v1-5 complete (mAP50=0.511; see Training Results section)
- Label Studio data: `annotate/ls_data/` (persistent DB + media); exports → `annotate/exports/` (YOLO ZIP)
- After export: unzip into `datasets/pid_valves/`; drawings 1002–1005 → train/, drawing 1001 (9 tiles) → val/
- **Login**: `tnb@qongsystems.com` / `Qong@2024`

### Annotation Classes (13 YOLO classes)
- Valves (7): `valve_bf`, `valve_bv`, `valve_ck`, `valve_gl`, `valve_db`, `valve_cv`, `valve_gen`
- Actuators (3): `actuator_motor`, `actuator_pneu`, `actuator_sol`
- Instruments (3): `inst_bubble` (all circle tags — PT/TT/FT/LT/PDT/PI/PS/ZS/etc.), `inst_cv` (FCV/XV), `inst_solenoid` (FY/XY)
- **inst_bubble is ONE class** — YOLO finds the circle, OCR reads the type code. Don't split by type.

## Annotation Sessions

**Team annotation**: use https://dev.qongsystems.com/ls/ (GCP, always on, HTTPS)
- LS login: `tnb@qongsystems.com` / `Qong@2024` (also: `admin@qong.com`, `g.sm@qongsystems.com`, `vg@qongsystems.com` — all `Qong@2024`)
- LS DB: **Postgres** (`label_studio` database, same Postgres container as webapp) — data is in named Docker volume `ls_data`, survives `git reset --hard` deploys
- LS uses `POSTGRE_*` env vars (NOT `POSTGRESQLURL` or `DATABASE_URL`) — see docker-compose.yml label-studio service
- To reset any LS password: `sudo docker compose exec -T label-studio python3 /label-studio/label_studio/manage.py shell -c "from users.models import User; u=User.objects.get(email='EMAIL'); u.set_password('NEW'); u.save()"`
- No tunnel needed — server is always accessible
- **Do NOT add nginx `auth_basic` on LS routes** — LS handles its own login; `LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=true` prevents unauthorized signups

**Local dev only** (offline annotation work):
```bash
./annotate/start_annotation_session.sh
```
- Starts label-studio + web locally; LS at `http://localhost:8080` or `http://localhost:9000/ls/`
- `WEBAPP_BASE_URL=http://localhost:8000` — tile images served from local web container

- **One-time fresh-instance setup** (required after any new Postgres LS DB):
  1. Fix 500 error (`organization.created_by = NULL`):
  ```bash
  sudo docker compose exec -T label-studio python3 /label-studio/label_studio/manage.py shell -c "
  from users.models import User; from organizations.models import Organization
  u = User.objects.get(email='tnb@qongsystems.com'); org = Organization.objects.get(id=1)
  org.created_by = u; org.save(); print('Fixed')"
  ```
  2. Enable legacy API tokens:
  ```bash
  sudo docker compose exec -T label-studio python3 /label-studio/label_studio/manage.py shell -c "
  from jwt_auth.models import JWTSettings; from organizations.models import Organization
  org = Organization.objects.get(id=1); s = JWTSettings.objects.get_or_create(organization=org)[0]
  s.legacy_api_tokens_enabled = True; s.save(); print('Enabled')"
  ```
  3. Get new API token, update `.env` `LS_API_KEY=...`, restart `web` + `cpu-worker`

## Training Lessons Learned (do NOT repeat these mistakes)

### Environment Setup
- Host Mac has **Python 3.9** (system) — ultralytics 8.4.42 + torch 2.8.0 installed at `~/Library/Python/3.9/`
- Docker trainer uses Python 3.11 + torch 2.3.0 + ultralytics 8.2.0
- **numpy must be pinned to `<2.0`** in Docker — ultralytics 8.2.0 uses `np.trapz` which was removed in numpy 2.0
- **`onnxsim` cannot be installed on ARM64** (needs cmake + g++) — removed from Dockerfile.trainer

### data.yaml Path
- `path: /app/datasets/pid_valves` was Docker-only — breaks on host
- Correct value: `path: datasets/pid_valves` — relative to cwd, works both in Docker (WORKDIR=/app) and on host (project root)
- Current value is correct; do not change it back to an absolute path

### data.yaml nc Must Match Actual Label Files
- **nc must equal the highest class index + 1 in your label files** — extra classes silently shift all indices and corrupt training (no error is raised)
- Verify before training: `awk '{print $1}' datasets/pid_valves/labels/train/*.txt | sort -n | uniq -c | tail -5` (max index = nc - 1)
- Current nc=10 (indices 0-9); instrument classes removed from data.yaml until annotation for them starts — add back only when label files actually use those indices

### MPS Training (Apple Silicon)
- MPS is available via `torch.backends.mps.is_available()` — use `device="mps"` in `model.train()`
- **AMP (mixed precision) causes NaN/Inf in EMA on MPS** — always set `amp=False` when training on MPS
- MPS is ~3x faster than CPU: ~1.5 s/it vs ~6.5 s/it at batch=2, imgsz=1280
- Docker cannot use MPS — run training directly on host for GPU speed

### Resume vs Finetune
- `--resume` loads saved `args.yaml` from the checkpoint run — device/project settings come from there, not from train.py
- `--finetune <path>` starts a new run with train.py settings — correct way to change device or project
- train.py `_find_last_checkpoint()` finds the most recently modified `last.pt` under `runs/detect/`
- When finetune loads a checkpoint saved by a different ultralytics version, torch.load may fail — upgrade ultralytics to match

### Root Cause of All 3 Training Failures
**Never switch environments mid-training.** Training started in Docker (torch 2.3) was killed mid-batch, producing a corrupted `last.pt`. Attempts to resume/finetune that checkpoint on host MPS (torch 2.8) caused cascading failures:
1. torch.load format mismatch (torch 2.3 → 2.8)
2. Corrupted EMA state from mid-batch kill → NaN at epoch ~25 every time
3. All checkpoints skipped due to NaN → empty weights directory, crash at end

**Rule: if you switch environment (Docker → host, CPU → MPS), always start fresh. Never carry a checkpoint across.**

### Training Results (pid_valves_v1-5) — SUPERSEDED
- Run: `runs/detect/pid_valves_v1-5/` — 50 epochs, mAP50 = **0.511**
- Training set: 36 images, 389 labels

### Training Results (pid_valves_v1-6) — SUPERSEDED
- Run: `runs/detect/pid_valves_v1-6/` — 50 epochs, mAP50 = **0.855** at epoch 30, nc=10, 44 images

### Training Results (pid_valves v1-7) — CURRENT BEST (2026-05-07)
- Run: `C:\Users\qongsystems\qong-poc-gpu\runs\detect\pid_valves\` on Windows GPU (RTX 2000 Ada)
- 92 epochs (early stop patience=30), mAP50 = **0.897** at epoch 61 (up from 0.855 ✅)
- Training set: 99 images (44 MUK + 55 from LS projects 1,3,4,5,6), nc=22
- ONNX (45MB) auto-exported by `train_gpu.py` → `models/best.onnx` on Windows; worker PID 11048
- **ALL training must run on Windows GPU** — never on MacBook (user directive)
- To retrain: run `scripts/export_and_merge.py` on GCP → scp tar.gz to Windows → run `train_gpu.py`
- **Class gaps (v1-7)**: 9 of 22 classes have ZERO training instances — actuator_motor(0), actuator_pneu(1), actuator_sol(2), valve_cv(6), valve_gen(8), inst_field-R(15), valve_ncbv(19), valve_relief_safety(20), valve_pnuectrl(21). Model cannot detect these. Fix: annotate them in LS before next training run.
- Verify class counts before training: `awk '{print $1}' datasets/pid_valves/labels/train/*.txt | sort -n | uniq -c`
- **Domain shift**: v1-7 trained on MUK oil/gas P&IDs only. Projects using different drawing standards (e.g. WTP water treatment) will have lower recall — need those project's tiles in training data.

### Docker Trainer (for reference / CI)
```bash
docker compose build trainer   # must rebuild after editing train.py or data.yaml
docker compose run --rm trainer python3 train.py
```
- Datasets are COPIED into image at build time — edits to `datasets/` require rebuild
- Runs/weights are written inside container — mount a volume if you need them on host

## Offline Detector (detector.py)

`detector.py` is the offline replacement for `extractor.py` — same public API:
- `extract_all_tiles(tiles, ...)` — YOLO ONNX inference + PaddleOCR text association
- `extract_drawing_number(pdf_path, tmp_dir)` — OCR title block, falls back to API

**pipeline.py uses extractor (NOT detector)** — `from extractor import extract_all_tiles, extract_drawing_number, extract_instruments`. Do not change this.

### PaddleOCR (host)
- Installed: `pip3 install paddleocr paddlepaddle` (Python 3.9, `~/Library/Python/3.9/`)
- Version: paddleocr 3.5.0, paddlepaddle 3.3.1
- Label Studio has incompatible redis/rq — ignore pip conflict warnings, both work fine

### ONNX Inference Notes
- `onnxruntime` 1.19.2 already installed; use `CPUExecutionProvider` (MPS not needed at inference)
- Model output shape: `[1, 14, 33600]` — transpose to `[33600, 14]`; cols 0-3 = xywh, 4-13 = class scores
- Letterbox preprocess with pad=114 (grey); scale back with stored scale + pad offsets

### Text Association Tuning
- Valve tag + line number searched within **300px radius** of valve centroid in OCR results
- Actuator linked to nearest valve within **150px**
- OCR may miss or misread tags — tune radius in `_associate_text()` in `detector.py` if recall drops
- `valve_ck` and `valve_gl` YOLO detections unreliable (mAP50 <0.05) — OCR text is the fallback

## Auto-Annotation (scripts/auto_annotate_ls.py)

Batch-posts YOLO pre-annotations to all unannotated LS tasks. Run on GCP:
```bash
# dry-run first to see counts
sudo docker compose exec -T web python3 scripts/auto_annotate_ls.py --dry-run
# annotate all projects
sudo docker compose exec -T web python3 scripts/auto_annotate_ls.py
# single project, overwrite existing predictions
sudo docker compose exec -T web python3 scripts/auto_annotate_ls.py --project 25 --force
```
- **Install onnxruntime first** (not in web container by default): `sudo docker compose exec -T web pip install onnxruntime`
- **After retraining**: copy new `best.onnx` to GCP at `/app/qong_poc/models/best.onnx`, then re-run
- `CONF_THRESH=0.15` (low by design — better to have false positives for annotators to remove than misses)
- `_LS_LABEL_NAME` dict in the script maps canonical class names to LS label config names (e.g. `actuator_pneu` → `actuator_pneumatic`)
- **LS bulk task API caveat**: `/api/tasks/?project=X` bulk response shows `ann_count: 0` even for annotated tasks — always use per-task `/api/tasks/{id}/` to check actual annotations
- Tiles with 0 YOLO detections (background/margin tiles) are silently skipped — not errors

## LS Projects — Annotation Status

`EXPORT_PROJECTS = [1, 3, 4, 5, 6, 11, 12, 13, 14]` in `scripts/export_and_merge.py`

| LS Projects | Drawing Source | Valves | Instruments | Notes |
|-------------|---------------|--------|-------------|-------|
| 1, 3, 4, 5, 6 | MUK oil/gas P&IDs | ✅ | ✅ | Full annotations, in v1-7 training |
| 11–14 | UNKNOWN-09 to UNKNOWN-13 | ✅ | ❌ | Valve-only; need DCS/PLC/interlock/inst_field annotations |
| 25 | WS-25-WTP-01 (water treatment) | partial | ❌ | Different drawing standard; v1-7 recall is low here |

- Projects 11-14 need instrument annotation (DCS, PLC, interlock, inst_field) before next training run
- Project 25 (WTP) requires annotating from scratch — add to EXPORT_PROJECTS only after annotating
- After completing annotations: re-run `export_and_merge.py`, then retrain on Windows GPU

## Label Studio Sync (merged to main)

- `/admin/label-studio` — super_admin pushes completed job tiles to Label Studio as annotation tasks
- `/annotate` — annotator-role users see synced projects + progress, link out to Label Studio
- `/jobs/{id}/tiles/{filename}` — serves tile PNGs so Label Studio can load images via URL; uses `get_job_dir(job)` with legacy fallback
- `webapp/label_studio_client.py` — LS REST API client; configured via `LS_URL` + `LS_API_KEY` env vars
- LS project created per P&ID drawing (named by pid_no); one project per drawing, re-sync safe
- `LS_URL` (Docker-internal, API calls only) vs `LS_EXTERNAL_URL` (browser-facing project links) — both in `label_studio_client.py`; set `LS_EXTERNAL_URL=https://dev.qongsystems.com/ls` in production
- `LS_API_KEY`: env var in `.env` — **must be named `LS_API_KEY`** (not `LABEL_STUDIO_API_KEY`); must be a user API token, not a JWT refresh token
- **LS legacy token auth**: LS 1.23+ disables legacy API tokens by default. If 401s appear, enable via Django shell (`sudo docker compose exec label-studio python3 manage.py shell`): `from jwt_auth.models import JWTSettings; from organizations.models import Organization; org = Organization.objects.get(id=1); s = JWTSettings.objects.get_or_create(organization=org)[0]; s.legacy_api_tokens_enabled = True; s.save()` — **must use `organization=org` key, NOT `id=1`** (raises FieldError in LS 1.23). Use `jwt_auth.models` (NOT `core.models`)
- **Auto-sync**: After every pipeline job, `_auto_sync_to_label_studio()` in `pipeline_runner.py` runs automatically — no manual button needed
- **`WEBAPP_BASE_URL` env var**: Tile image URL base for LS sync. Set to `https://dev.qongsystems.com` in `.env` on GCP so LS container can load tile images via the public domain.
- **`push_tiles` signature**: `push_tiles(project_id, tile_urls: list)` takes **raw URL strings** — the function wraps them as `{"data": {"image": url}}` internally. Do NOT pre-wrap.
- **`push_tiles` response**: LS `/api/projects/{id}/import` returns a dict `{"task_count": N, ...}` — use `data.get("task_count", ...)`, not `len(data)` (which counts dict keys, not tasks)
- **LS project stats cache**: `num_tasks_with_annotations` in project stats may show 0 right after import (async update); verify via `/api/tasks/{id}/annotations/` endpoint instead
- **Annotation import with tasks**: pass `[{"data": {"image": url}, "annotations": [{"result": [...]}]}]` to `/api/projects/{id}/import` to import tasks + annotations in one call
- **Re-sync deletes stale tasks first**: `delete_all_tasks(project_id)` is called before `push_tiles()` in the sync endpoint — prevents duplicate tasks with stale/broken image URLs
- **Must sync via public URL**: tile image URLs use `request.base_url` from the sync HTTP request; always trigger Re-sync from the public domain (https://dev.qongsystems.com) so LS container can load images
- **GCP LS current state**: 24 projects covering all 39 jobs; "PID Training - All Valves" (project 7) has 45 tasks + 45 annotations migrated from local LS
- **Local LS SQLite table names**: `project`, `task`, `task_completion` (NOT `projects_project`/`tasks_task` — those are a different LS schema version)

## Own System Design (feature/own-system branch)

See `OWN_SYSTEM_DESIGN.md` for full spec. Summary:
- **Detection**: YOLOv8s ONNX at imgsz=1280, 10 classes (8 valve + 2 actuator types)
- **OCR**: PaddleOCR PP-OCRv4, `use_angle_cls=True`
- **Association**: geometric spatial linking (symbol bbox → tag text → line text)
- **Annotation tool**: Label Studio (local), ~11 hrs to annotate all 45 tiles
- **Integration**: `detector.py` replaces `extractor.py` with identical public API
- **Pipeline.py change**: one line — `from extractor import` → `from detector import`

## Phase A5 — Pre-Annotations (COMPLETE, 2026-05-06)

**End-to-end verified 2026-05-06**: job 1 (MUK-62-1-15-1003, 9 tiles) → 85 detections → 9 LS predictions posted (model_version `gpu-worker-v1`).

GPU worker POSTs detections → webapp stores JSON → auto-pushes as LS pre-annotations.

- `POST /api/v1/jobs/{job_id}/gpu-result` (`webapp/routers/api_v1.py`) — auth via `_get_api_user`; stores `job.gpu_detections` (JSON); calls `push_predictions()` if `job.ls_project_id` set; returns `{"stored": N, "ls_predictions_posted": N}`
- `push_predictions(project_id, detections, job_dir)` (`label_studio_client.py`) — gets LS tasks for project, matches by `tile_p{page}_r{row}_c{col}` in task image URL, opens tile files for exact dims (2000×2000 fallback), POSTs to `/api/predictions/` with `model_version="gpu-worker-v1"`
- `job.gpu_detections` TEXT column — JSON list of detection dicts; added via `run_migrations()`
- Detection dict fields: `valve_tag`, `line_number`, `actuator`, `yolo_class`, `yolo_conf`, `tile_row`, `tile_col`, `tile_page`, `tile_x0`, `tile_y0`, `bbox_tile` ([x1,y1,x2,y2] in tile pixels), `source`

## Phase A4 — GPU Worker (COMPLETE, 2026-05-06)

**Tailscale network**:
- GCP VM (`qong-dev-server`): Tailscale IP `100.127.190.88`
- Windows GPU box (`desktop-6o56u39`): Tailscale IP `100.91.199.103`, username `qongsystems`
- Mac (`devs-macbook-pro`): Tailscale IP `100.81.161.115`
- GCP→Windows latency: ~65ms via direct peer; `sudo tailscale ping 100.91.199.103` to verify

**Redis on Tailscale**:
- Redis bound to BOTH `127.0.0.1:6379` (Docker internal) AND `100.127.190.88:6379` (Tailscale)
- Windows GPU worker connects via `REDIS_URL=redis://100.127.190.88:6379/0`
- After any docker-compose.yml port change: `sudo docker compose up -d --force-recreate redis`

**GPU worker repo** (`Qong-Systems/qong_poc_gpu` — separate repo, NOT in qong_product):
- Clone: `git clone https://github.com/Qong-Systems/qong_poc_gpu.git`
- `worker.py` — RQ worker consuming `gpu` queue; auto-deletes all tile files after each job
- `inference/engine.py` — YOLO ONNX + EasyOCR (replaced PaddleOCR 2026-05-06), zero imports from main repo
- `requirements.txt` — minimal: rq, redis, onnxruntime-gpu, easyocr, requests
- Local path on dev machine: `/Users/maahedev/allcode/experiments/qong/qong-gpu-worker/`

**Windows setup (completed 2026-05-06)**:
- Python: `C:\Program Files\Python311\python.exe` (3.11.9)
- Worker dir: `C:\Users\qongsystems\qong-poc-gpu\`
- ONNX model: `C:\Users\qongsystems\qong-poc-gpu\models\best.onnx` (45 MB)
- `.env`: `REDIS_URL=redis://100.127.190.88:6379/0`, `MODEL_PATH=models/best.onnx`
- PaddleOCR models cached in `C:\Users\qongsystems\.paddleocr\whl\`
- To start: `cd C:\Users\qongsystems\qong-poc-gpu && "C:\Program Files\Python311\python.exe" -X utf8 worker.py`
- **`-X utf8` is required** — EasyOCR progress bar crashes with cp1252 encoding over SSH without it
- Auto-start: Task Scheduler task `QongGpuWorker` runs `start_worker.bat` at ONLOGON (uses `-X utf8`)

**ONNX on Windows**: `onnxruntime-gpu 1.25.1` installed; currently uses CPU (CUDA 12 + cuDNN 9 not yet installed)
- Providers available: `TensorrtExecutionProvider, CUDAExecutionProvider, CPUExecutionProvider`
- Falls back to CPU silently — inference works, just slower

**CUDA install (no full toolkit needed — use redist ZIPs)**:
Download 3 packages (~2GB total), extract DLLs to `C:\Users\qongsystems\qong-poc-gpu\cuda_dlls\`, add `os.add_dll_directory(dll_dir)` in worker.py before `import onnxruntime`:
- cudart (~20MB): `developer.download.nvidia.com/compute/cuda/redist/cuda_cudart/windows-x86_64/cuda_cudart-windows-x86_64-12.6.77-archive.zip`
- cublas (~400MB): `developer.download.nvidia.com/compute/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.6.3.3-archive.zip`
- cuDNN (~1.5GB): `developer.download.nvidia.com/compute/cudnn/redist/cudnn/windows-x86_64/cudnn-windows-x86_64-9.5.1.17_cuda12-archive.zip`
- After extracting: `python -X utf8 -c "import onnxruntime; print(onnxruntime.get_available_providers())"` should show `CUDAExecutionProvider` before `CPUExecutionProvider`

**PaddleOCR first-run model download**: On fresh Windows install, `en_PP-OCRv3_det_infer.tar` (~3910 chunks) and `en_PP-OCRv4_rec_infer.tar` (~10000 chunks) download to `C:\WINDOWS\system32\config\systemprofile\.paddleocr\whl\`. Takes ~2-3 min; subsequent runs use cache.

**EasyOCR on Windows (replaces PaddleOCR — 2026-05-06)**: `easyocr==1.7.2` + PyTorch backend; avoids PaddleOCR's fatal oneDNN/fused_conv2d crash on Intel CPUs (that error was NOT safe to ignore — it caused 0 text detections).
- API: `reader.readtext(path)` → `[(bbox, text, conf)]`; bbox = `[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]` (quadrilateral — take min/max xs/ys for axis-aligned rect)
- EasyOCR reads hyphens in valve tags as underscores — `_OCR_SUBS` in `engine.py` includes `(r'(\d{2})_([A-Z]{2,4})_(\d{6})', r'\1-\2-\3')`
- EasyOCR first run downloads ~200MB models to `C:\WINDOWS\system32\config\systemprofile\.EasyOCR\`; cached for subsequent runs

**Transient urllib3 pool pollution (SimpleWorker)**: If a prior job in the same SimpleWorker process left a 60s `ConnectTimeout`, the next job may get "connection refused" partway through tile downloads. Caused by polluted urllib3 connection pool state. Fix: ensure worker is idle between jobs; restart worker if stuck.

**PaddleOCR (replaced — historical context only)**: was `paddleocr==2.9.1` (2.x API: `.ocr(path, cls=True)` → `[[[bbox,(text,conf)],...]]`); abandoned due to fatal `fused_conv2d` oneDNN crash producing 0 OCR results on Windows Intel CPUs. Do not re-add it.

**Windows pip install patterns**:
- Install in stages: core packages first (rq, redis, onnxruntime-gpu, numpy, Pillow, paddlepaddle), then paddleocr separately
- Use `--timeout 30 --retries 3` flags to avoid silent stalls on slow CDNs
- If pip stalls (same last line for 5+ min with file size not growing): `taskkill /PID <pid> /F`, retry
- `winget` does NOT work over SSH (requires desktop session) — use `Invoke-WebRequest` + silent installers

**SSH to Windows via GCP jump** (`sshpass` already installed on GCP VM — no setup needed):
```bash
gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="sshpass -p '123456' ssh -o StrictHostKeyChecking=no qongsystems@100.91.199.103 'YOUR_COMMAND'"
```
- File copy: SCP to GCP VM first (`gcloud compute scp`), then `sshpass scp` to Windows
- For Python scripts: SCP the .py file, then run `"C:\Program Files\Python311\python.exe" C:\path\to\script.py`
- Inline Python `-c` with complex strings fails due to nested quoting — always write to a file first

**CRITICAL — binary file transfer (ONNX models)**: `type C:\file | ssh ...` corrupts binary files via CRLF conversion. Symptom: ONNX runs but ALL detections collapse to one dominant class (e.g. every detection shows `valve_bf` at 0.26-0.41 conf). Use base64 encode/decode instead:
```bash
# On GCP VM (after sshpass retrieves base64 from Windows):
gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="
  sshpass -p '123456' ssh -o StrictHostKeyChecking=no qongsystems@100.91.199.103 \
  '\"C:\\Program Files\\Python311\\python.exe\" -c \
  \"import base64; data=open(r\\\"C:\\\\Users\\\\qongsystems\\\\qong-poc-gpu\\\\models\\\\best.onnx\\\",\\\"rb\\\").read(); print(base64.b64encode(data).decode())\"' \
  | python3 -c \"import sys,base64; open('/tmp/best.onnx','wb').write(base64.b64decode(sys.stdin.read().strip()))\"
"
```
- Verify size after copy: `ls -la /tmp/best.onnx` must match `dir C:\path\best.onnx` byte-for-byte

**Security design**:
- Windows box has ONLY `REDIS_URL` — no MinIO/DB/GCS credentials
- Tiles passed as presigned URLs (1-hour expiry, job-specific) — Windows cannot access other jobs' files
- `tempfile.TemporaryDirectory` in `run_inference_job()` guarantees all tile files deleted after every job, even on crash

**Auto-start via Task Scheduler (DONE — NSSM not needed)**:
- Task Scheduler task `QongGpuWorker` runs `start_worker.bat` at ONLOGON for `qongsystems` user
- `start_worker.bat`: `"C:\Program Files\Python311\python.exe" -X utf8 worker.py >> logs\worker.log 2>&1`
- `launch_worker.py`: starts detached process via `subprocess.Popen([python, '-X', 'utf8', 'worker.py'], creationflags=0x08)` (DETACHED_PROCESS — survives SSH disconnect)

**Windows SSH** (enable with one command as Administrator):
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Start-Service sshd; Set-Service -Name sshd -StartupType Automatic; New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```
- Password auth disabled by default — also run: `Add-Content "C:\ProgramData\ssh\sshd_config" "\nPasswordAuthentication yes"; Restart-Service sshd`
