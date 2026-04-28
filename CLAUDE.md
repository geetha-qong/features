# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV.
Target: **≥90% recall** on valve identification.

**Current status**: Production webapp live at https://dev.theqong.com
**Next phase**: Replace API with own offline model (see `OWN_SYSTEM_DESIGN.md`)

## Branches

- `main` — stable, production-deployed API-based pipeline
- `feature/own-system` — offline YOLO+PaddleOCR system (annotation → training → replace extractor.py)

## P&ID Document Structure

### Valve Tag Format
`[AreaCode]-[TypeCode]-[SerialNo]` — e.g. `62-BF-151031`

### Line Number Format
`[Size]"-[FluidCode]-[AreaCode][SerialNo]-[PipingClass]` — e.g. `20"-W-62151031-BGA`

### Valve Type Codes
`BF`=Butterfly, `BV`/`VB`=Ball, `DB`=Double Block & Bleed, `CK`=Check, `GL`=Globe,
`VM`=Manual gate/globe, `VG`=Gate, `NV`=Needle, `SV`=Safety, `PV`=Pressure valve,
`UZV`=Ultrasonic zone valve, `FV`=Flow valve, `CV`=Control valve (pneumatic)

### Actuator Codes (Dynamic Code in CSV)
`M`=Motor, `P`=Pneumatic, `SL`=Solenoid, `-`=Manual

### DB Valve Rule
DB (Double Block & Bleed) valves are **always** on 2" instrument taps — size is always `2"`.
Parser auto-assigns size=2 when NOT DEFINED for DB category.

## Output CSV Schema (14 columns)

`P&ID No`, `Dynamic Code`, `Category`, `Size`, `Area Code`, `Serial No`,
`Series Code`, `Fluid Code`, `Piping Class`, `Qty`, `Motor Actuator`,
`Pneumatic Actuator ` *(trailing space — do not remove)*, `Solenoid`, `line`

## Current Architecture (main branch — API-based)

```
PDF → pdf_to_tiles.py → 9 PNG tiles (3×3, 25% overlap)
    → extractor.py (OpenRouter API, claude-sonnet-4-6 or gemini-2.0-flash)
      - Pass 1: valve tag + line number per tile
      - Pass 2: targeted line number recovery for misses
      - Stage 0: title block crop → extract Drawing No.
    → parser.py → corrections.py → validator.py → CSV
```

### Key Files
- `pipeline.py` — orchestrator, one-line swap to go offline: `from extractor` → `from detector`
- `pdf_to_tiles.py` — PDF → PNG tiles (PyMuPDF, 3× DPI)
- `extractor.py` — OpenRouter vision API calls, two-pass extraction, title block OCR
- `parser.py` — tag/line regex parser, ValveRow dataclass, deduplication
- `corrections.py` — drawing-specific manual overrides (post-parse, pre-validate)
- `validator.py` — regex validation, CSV writer
- `prompts.py` — all Claude Vision prompt templates
- `webapp/` — FastAPI web app (upload → job queue → results → download)
- `OWN_SYSTEM_DESIGN.md` — full design doc for offline YOLO+PaddleOCR system

## Webapp Features (production at https://dev.theqong.com)

- Login/register (JWT cookie auth). Admin: `admin / Qong@2024`
- Upload one or more P&ID PDFs → one background job per file (serialized via `_pipeline_lock`)
  - Form field: `name="files"` (multiple). Single file → redirect to job detail; batch → redirect to dashboard
  - P&ID number override only applied when single file uploaded
- Dashboard: job list with status, valve count, processing time
- Job detail: valve table, collapsible AI log, engineer feedback
- Control valve toggle, job re-run, CSV download per job
- Auto-extract Drawing No. from title block (bottom-right 40%×22% crop)

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{job_id}/tmp/` (never commit)

## Deployment (Production)

- Server: `root@157.180.20.168` (Ubuntu 24.04, aaPanel)
- App: FastAPI + uvicorn, port 8001, systemd `qong_poc`
- Nginx: `/www/server/panel/vhost/nginx/dev.theqong.com.conf`
- Code: `/www/wwwroot/qong_poc/`, auto-deploy via GitHub webhook
- **To deploy**: `git push origin main` (webhook triggers pull + restart)
- SSH alias for Winn-Projects GitHub: `winn-projects`

## DB Schema Notes

- SQLite at `webapp.db` (local) — NOT committed
- `run_migrations()` in `database.py` handles ALTER TABLE on startup
- Job columns: `processing_time` (Float), `processing_log` (Text), `include_control_valves` (Bool),
  `original_filename` (Str) — used to derive `drawing_stem` for corrections lookup

## Critical Bug Fixes (already applied)

1. **Corrections not applying**: `pipeline_runner.py` passes `input.pdf` as path →
   `drawing_stem` was always `"input"`. Fixed: pass `original_filename` through to `pipeline.run()`.
2. **DB valve size NOT DEFINED**: Parser now auto-assigns size=`"2"` for DB category.
3. **P&ID No truncated**: Title block prompt updated to capture full revision suffix (e.g. `24C7-D`).
4. **Jinja2 template path**: Use `Path(__file__).parent.parent / "templates"` (absolute) in all 3 router files.
5. **Stale processing jobs**: Reset to `failed` on app startup.

## Correction Rules (verified by engineer, MUK-62-1-15-1004)

See `corrections.py` for full list. Key rules:
- Removed hallucinations: 151076, 151077 (not present in drawing)
- DB valves 151025–151028: size corrected
- BF valves 151065–151068: all on line `10"-W-62151021-BGA-H`

## Ground Truth Results (5 P&IDs, Oman MUK project)

| P&ID | Valves | Actuated | Complete Rows |
|------|--------|----------|---------------|
| MUK-62-1-15-1001 | 54 | 6 | ~91% |
| MUK-62-1-15-1002 | 42 | 9 | 100% ✅ |
| MUK-62-1-15-1003 | 35 | 0 | ~97% |
| MUK-62-1-15-1004 | 28 | 1 | ~100% |
| MUK-62-1-15-1005 | 34 | 0 | ~94% |
| **Total** | **193** | **16** | **~93%** |

These 193 valve instances + 45 tiles are the training dataset for the offline system.

## Own System Design (feature/own-system branch)

See `OWN_SYSTEM_DESIGN.md` for full spec. Summary:
- **Detection**: YOLOv8s ONNX at imgsz=1280, 10 classes (8 valve + 2 actuator types)
- **OCR**: PaddleOCR PP-OCRv4, `use_angle_cls=True`
- **Association**: geometric spatial linking (symbol bbox → tag text → line text)
- **Annotation tool**: Label Studio (local), ~11 hrs to annotate all 45 tiles
- **Integration**: `detector.py` replaces `extractor.py` with identical public API
- **Pipeline.py change**: one line — `from extractor import` → `from detector import`

### Annotation Classes (10 YOLO classes)
`valve_bf`, `valve_bv`, `valve_ck`, `valve_gl`, `valve_db`, `valve_cv`, `valve_gen`,
`actuator_motor`, `actuator_pneumatic`, `actuator_solenoid`

## Docker Services (feature/own-system branch)

Three services in `docker-compose.yml`:
- `web` — FastAPI webapp (port 8000)
- `label-studio` — annotation tool (port 8080); tiles mounted at `/tiles` inside container; exports land in `annotate/exports/`
- `trainer` — YOLOv8 training via `Dockerfile.trainer` (CPU PyTorch by default; uncomment `deploy.resources` for GPU)

```bash
docker compose up label-studio                                                                        # start annotation tool
docker compose run --rm trainer python3 train.py                                                      # train from scratch
docker compose run --rm trainer python3 train.py --resume                                             # resume training
docker compose run --rm trainer python3 train.py --export runs/detect/pid_valves_v1/weights/best.pt  # export ONNX
```

## Annotation Status (feature/own-system branch)

- 45 tiles ready in `annotate/tiles/` (exported from 5 P&IDs)
- `datasets/pid_valves/` folder structure exists but `images/train|val/` and `labels/train|val/` are **empty** — annotations not yet done
- Label Studio data: `annotate/ls_data/` (persistent DB + media); exports → `annotate/exports/` (YOLO ZIP)
- After export: unzip into `datasets/pid_valves/`; drawings 1002–1005 → train/, drawing 1001 (9 tiles) → val/
- **Login**: `tnb@qongsystems.com` / `Qong@2024`

## Starting an Annotation Session (sharing with team)

```bash
./annotate/start_annotation_session.sh
```

This script:
1. Runs `caffeinate -i` to prevent Mac sleep
2. Ensures Label Studio Docker container is up
3. Starts `ngrok http 8080` → prints a public URL to share with the team

- Screen lock is fine; Mac **must not sleep** (caffeinate handles this)
- ngrok URL changes on every restart — share fresh URL each session
- Team login: `tnb@qongsystems.com` / `Qong@2024`
- Local URL: `http://localhost:8080`
- ngrok installed at `/opt/homebrew/bin/ngrok`, auth token already configured
- **Known 500 bug**: if `organization.created_by` is null after login, fix with:
  ```bash
  docker compose exec label-studio bash -c "cd /label-studio/label_studio && python3 -c \"
  import django, os, sys; sys.path.insert(0, '.'); os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.label_studio'; django.setup()
  from users.models import User; from organizations.models import Organization
  u = User.objects.get(email='tnb@qongsystems.com'); org = Organization.objects.get(id=1)
  org.created_by = u; org.save(); print('Fixed')
  \""
  ```

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

### Training Results (pid_valves_v1-5) — COMPLETED
- Run: `runs/detect/pid_valves_v1-5/` — 50 epochs, mAP50 = **0.511** (target ≥0.5 ✅)
- Strong classes: `valve_db` 0.944, `valve_bf` 0.845, `valve_bv` 0.634
- Weak classes (too few training instances): `valve_ck` 0.001, `valve_gl` 0.034
- ONNX exported to `models/best.onnx` (43 MB)
- To retrain: `python3 train.py` (always start fresh from `yolov8s.pt`; ~17 min on M3 Pro)
- To export: `python3 train.py --export runs/detect/<run_name>/weights/best.pt`

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

**pipeline.py is already switched**: `from detector import extract_all_tiles, extract_drawing_number`

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

## Temporary Files

All intermediate files go in `job_outputs/{id}/tmp/` — never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.
