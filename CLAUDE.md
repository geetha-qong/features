# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV.
Target: **≥90% recall** on valve identification.

**Current status**: Production webapp live at https://dev.theqong.com
**Next phase**: Replace API with own offline model (see `OWN_SYSTEM_DESIGN.md`)

## Branches

- `dev` — active development; auto-deploys to `dev.qongsystems.com` on every push via GitHub Actions
- `main` — reserved for future production at `app.qongsystems.com` (do not push until prod infra ready)
- `feature/multi-cloud-saas` — superseded by `dev` (all phases A1-A3, B1-B5 merged in)

## Docker-First Rule

**NEVER install any service or tool directly on the local Mac.** All services (nginx, databases, annotation tools, etc.) must be added as Docker containers in `docker-compose.yml`. This ensures the compose file can be pushed to production as-is.

## CRITICAL: Two-Mode Architecture — Do NOT Mix

**Production (end users)** → API-based pipeline only (`extractor.py`):
- `pipeline.py` MUST import from `extractor`, NOT `detector`
- Both valve list CSV and instrumentation index CSV are generated via OpenRouter Vision API
- This is what customers see — 93% recall, battle-tested

**Internal/training (team only)** → Offline model (`detector.py`):
- Used for annotation review, YOLO training, accuracy benchmarking
- Run `detector.py` manually or in a separate script — never wire it into the production pipeline
- Goal: get offline recall to ≥93% before considering a switch

**Rule**: `pipeline.py` line 15 must always read `from extractor import ...` — never `from detector import ...`
If someone changes this by mistake, revert it immediately. The offline detector is NOT production-ready yet (73% recall vs 93% API).

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

## SaaS Features (on feature/multi-cloud-saas, not yet on main)

- **Credits ledger**: every balance change via `webapp/credits.py` — never UPDATE `credits_remaining` directly; always via `grant/deduct/refund`. Invariant: `SUM(delta) == credits_remaining` per user.
- **API keys**: `qk_<32-hex>` format; stored hashed (pbkdf2_sha256). Full key shown once via `?new_key=` URL param after creation. `key_prefix` = first 8 chars for lookup.
- **Admin panel v2**: `/admin/dashboard`, `/admin/credits`, `/admin/feedback`, `/admin/plans` — pass `users_map = {u.id: u for u in ...}` to templates (NOT `users` — collides with `user` context var for current user)
- **User account pages**: `/account`, `/account/api-keys`, `/account/billing`
- **REST API v1**: `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/account` — auth via `Authorization: Bearer qk_...` OR cookie JWT; returns 401 (not 303 redirect) on failure
- **Pre-flight credit check**: `fitz.open(pdf).page_count` for page count → deduct before enqueue; `pipeline_runner.py` refunds on failure

## Webapp Features (production at https://dev.theqong.com)

- Login/register (JWT cookie auth). Admin: `admin` (see memory for current password)
- **Roles (3-tier)**: `super_admin` (all jobs + admin menu), `annotator` (all jobs visible + /annotate queue, no admin panel), `user` (own jobs only)
- Public `/register` creates inactive account (`is_active=False`) — super_admin approves at `/admin/users`
- Admin-created users (via `/admin/users` modal) are active immediately
- First-ever registered user auto-promoted to super_admin; existing `admin` account promoted on startup
- Upload one or more P&ID PDFs → one background job per file (serialized via `_pipeline_lock`)
  - Form field: `name="files"` (multiple). Single file → redirect to job detail; batch → redirect to dashboard
  - P&ID number override only applied when single file uploaded
- Dashboard: job list with status, valve count, processing time
- Job detail: valve table, collapsible AI log, engineer feedback
- Control valve toggle, job re-run, CSV download per job
- Auto-extract Drawing No. from title block (bottom-right 40%×22% crop)
- **Per-user file storage**: uploads → `uploads/{user_id}/`, job outputs → `job_outputs/{user_id}/{job_id}/`
  - `get_job_dir(job)` in `config.py` — checks new path first, falls back to legacy `job_outputs/{job_id}/`
- **Super admin + annotator see all jobs**: `_can_access_job(job, user)` in `jobs.py` — owner OR super_admin OR annotator can view/download/rerun; dashboard shows User column for both
- **Instrumentation Index download**: `/jobs/{id}/download-inst-index` endpoint; button shown on job detail when ready

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{job_id}/tmp/` (never commit)

## Deployment (Production — Hetzner, legacy)

- Server: `root@157.180.20.168` (Ubuntu 24.04, aaPanel) — still serving `main` branch at https://dev.theqong.com
- App: FastAPI + uvicorn, port 8001, systemd `qong_poc`
- Nginx: `/www/server/panel/vhost/nginx/dev.theqong.com.conf`
- Code: `/www/wwwroot/qong_poc/`, auto-deploy via GitHub webhook
- **To deploy to Hetzner**: `git push origin main` (webhook triggers pull + restart)
- **After adding new pip dependencies**: SSH in and run `venv/bin/pip install -r requirements-webapp.txt` manually, then `systemctl restart qong_poc`

## Deployment (GCP — active, dev branch)

- **Live at**: https://dev.qongsystems.com
- **VM**: `qong-dev-server`, `e2-standard-2`, zone `asia-southeast1-c`, IP `34.126.93.103` (static, reserved — won't change on stop/start)
- **DNS**: `dev.qongsystems.com` A record managed on GoDaddy (ns53/ns54.domaincontrol.com) — update A record there if IP ever changes
- **VM OAuth scopes**: set to `cloud-platform`; updated 2026-05-05. **NOTE: `gsutil` has a credentials bug on this VM despite correct scopes — always use `gcloud storage` instead.** `backup.sh` and `restore.sh` already use `gcloud storage`.
- **OS**: Debian 12 (bookworm), user `maahedev`
- **Code**: `/app/qong_poc/` (branch `dev`)
- **Auto-deploy**: every push to `dev` branch triggers GitHub Actions → SSH → `git reset --hard origin/dev` + `docker compose build/up` (workflow: `.github/workflows/deploy-dev.yml`; GitHub secret name: `GSP_DEV_SSH_KEY`; uses `webfactory/ssh-agent@v0.9.0` — appleboy/ssh-action silently drops the key)
- **Access**: `gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="..."`
- **Local gcloud**: installed at `/opt/homebrew/share/google-cloud-sdk/bin/gcloud`; add to PATH: `export PATH=/opt/homebrew/share/google-cloud-sdk/bin:"$PATH"`; auth: `theqongglobal@gmail.com`; project: `project-7555468d-d13a-482e-9ae`
- **All docker commands need `sudo`** on GCP VM: `sudo docker compose ...`
- **Deploy key**: `~/.ssh/id_ed25519_qong_product` on VM; SSH alias `qong-product` in `~/.ssh/config`
- **SSL**: Let's Encrypt cert via certbot standalone; `/etc/letsencrypt/live/dev.qongsystems.com/` mounted read-only into nginx container; auto-renews via systemd timer
- **nginx**: ports 80 (HTTP→HTTPS redirect) + 443 (HTTPS); webapp at `/`, Label Studio at `/ls/`; `client_max_body_size 100M` required for PDF uploads; security headers (X-Frame-Options, HSTS, nosniff, Referrer-Policy) and rate limiting (5r/m `/login`, 10r/m `/api/v1/jobs`) are intentional — do not remove
- **GitHub Actions workflow IPs**: both `deploy-dev.yml` and `backup.yml` use `34.126.93.103` — if VM IP ever changes, update both files
- **GCP Firewall rules**: `qong-allow-http-https` (tcp:80,443), `qong-allow-web` (tcp:8000,9000,9001) — tag `qong-server` on VM
- **LS_API_KEY**: set in `/app/qong_poc/.env` after logging into Label Studio; restart `web` + `cpu-worker` after setting

### GCP — To redeploy manually after code changes:
```bash
gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="cd /app/qong_poc && git pull && sudo docker compose build web cpu-worker && sudo docker compose up -d web cpu-worker && sudo docker compose restart nginx"
```

### GCP — Fresh Postgres: create admin user on first deploy:
```bash
sudo docker compose exec web python3 -c "
from webapp.database import SessionLocal
from webapp import models, auth
db = SessionLocal()
u = models.User(username='admin', email='admin@qongsystems.com', password_hash=auth.pwd_context.hash('Qong@2024'), role='super_admin', is_active=True, credits_remaining=999)
db.add(u); db.commit()
print('admin created')
"
```

### GCP — After nginx restart, always restart nginx one more time if 502:
Rebuilt containers get new IPs; nginx caches old IP → 502. Fix: `sudo docker compose restart nginx`

## Repo
- **Repo**: `Qong-Systems/qong_product` (migrated from `Winn-Projects/qong_poc` in Apr 2026)
- SSH alias for Qong-Systems GitHub (local): `qongsystems`
- SSH alias for Qong-Systems GitHub (GCP VM deploy key): `qong-product` (key: `~/.ssh/id_ed25519_qong_product` on VM)
- SSH alias for Winn-Projects GitHub (legacy, local only): `winn-projects`

## DB Schema Notes

### New tables (feature/multi-cloud-saas, defined as SQLAlchemy models in models.py)
- `api_keys` — `id, user_id, name, key_prefix(8), key_hash, created_at, last_used_at, revoked_at`
- `credit_transactions` — ledger: `id, user_id, delta(signed), balance_after, reason, job_id, meta(JSON), created_at`
- `billing_plans` — `id, name, credits, price_usd_cents, is_active, stripe_price_id, created_at`
- `user_feedback` — `id, user_id(nullable for anon), category, subject, message, page_url, status, admin_notes, created_at`

### New user columns (feature/multi-cloud-saas)
- `credits_remaining INTEGER DEFAULT 10`, `tier VARCHAR DEFAULT 'trial'`, `organization VARCHAR`

### SQLite (main branch / local dev fallback)
- SQLite at `data/webapp.db` inside container — mounted via named Docker volume `webapp_db:/app/data`
- On fresh clone: named volume auto-created by Docker (no manual file creation needed)
- Legacy path was `webapp.db` in project root — **migrated to `data/webapp.db` on 2026-05-02** (39 jobs, 4 users moved). Root `webapp.db` is now stale/unused.
- `run_migrations()` in `database.py` handles ALTER TABLE on startup
- Job columns: `processing_time` (Float), `processing_log` (Text), `include_control_valves` (Bool),
  `original_filename` (Str) — used to derive `drawing_stem` for corrections lookup
- User columns added: `role` (Str default `'user'`), `is_active` (Bool default `True`)
- Job columns added: `ls_project_id` (Int), `ls_synced` (Bool) — Label Studio sync state
- Job columns added: `output_inst_index_path` (Str) — path to instrumentation_index.csv when generated
- Job columns added: `output_inst_datasheet_path` (Str) — path to instrument_datasheets.zip when generated

## Admin / Password Reset (production server)

- App uses **pbkdf2_sha256** (NOT bcrypt): `CryptContext(schemes=["pbkdf2_sha256"])` in `webapp/auth.py`
- To reset a password directly in SQLite (e.g. after DB migration):
  ```bash
  cd /www/wwwroot/qong_poc && venv/bin/python3 -c "
  from passlib.context import CryptContext; import sqlite3
  h = CryptContext(schemes=['pbkdf2_sha256']).hash('Qong@2024')
  c = sqlite3.connect('data/webapp.db'); c.execute('UPDATE users SET password_hash=? WHERE username=?', (h,'admin')); c.commit()
  "
  ```
- Instrumentation Index / Datasheets buttons only appear on job detail when `output_inst_index_path` is set — old jobs need a **Re-run** to generate them

## Critical Bug Fixes (already applied)

1. **Corrections not applying**: `pipeline_runner.py` passes `input.pdf` as path →
   `drawing_stem` was always `"input"`. Fixed: pass `original_filename` through to `pipeline.run()`.
2. **DB valve size NOT DEFINED**: Parser now auto-assigns size=`"2"` for DB category.
3. **P&ID No truncated**: Title block prompt updated to capture full revision suffix (e.g. `24C7-D`).
4. **Jinja2 template path**: Use `Path(__file__).parent.parent / "templates"` (absolute) in all 3 router files.
5. **Stale processing jobs**: Reset to `failed` on app startup.
6. **Starlette 1.0.0 broke TemplateResponse**: `TypeError: unhashable type: 'dict'` on every page load. Fix: pin `fastapi>=0.111.0,<0.115.0` and `starlette>=0.37.0,<0.41.0` in `requirements-webapp.txt`.
7. **`requests` missing from requirements-webapp.txt**: `label_studio_client.py` uses it — must include `requests>=2.31.0`.
8. **PDF inline viewing**: `FileResponse` forces download. Use `starlette.responses.Response` with `media_type="application/pdf"` and `Content-Disposition: inline; filename="..."` to open in browser tab.

## Postgres Compatibility Fixes (applied 2026-05-05 for GCP deployment)

9. **`psycopg2-binary` missing**: Not in `requirements-webapp.txt` — Postgres connection fails at startup. Added: `psycopg2-binary>=2.9.9`
10. **`AUTOINCREMENT` is SQLite-only**: Raw SQL `CREATE TABLE ... INTEGER PRIMARY KEY AUTOINCREMENT` fails on Postgres. Fix: removed raw SQL table creation from `run_migrations()`; replaced with `from webapp import models; Base.metadata.create_all(engine)` — dialect-agnostic, idempotent.
11. **Boolean seed values**: Postgres `billing_plans.is_active` is `BOOLEAN` — inserting `1`/`0` raises `DatatypeMismatch`. Use `TRUE`/`FALSE` in seed SQL.
12. **RQ `Connection` removed**: `from rq import Connection` fails on rq>=1.16. Fix in `workers/cpu_worker.py`: `Worker(queues=[Queue("cpu", connection=conn)], connection=conn)` — no `with Connection(conn):` wrapper needed.
13. **nginx 502 after container rebuild**: Rebuilt containers get new Docker IPs; nginx caches the old one → 502. Always `sudo docker compose restart nginx` after rebuilding `web`.

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

### Annotation Classes (13 YOLO classes)
- Valves (7): `valve_bf`, `valve_bv`, `valve_ck`, `valve_gl`, `valve_db`, `valve_cv`, `valve_gen`
- Actuators (3): `actuator_motor`, `actuator_pneu`, `actuator_sol`
- Instruments (3): `inst_bubble` (all circle tags — PT/TT/FT/LT/PDT/PI/PS/ZS/etc.), `inst_cv` (FCV/XV), `inst_solenoid` (FY/XY)
- **inst_bubble is ONE class** — YOLO finds the circle, OCR reads the type code. Don't split by type.

## Instrumentation Index (merged to main)

Pipeline now generates a 30-column Instrumentation Index CSV alongside the valve CSV:
- `instrument_prompts.py` — Vision prompts (instrument-focused, excludes valves)
- `instrument_parser.py` — `InstrumentRow` dataclass + `TYPE_MAP` (22 type codes → io_type, signal_type)
- `instrument_validator.py` — 30-column CSV writer
- `extractor.py` — `extract_instruments()` single Vision pass per tile
- `pipeline.py` — Stage 5 writes `instrumentation_index.csv` to job dir alongside `valve_list.csv`
- DB column: `output_inst_index_path` on `jobs` table; stored by `pipeline_runner.py` on success

## Instrument Datasheets (merged to main)

Pipeline Stage 5c generates a ZIP of per-instrument HTML spec forms alongside the CSVs:
- `instrument_datasheet.py` — `generate_datasheet_html(inst)` + `write_datasheet_zip(inst_rows, zip_path)`
- Output: `instrument_datasheets.zip` in job dir; one `.html` file per instrument tag
- Fields from P&ID: tag, type, line, equipment, system. Unknown fields → `TBD` (grey italic) or `LATER` (red italic)
- DB column: `output_inst_datasheet_path` on `jobs` table; stored by `pipeline_runner.py` on success
- Download endpoint: `/jobs/{id}/download-inst-datasheets` → ZIP served as `instrument_datasheets_{pid_no}.zip`
- Button shown on job detail page when `output_inst_datasheet_path` is set

## New Modules (feature/multi-cloud-saas)

- `webapp/storage.py` — S3 adapter (`put_file`, `get_file`, `presigned_url`, `list`, `exists`, `delete`); singleton via `get_storage()`
- `webapp/queue.py` — RQ wiring: `cpu_q = Queue("cpu", ...)`, `gpu_q = Queue("gpu", ...)`
- `webapp/credits.py` — ledger helpers: `grant`, `deduct`, `refund`, `check_balance`, `get_balance`; all commit to `credit_transactions`
- `webapp/routers/api_v1.py` — REST API endpoints; `_get_api_user` dep accepts Bearer OR cookie
- `webapp/routers/account.py` — user-facing `/account/*` and `/feedback` routes

## Testing Pattern (unit tests)

- In-memory SQLite for FastAPI TestClient requires `StaticPool` — without it each new connection gets a fresh empty DB and ORM-created tables vanish:
  ```python
  from sqlalchemy.pool import StaticPool
  engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
  ```
- Override `get_db`: `app.dependency_overrides[get_db] = lambda: db_session` — must return same session as fixtures use
- `get_current_user` raises HTTP 303 (redirect to /login), not 401 — API-facing deps must catch `HTTPException` and re-raise as 401
- Run all unit tests: `python3 -m pytest tests/unit/ -v`

## Docker Services

### Additional services (feature/multi-cloud-saas, in docker-compose.yml)
- `postgres` — Postgres 16; `DATABASE_URL=postgresql://...`; named volume `postgres_data`
- `redis` — Redis 7 for RQ job queue; `REDIS_URL=redis://redis:6379/0`
- `minio` — S3-compatible local storage; `STORAGE_ENDPOINT_URL=http://minio:9000`, `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`
- `cpu-worker` — RQ worker consuming `cpu` queue; runs pipeline jobs off the main web process
- `database.py` reads `DATABASE_URL` env var — falls back to SQLite when unset

### Original five services in `docker-compose.yml`:
- `web` — FastAPI webapp (port 8000)
- `label-studio` — annotation tool (port 8080); tiles mounted at `/tiles` inside container; exports land in `annotate/exports/`
- `nginx` — reverse proxy; **`absolute_redirect off` is REQUIRED** — without it nginx appends the port to redirect URLs
- nginx LS route list: `/ls/`, `/api/`, `/static/`, `/react-app/`, `/media/`, `/data/`, `/user/`, `/projects/`, `/tasks/`, `/dm/`, `/organization/` — all proxied to LS; webapp uses none of these prefixes
- **`LABEL_STUDIO_HOST=https://dev.qongsystems.com/ls`** — LS derives `FORCE_SCRIPT_NAME=/ls` from the URL path in `core/settings/base.py`; the bare `FORCE_SCRIPT_NAME` env var is silently ignored by LS
- **Do NOT add `proxy_redirect / /ls/`** in the `/ls/` nginx block — once FORCE_SCRIPT_NAME is working, this causes double-prefix (`/ls/ls/` redirect loops)
- port 9001 = direct LS fallback (local only); `LS_EXTERNAL_URL` defaults to `http://localhost:9001`
- `label-studio-mcp` — Label Studio MCP server (port 8090)
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

## Non-Standard Tag Format P&IDs

Some customer P&IDs use tags like `VB25`, `VB40 2090`, `VBPP40` — no `AreaCode-TypeCode-SerialNo` pattern.
- Parser skips all 0 valves → valve count = 0 in webapp. **This is not a bug** — it's a different naming convention.
- Instrument index extraction still works (instrument bubbles are standard).
- To support these: extend `parser.py` with new regex patterns alongside existing ones (additive, never modify working patterns).

## Offline Detector Recall Improvements (feature/own-system, committed cf21758)

- `_extract_tags_from_tile()` — row-based OCR token clustering (40px y-tolerance), groups 1–4 tokens to reassemble fragmented tags
- `_targeted_crop_ocr()` — 400×400px crop from full-page image centered on YOLO detection; major win for noisy/hatched tiles
- TAG_RE: `(?<!\d)(\d{2})-([A-Z]{2,4})-(\d{6})(?!\d)` — exact 6-digit serial, no leading-digit leakage
- Benchmark (2 drawings): 73.3% recall (44/60), up from 53.4% baseline
- Annotated PDF named after source drawing: `INPUT-MUK-..._annotated.pdf` (not timestamped CSV name)

## Server Security (GCP VM — applied 2026-05-06)

- **All internal ports bound to `127.0.0.1`** in docker-compose.yml — postgres (5432), redis (6379), minio (9100/9101), web (8000), label-studio (8080) are NOT reachable from the internet
- **GCP firewall**: only `qong-allow-http-https` (80/443) and `default-allow-ssh` (22) remain; `qong-allow-web` and `default-allow-rdp` were deleted — do NOT recreate them
- **`.env` permissions**: `chmod 600 /app/qong_poc/.env` — must stay 600; re-apply after any manual file copy
- **After port binding changes in docker-compose.yml**: use `--force-recreate` — plain `up -d` won't rebind already-running containers
- **MinIO bucket**: anonymous download removed — use `storage.presigned_url()` for download links; never run `mc anonymous set download` again

## Temporary Files

All intermediate files go in `job_outputs/{id}/tmp/` — never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.

## Multi-Cloud Migration (in progress on dev branch)

Moving from Hetzner (SQLite + threads) → GCP (Postgres + Redis + RQ + GCS).

**Phases complete**: A1 (S3 adapter + MinIO), A2 (Postgres + RQ), A3 (GCP VM live, data migrated), A4 (GPU worker on Windows — deps, model, ONNX session, Redis all verified), A6 (/healthz, nightly pg_dump→GCS, restore script), B1–B2 (credits ledger + pre-flight), B3–B4 (admin panel v2 + account pages), B5 (REST API v1)

**Phases pending**:
- A5 — Pre-annotations: push YOLO predictions to Label Studio after GPU inference (needs callback endpoint)
- B6/B7 — Stripe Checkout (deferred until 5+ paying customers)

**A6 details**:
- `scripts/backup.sh` — pg_dump + `gcloud storage rsync uploads/ job_outputs/` → `gs://qong-backups`; 30-day retention on pg_dumps
- `scripts/restore.sh` — full server rebuild from GCS backup in <10 min
- `.github/workflows/backup.yml` — runs 02:00 IST daily via `schedule:`; manual trigger via `workflow_dispatch` in Actions UI
- **GCS bucket**: `gs://qong-backups` (asia-southeast1); VM service account needs `roles/storage.objectAdmin`
- **Nightly backup**: GitHub Actions SSHs into VM → runs `scripts/backup.sh` using same `GSP_DEV_SSH_KEY` secret

Full architecture plan: `sparkling-exploring-blum.md` in Claude plans folder.

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
- `inference/engine.py` — YOLO ONNX + PaddleOCR, zero imports from main repo
- `requirements.txt` — minimal: rq, redis, onnxruntime-gpu, paddleocr==2.9.1, requests
- Local path on dev machine: `/Users/maahedev/allcode/experiments/qong/qong-gpu-worker/`

**Windows setup (completed 2026-05-06)**:
- Python: `C:\Program Files\Python311\python.exe` (3.11.9)
- Worker dir: `C:\Users\qongsystems\qong-poc-gpu\`
- ONNX model: `C:\Users\qongsystems\qong-poc-gpu\models\best.onnx` (45 MB)
- `.env`: `REDIS_URL=redis://100.127.190.88:6379/0`, `MODEL_PATH=models/best.onnx`
- PaddleOCR models cached in `C:\Users\qongsystems\.paddleocr\whl\`
- To start: `cd C:\Users\qongsystems\qong-poc-gpu && "C:\Program Files\Python311\python.exe" worker.py`

**ONNX on Windows**: `onnxruntime-gpu 1.25.1` installed; currently uses CPU (CUDA 12 + cuDNN 9 not yet installed)
- Providers available: `TensorrtExecutionProvider, CUDAExecutionProvider, CPUExecutionProvider`
- Falls back to CPU silently — inference works, just slower

**paddleocr version pinning**: always use `paddleocr==2.9.1` on Windows
- paddleocr 3.x pulls in `paddlex → modelscope + huggingface_hub + pandas` — these CDNs stall for hours on Windows
- paddleocr 2.9.1 installs entirely from PyPI; all deps download in 5-10 min
- API change: 2.x uses `.ocr(path, cls=True)` returning `[[[bbox,(text,conf)],...]]`; 3.x uses `.predict(path)` returning dicts
- engine.py uses 2.x API — do not upgrade paddleocr without updating engine.py

**Windows pip install patterns**:
- Install in stages: core packages first (rq, redis, onnxruntime-gpu, numpy, Pillow, paddlepaddle), then paddleocr separately
- Use `--timeout 30 --retries 3` flags to avoid silent stalls on slow CDNs
- If pip stalls (same last line for 5+ min with file size not growing): `taskkill /PID <pid> /F`, retry
- `winget` does NOT work over SSH (requires desktop session) — use `Invoke-WebRequest` + silent installers

**SSH to Windows via GCP jump**:
```bash
gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="sshpass -p '123456' ssh -o StrictHostKeyChecking=no qongsystems@100.91.199.103 'YOUR_COMMAND'"
```
- File copy: SCP to GCP VM first (`gcloud compute scp`), then `sshpass scp` to Windows
- For Python scripts: SCP the .py file, then run `"C:\Program Files\Python311\python.exe" C:\path\to\script.py`
- Inline Python `-c` with complex strings fails due to nested quoting — always write to a file first

**Security design**:
- Windows box has ONLY `REDIS_URL` — no MinIO/DB/GCS credentials
- Tiles passed as presigned URLs (1-hour expiry, job-specific) — Windows cannot access other jobs' files
- `tempfile.TemporaryDirectory` in `run_inference_job()` guarantees all tile files deleted after every job, even on crash

**Windows SSH** (enable with one command as Administrator):
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; Start-Service sshd; Set-Service -Name sshd -StartupType Automatic; New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```
- Password auth disabled by default — also run: `Add-Content "C:\ProgramData\ssh\sshd_config" "\nPasswordAuthentication yes"; Restart-Service sshd`

## GitHub — Org Separation

- **`gh` CLI is authenticated as `tarunhere`** — admin of `Winn-Projects` only; cannot create repos in `Qong-Systems`
- **`git push` to Qong-Systems** works via SSH alias `qongsystems` (key: `~/.ssh/id_qongsystems`)
- **To create a new Qong-Systems repo**: ask user to create it manually on GitHub, then push: `git remote add origin git@qongsystems:Qong-Systems/<repo>.git && git push -u origin main`
- **NEVER create a Qong-Systems repo under Winn-Projects** — completely different org/domain
