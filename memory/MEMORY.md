# Project Memory: qong_poc

## Project
P&ID Valve List extraction POC — Occidental Mukhaizna LLC (Oman).
Goal: Extract valve list from scanned P&ID → CSV with ≥90% recall.
Live at: https://dev.qongsystems.com

## Branches
- `main` — future production at **app.qongsystems.com** (not yet live; do not push until prod infra ready)
- `dev` — active development; auto-deploys to **dev.qongsystems.com** on every push
- `feature/multi-cloud-saas` — superseded by `dev` (all phases A1-A3, B1-B5 merged)

## GitHub
- [GitHub org separation — never use Winn-Projects for Qong work](feedback_github_orgs.md) — gh CLI is tarunhere/Winn-Projects; Qong-Systems repos need manual creation or separate token

## Key Files
- `pipeline.py` — orchestrator (one-line swap: `from extractor` → `from detector` for offline)
- `pdf_to_tiles.py` → `extractor.py` → `parser.py` → `corrections.py` → `validator.py`
- `prompts.py` — all Claude Vision prompts (documents association rules for own-system)
- `corrections.py` — drawing-specific manual overrides (post-parse)
- `webapp/` — FastAPI web app (upload, job queue, results, feedback)
- `OWN_SYSTEM_DESIGN.md` — full offline system design (YOLO+PaddleOCR)
- `train.py` — YOLOv8s training script
- `datasets/pid_valves/data.yaml` — 10-class YOLO dataset config
- `annotate/` — Label Studio setup guide + tile export script

## P&ID Domain Knowledge
- Valve tag format: `[AreaCode]-[TypeCode]-[SerialNo]` e.g. `62-BF-151031`
- Line number format: `[Size]"-[FluidCode]-[AreaCode][SerialNo]-[PipingClass]` e.g. `20"-W-62151031-BGA`
- Actuators: M=Motor, P=Pneumatic, SL=Solenoid, none=Manual
- DB (Double Block & Bleed) valves are ALWAYS 2" — auto-assigned in parser.py
- M symbols on pumps (62-P-XXXXX) are pump motors — NOT valve actuators
- CV = Control Valve (pneumatic dome) — optional to include per job
- PDF is scanned (image-based) — no embedded text

## Ground Truth Results (5 P&IDs tested, all Oman MUK project)
| P&ID | Valves | Actuated | Complete |
|------|--------|----------|---------|
| MUK-62-1-15-1001 | 54 | 6 | ~91% |
| MUK-62-1-15-1002 | 42 | 9 (P+SL) | 100% |
| MUK-62-1-15-1003 | 35 | 0 | ~97% |
| MUK-62-1-15-1004 | 28 | 1 (P) | ~100% |
| MUK-62-1-15-1005 | 34 | 0 | ~94% |
| **Total** | **193** | **16** | **~93%** |
45 tiles available as training data for offline system.

## Environment
- Python 3.12 (server: Ubuntu 24.04), Python 3.9 (local dev)
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- extractor.py uses OpenRouter (openai-compatible) with `OPENROUTER_API_KEY`
- Default model: `google/gemini-2.0-flash-001`; override via `OPENROUTER_MODEL`
- Temp files → `job_outputs/{id}/tmp/` per job (never commit)
- Local app: `OPENROUTER_API_KEY=... python3 -m uvicorn webapp.main:app --port 8000 --reload`

## Deployment
- **Dev**: `dev` branch → auto-deploy to `dev.qongsystems.com` (GCP VM `qong-dev-server`, `asia-southeast1-c`, IP `34.126.93.103`) via GitHub Actions
- **Prod (future)**: `main` branch → `app.qongsystems.com` (separate GCP setup, not yet live)
- **Legacy**: `root@157.180.20.168` (Hetzner, still serving `main` branch at https://dev.theqong.com — old domain)
- GCP VM user: `maahedev`; code at `/app/qong_poc/`; all docker needs `sudo`
- gcloud CLI: `/opt/homebrew/share/google-cloud-sdk/bin/gcloud`; auth: `theqongglobal@gmail.com`
- SSH deploy key on VM: `~/.ssh/id_ed25519_qong_product`; GitHub SSH alias `qong-product`
- GitHub Actions deploy key: `~/.ssh/github_actions_deploy` on VM (pub key in `authorized_keys`)

## Key Bug Fixes (applied to dev branch)
- **Corrections not applying**: `drawing_stem` was always `"input"` because pipeline received
  `input.pdf` as path. Fixed: pass `original_filename` through pipeline_runner → pipeline.run()
- **DB valve size**: Parser auto-assigns size=`"2"` for DB category when NOT DEFINED
- **P&ID No truncated**: Title block prompt updated to capture full revision suffix (e.g. `24C7-D`)
- **Jinja2 template path**: Use absolute path `Path(__file__).parent.parent / "templates"`
- **Port conflict on server**: port 8000 taken by Docker → app uses 8001
- **Stale processing jobs**: Reset to `failed` on app startup
- **Postgres compat**: `Base.metadata.create_all()` replaces raw SQL; `TRUE/FALSE` for booleans; `psycopg2-binary` added
- **rq.Connection removed**: `Worker(queues=[Queue("cpu", connection=conn)], connection=conn)` — no `with Connection(conn):`
- **LS FORCE_SCRIPT_NAME**: Set via `LABEL_STUDIO_HOST=https://dev.qongsystems.com/ls` — LS derives it from URL path; bare env var is ignored
- **LS legacy tokens**: Enable via `jwt_auth.models.JWTSettings.legacy_api_tokens_enabled = True` in Django shell

## DB Schema Notes
- SQLite at `webapp.db` (local + server, NOT committed)
- `run_migrations()` in `database.py` handles ALTER TABLE on startup
- Key Job columns: `processing_time`, `processing_log`, `include_control_valves`, `original_filename`
- `original_filename` used to derive `drawing_stem` for corrections lookup

## Label Studio (GCP)
- URL: https://dev.qongsystems.com/ls/ (basic auth: `qong` / `Qong@LS2024`)
- LS login: `tnb@qongsystems.com` / `teNZmvlCg3GDcl99`
- LS API token: `489d6c0dd73a50b72e9814d305d136fe1f505c7e` (legacy token for tnb@qongsystems.com)
- `LS_API_KEY` set in `/app/qong_poc/.env` on GCP VM
- Legacy tokens enabled via `jwt_auth.models.JWTSettings` Django model

## Own System Design (feature/own-system branch)
Replacing extractor.py with local inference — no API, no cost, no hallucinations.
- **detector.py** = drop-in for extractor.py (identical public API)
- **symbol_detector.py**: YOLOv8s ONNX at imgsz=1280, 10 classes
- **ocr_engine.py**: PaddleOCR PP-OCRv4, use_angle_cls=True
- **associate.py**: geometric spatial linking (symbol bbox → tag → line)
- **pipe_tracer.py**: OpenCV HoughLinesP for pass-2 line number recovery
- Annotation: Label Studio (local), ~11hrs for 45 tiles, 10 classes
- Training: `python3 train.py` → 100 epochs → export ONNX → copy to models/best.onnx
- Expected mAP@0.5: 82–88% from 5 drawings, 88–93% with augmentation

## YOLO Classes (10)
valve_bf(0), valve_bv(1), valve_ck(2), valve_gl(3), valve_db(4),
valve_cv(5), valve_gen(6), actuator_motor(7), actuator_pneu(8), actuator_sol(9)

## Webapp Features
- Login/register (JWT cookie auth). Admin: `admin / s97nyGExH35FBeziyr`
- Upload PDF → background job (serialized via `_pipeline_lock`)
- Dashboard, job detail, CSV download, re-run, AI log, CV toggle, engineer feedback
- Auto-extract Drawing No. from title block (bottom-right 40%×22% crop)
