# Webapp & SaaS

FastAPI webapp, SaaS layer, DB schema, admin operations. See `CLAUDE.md` for top-level rules.

## Webapp Features (production at https://dev.qongsystems.com)

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
- **Annotated PDF download**: `/jobs/{id}/annotated-pdf` endpoint — numbered bounding boxes per detected valve (colour-coded by detection source). Written to `job_dir/annotated.pdf` by Stage 5 of `pipeline.py` via the `annotated_pdf_path` kwarg. Button appears on job detail when `output_annotated_pdf_path` is set.
- **Run History panel** (per-attempt observability): every pipeline attempt writes a `job_runs` row. Panel on job detail shows attempt #, status, current/final stage, duration, last heartbeat, killer reason, and per-stage timings. Stale banner is driven by the heartbeat (not elapsed-minutes guessing).
- **Serving PDFs inline**: use `starlette.responses.Response` with `media_type="application/pdf"` and `Content-Disposition: inline; filename="..."` — `FileResponse` forces a download instead

## SaaS Features (merged to dev branch)

- **Credits ledger**: every balance change via `webapp/credits.py` — never UPDATE `credits_remaining` directly; always via `grant/deduct/refund`. Invariant: `SUM(delta) == credits_remaining` per user.
- **API keys**: `qk_<32-hex>` format; stored hashed (pbkdf2_sha256). Full key shown once via `?new_key=` URL param after creation. `key_prefix` = first 8 chars for lookup.
- **Admin panel v2**: `/admin/dashboard`, `/admin/credits`, `/admin/feedback`, `/admin/plans` — pass `users_map = {u.id: u for u in ...}` to templates (NOT `users` — collides with `user` context var for current user)
- **User account pages**: `/account`, `/account/api-keys`, `/account/billing`
- **REST API v1**: `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/account` — auth via `Authorization: Bearer qk_...` OR cookie JWT; returns 401 (not 303 redirect) on failure
- **Pre-flight credit check**: `fitz.open(pdf).page_count` for page count → deduct before enqueue; `pipeline_runner.py` refunds on failure

## DB Schema Notes

### New tables (defined as SQLAlchemy models in models.py)
- `api_keys` — `id, user_id, name, key_prefix(8), key_hash, created_at, last_used_at, revoked_at`
- `credit_transactions` — ledger: `id, user_id, delta(signed), balance_after, reason, job_id, meta(JSON), created_at`
- `billing_plans` — `id, name, credits, price_usd_cents, is_active, stripe_price_id, created_at`
- `user_feedback` — `id, user_id(nullable for anon), category, subject, message, page_url, status, admin_notes, created_at`

### New user columns
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
- Job columns added: `output_annotated_pdf_path` (Str) — path to annotated.pdf (numbered bounding boxes) when generated
- **`job_runs` table** (Phase 1 observability) — one row per pipeline attempt. Columns: `id, job_id, attempt_num, rq_id, started_at, ended_at, status (running|done|failed|killed), current_stage, last_heartbeat_at, error_msg, error_traceback, stage_timings (JSON), killer`. Created via `Base.metadata.create_all` on startup; no raw SQL migration needed.

## Admin / Password Reset

- App uses **pbkdf2_sha256** (NOT bcrypt): `CryptContext(schemes=["pbkdf2_sha256"])` in `webapp/auth.py`
- To reset a password on GCP (Postgres):
  ```bash
  gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --command="cd /app/qong_poc && sudo docker compose exec -T web python3 -c \"
  from webapp.database import SessionLocal; from webapp import models, auth
  db=SessionLocal(); u=db.query(models.User).filter_by(username='admin').first()
  u.password_hash=auth.pwd_context.hash('NEW_PASSWORD'); db.commit(); print('reset')\""
  ```
- Instrumentation Index / Datasheets buttons only appear on job detail when `output_inst_index_path` is set — old jobs need a **Re-run** to generate them

## New Modules

- `webapp/storage.py` — S3 adapter (`put_file`, `get_file`, `presigned_url`, `list`, `exists`, `delete`); singleton via `get_storage()`
- `webapp/queue.py` — RQ wiring: `cpu_q = Queue("cpu", ...)`, `gpu_q = Queue("gpu", ...)`
- `webapp/credits.py` — ledger helpers: `grant`, `deduct`, `refund`, `check_balance`, `get_balance`; all commit to `credit_transactions`
- `webapp/routers/api_v1.py` — REST API endpoints; `_get_api_user` dep accepts Bearer OR cookie
- `webapp/routers/account.py` — user-facing `/account/*` and `/feedback` routes
- `webapp/watchdog.py` (Phase 2 observability) — asyncio loop started at FastAPI startup. Sweeps every 5 min, marks `JobRun` rows with no heartbeat for >90s as `killed` (killer=`heartbeat-watchdog`) and flips the parent `Job` to `failed` if still `processing`. Constants: `STALE_HEARTBEAT_SECONDS=90`, `WATCHDOG_INTERVAL_SECONDS=300`.
- `webapp/pipeline_runner.py` heartbeat thread (Phase 1 observability) — `_HeartbeatThread` writes `last_heartbeat_at` + parses log_buffer for latest "Stage N: ..." every 30s; uses fresh short-lived sessions so heartbeat writes never conflict with the main pipeline transaction. JobRun finalize also uses a fresh session (avoids the same-transaction status-flip bug that broke job 39's first rerun).

## Testing Pattern (unit tests)

- In-memory SQLite for FastAPI TestClient requires `StaticPool` — without it each new connection gets a fresh empty DB and ORM-created tables vanish:
  ```python
  from sqlalchemy.pool import StaticPool
  engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
  ```
- Override `get_db`: `app.dependency_overrides[get_db] = lambda: db_session` — must return same session as fixtures use
- `get_current_user` raises HTTP 303 (redirect to /login), not 401 — API-facing deps must catch `HTTPException` and re-raise as 401
- Run all unit tests: `python3 -m pytest tests/unit/ -v`
