# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read order at the start of every session (do NOT skip)

1. **`SESSION_STATE.md`** — what the previous session did, where it stopped, next concrete step, what's blocked, gotchas the previous session learned. Short on purpose; the journal lives in FEATURES.md.
2. **`FEATURES.md`** — append-only history of every meaningful decision, model swap, threshold change, architecture choice. Read the most recent 5–10 entries.
3. **This file (`CLAUDE.md`)** — repo conventions, branch policy, environment, security rules.
4. **The user's current message** — what they want done now.

## Must do during every session

- When implementing a feature, behavior change, model swap, or architecture decision: **append one entry to `FEATURES.md`**. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`. Recording the *reasoning* matters more than the choice. Format inside FEATURES.md.
- For long discussions, link out to `docs/decisions/NN-title.md` from the FEATURES.md entry.

## Must do at the end of every session

- **Overwrite `SESSION_STATE.md` in full** with: what happened this session, where you stopped (file paths, commit hashes), next concrete step, what's blocked, what the next session should know (gotchas, lessons). Don't accumulate — overwrite. The journal accumulates in FEATURES.md, not here.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV today.
Evolving into a **human-in-the-loop digital twin platform** (multi-page graph + new deliverables: valve list, instrument index, datasheets, BOM, loop trace, equipment list) over the next 6-9 months. See FEATURES.md #01 and the plan at `/Users/maahedev/.claude/plans/async-soaring-puppy.md` for the full trajectory.

Headline metric long-term: graph isomorphism (`networkx.is_isomorphic`) — measures topological correctness of the extracted graph vs human ground truth. Short-term (existing product): ≥90% recall on valve identification.

**Current status:** Production webapp live at https://dev.qongsystems.com. v1-10 YOLO ONNX (23 classes incl. flow direction) deployed 2026-06-05 — FEATURES #30. Spec A (D1, D1.5, D2, D3-4, D5) functionally complete and verified. `canonical_entities` DB index live (FEATURES #34) with 1,304 rows across 49 jobs, cross-job query surface at `/admin/entities` (FEATURES #36).
**Next phase:** Graph-extraction v0 (digital twin) — design + implementation plan at `docs/superpowers/{specs,plans}/2026-06-0{5,6}-graph-extraction-*.md`. All work is on `dev`/`main` (the old `dt/*` track is retired — see below).

## Detail Index (read on demand)

- [`docs/claude/pipeline.md`](docs/claude/pipeline.md) — P&ID format, CSV schema, architecture, key files, corrections, ground truth, instruments, datasheets, non-standard tags, offline detector recall
- [`docs/claude/webapp.md`](docs/claude/webapp.md) — Webapp & SaaS features, DB schema, admin/password reset, modules, testing
- [`docs/claude/deployment.md`](docs/claude/deployment.md) — GCP VM, docker services, server security, multi-cloud migration
- [`docs/claude/training_and_gpu.md`](docs/claude/training_and_gpu.md) — Annotation, training lessons, offline detector, Label Studio sync, GPU worker (Tailscale/Windows/CUDA/EasyOCR)
- [`docs/claude/deliverables.md`](docs/claude/deliverables.md) — Deliverables subsystem (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

## Branches

**Current production-track layout (clean baseline established 2026-06-03 at `0f4f3c4`):**

- `dev` — active development; auto-deploys to `dev.qongsystems.com` on every push via `.github/workflows/deploy-dev.yml`.
- `qa` — QA release candidate; deploys to `qa.qongsystems.com` via **manual** `workflow_dispatch` on `.github/workflows/deploy-qa.yml`. **Workflow default ref is `dev`, not `qa`** — to deploy the `qa` branch, pass `ref: qa` on dispatch (or change `default: 'dev'` in the workflow file). Branched from `dev` 2026-06-03.
- `main` — reserved for future production at `app.qongsystems.com`. No `deploy-main.yml` exists yet (task D in `SESSION_STATE.md`). Do not push until prod infra is provisioned.

**Feature-branch policy:** branch off `dev`, merge back via PR. Stale branches `feature/digital-twin`, `feature/observability-job-runs`, `feature/instrument-index-improvements` were deleted locally on 2026-06-03; their `origin/*` refs are retained on GitHub for now but are reference-only — do **not** branch from them. `feature/multi-cloud-saas` was superseded by `dev` (all phases A1-A3, B1-B5 merged in).

## Experimental track (`dt/*` branches) — RETIRED 2026-06-17

**There are no `dt/*` branches anymore. All work happens on `main`/`dev`** via the
normal feature-branch policy (branch off `dev`, PR back). Ignore any older
reference to `dt/main` / `dt/<topic>` / "merge at handover" / `[DT]` FEATURES
prefixes — that parallel-track model is no longer used.

- The graph-extraction / digital-twin code that was prototyped in
  `experiments/digital_twin/` is folded into the normal codebase; new graph work
  lands on `dev` (then `main`) like any other feature, with a standard FEATURES.md
  entry (no `[DT]` prefix).
- SESSION_STATE.md no longer needs a "team / experimental" track label.

## Docker-First Rule

**NEVER install any service or tool directly on the local Mac.** All services (nginx, databases, annotation tools, etc.) must be added as Docker containers in `docker-compose.yml`. This ensures the compose file can be pushed to production as-is.

## Quick Start (local dev)

```bash
docker compose up -d                                           # start all services
docker compose logs -f web                                     # tail webapp logs
docker compose exec web python3 -m pytest tests/unit/ -v      # run unit tests
```

- Webapp: http://localhost:8000
- Label Studio (direct): http://localhost:9001
- Label Studio (via nginx): http://localhost:9000/ls/

## VM access (production troubleshooting)

- SSH via IAP (plain port 22 is firewalled): `gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --tunnel-through-iap --command="..."` — works because gcloud is authed as `theqongglobal@gmail.com`. Same `--tunnel-through-iap` flag on `gcloud compute scp`.
- **GCP VMs (dev/intake) stopped 2026-06-02** post-AWS-cutover (FEATURES #21). To restart for rollback: `gcloud compute instances start qong-dev-server --zone=asia-southeast1-c` (new ephemeral IP) + flip Cloudflare A-record. Disks + daily snapshots + GCS retained until Phase 4 (7-day soak).
- **Don't use `gcloud compute scp --tunnel-through-iap` for files > ~50 MB** — IAP throttles to ~0.3 MB/s and stalls. Route via GCS instead (`gcloud storage cp` from VM hits ~128 MB/s), then pull GCS → local at ~16 MB/s.
- **EC2 access is SSM Session Manager only** (no public 22, no key pair). `aws ssm start-session --target i-xxx --region ap-south-1 --profile tnbqong`, or `aws ssm send-command` for non-interactive scripts. Both EC2s share IAM `may26-ec2-ssm-role`.
- **EC2 deploy-key remote URL must use the `qong-product` SSH alias**, not bare `git@github.com:`. If `git pull` fails silently with "Permission denied (publickey)" on a freshly-provisioned EC2: `git remote set-url origin git@qong-product:Qong-Systems/qong_product.git`. One-time fix per VM.
- **SSM RunCommand runs as root** but `/opt/qong` is ubuntu-owned, so `git` aborts ("dubious ownership"). Fix once: `sudo git config --system --add safe.directory /opt/qong`.
- **`aws ssm get-command-invocation` truncates stdout at ~24 KB.** For long bootstraps (docker build + restore + start), split into multiple commands, or run separate state-probe queries after the fact.
- **EC2 can't reach its own public IP** (no hairpin NAT). Inside-VM smoke checks use 127.0.0.1 with `-H "Host: dev.qongsystems.com"`.
- Query production DB from VM: `psql -U postgres` fails (role doesn't exist). Use the ORM via the web container: `sudo docker compose exec -T web python3 -c "from webapp.database import SessionLocal; from webapp.models import Job; s=SessionLocal(); print(s.get(Job, 41).output_csv_path)"`. Avoid f-strings inside `-c` (quoting hell — use `print(label, value)` with `,` separator).
- Job artifact paths: jobs ≥ 40 use org-scoped `/app/job_outputs/{org_id}/{job_id}/`; jobs ≤ 39 use flat `/app/job_outputs/{job_id}/`. Always read the exact path from `Job.output_csv_path` / `output_annotated_pdf_path` in the DB rather than guessing.
- **Deploy `Created`-container 502:** if after a deploy `/` returns 502 but `/healthz` (served by nginx) returns 200, the web/cpu-worker containers are stuck in **`Created`** (hash-prefixed names like `7e47…_qong-web-1`) — a name-collision on `up -d`. Recover: `sudo docker compose -f docker-compose.yml -f docker-compose.override.dev.yml --env-file .env.dev -p qong up -d --force-recreate --remove-orphans web cpu-worker`.
- **Don't push to `dev` while a cpu-worker job is processing** — the deploy recreates the cpu-worker container and kills the running job (it then fails with `"No heartbeat for >90s"`). Wait for the job to reach a terminal state first.
- **Watch a deploy by polling the SPA bundle hash on `/`** (`curl -s https://dev.qongsystems.com/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'`) until it changes — `gh run list` 404s for Qong-Systems (gh is authed as tarunhere/Winn-Projects only). The web build runs on the EC2, so a brief `/` 502 mid-swap is normal.
- **Run ad-hoc Python in the running container via SSM:** `docker cp /tmp/x.py qong-web-1:/tmp/ && sudo docker exec -e PYTHONPATH=/app -w /app qong-web-1 python3 /tmp/x.py`. Use plain `docker exec` (not `compose exec`) from SSM; `PYTHONPATH=/app` + `-w /app` are required or `from webapp import …` fails (a script file puts *its own* dir on `sys.path`, not cwd — unlike `python3 -c`).

## AWS inventory (as of 2026-06-02 — see FEATURES #21)

- **Account:** 449901518037 (`tnbqong` profile). All resources in `ap-south-1`.
- **QA:** EC2 `i-04be6af1fb7929a0c`, data EBS `vol-06bdf1fab12bd2971`. URL https://qa.qongsystems.com. **STOPPED 2026-06-02** to save ~$30/mo. No EIP — restart auto-assigns a fresh public IP, so the CF A-record needs updating on restart (~5 min). Restart: `aws ec2 start-instances --instance-ids i-04be6af1fb7929a0c --region ap-south-1 --profile tnbqong`. If QA will cycle frequently, allocate an EIP first (~$3.65/mo idle, stable IP).
- **Dev:** EC2 `i-0e7b89bd91b67a291` at EIP `13.204.52.248`, data EBS `vol-00152abd9fa8f1bf8` at `/mnt/qong-data`. URL https://dev.qongsystems.com. EIP is free while attached.
- **SSM secrets:** `/may26aws/qong-qa/*` (7 params), `/may26aws/qong-dev/*` (7 params), `/may26aws/hermes-agent/openrouter/key` (sibling workload). Always ap-south-1, never us-east-1.
- **S3:** `qong-pid-archive-2026-06-02` (~1 GB, AES256, versioned) — pre-migration PID backup. Bucket policy grants read to `may26-ec2-ssm-role`.
- **IAM role:** `may26-ec2-ssm-role` (shared by both EC2s). Has SSM + KMS; per-bucket S3 grants via bucket policy.
- **nginx config on each host:** `/etc/nginx/sites-available/qong-{qa,dev}` + cert at `/etc/ssl/qong-{qa,dev}/origin.{crt,key}` + CF IP allowlist `/etc/nginx/cloudflare-ips.conf`. Default_server returns 301 to canonical hostname (not the prior 444 drop).
- **Label Studio on dev** lives at https://ls-dev.qongsystems.com (subdomain hosting, FEATURES #23). Separate nginx vhost at `/etc/nginx/sites-available/qong-dev-ls` proxies to the LS container on `127.0.0.1:8080`. LS data (6 users, 28 projects, 819 tasks, 826 annotations) preserved via the postgres `label_studio` DB restored from GCP's pg_dumpall. Existing GCP LS users log in with their original passwords — no fresh admin account. **QA does NOT host LS publicly** by design.
- **`LABEL_STUDIO_HOST` env var** must match the host LS is reached on, or LS generates redirects to wrong paths (e.g. `/ls/user/login` → 404). Override per env in `docker-compose.override.{env}.yml` `label-studio.environment.LABEL_STUDIO_HOST`. Base compose has the path-based local-dev value; AWS envs override to subdomain.
- **Tile endpoint CORS** for LS canvas access: `webapp/routers/jobs.py:serve_tile` returns `Access-Control-Allow-Origin: *` + `Vary: Origin` (FEATURES #24). LS at `ls-dev.qongsystems.com` loads tile PNGs from `dev.qongsystems.com` cross-origin; without CORS the browser canvas-taint check blocks LS's labeling tools. The handler in `webapp/main.py` is dead — see "Duplicate-route shadow" gotcha above.

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

**Exception:** YOLO inference is permitted in the webapp for bbox-surfacing only (canvas overlay via `Job.gpu_detections`). The CSV/deliverable pipeline still uses `extractor.py` (OpenRouter API). Do not import `detector.py` into `pipeline.py`. The new `webapp/inference.py` is the supported path for in-process inference (FEATURES #28).

## Canonical entity storage — file-first, DB as read-index (FEATURES #34)

**Source of truth for canonical entities is the on-disk `canonical.json`** in each job's output directory. Deliverable generators read it + merge `entity_overrides` at request time. This contract is intentional (no schema migrations on canonical evolution; easy debug).

**The `canonical_entities` DB table is a denormalised read-index** for cross-job queries (admin dashboards, audits, duplicate-tag detection, "all valves of size 8 across customer X's jobs"). Never edit through this table — `entity_overrides` is still the canonical edit store. Mutate via:

- **Online dual-write:** `pipeline_runner.py` calls `webapp.deliverables.canonical_db_index.sync_canonical_to_db(canonical, db)` after every `write_canonical_for_job`. Non-fatal — DB sync failure logs but doesn't roll back job "done" state.
- **Backfill (idempotent):** `python -m webapp.scripts.index_canonical_to_db [--from-db|--dry-run|--job-id N]` populates from on-disk canonical.json for legacy jobs. Safe to re-run.
- **Legacy canonical.json backfill:** `python -m webapp.scripts.backfill_canonical [--from-db]` re-emits canonical.json from CSVs for jobs predating the 2026-05-28 emitter — pair with the index script when a brand-new env is seeded from old data.

Cross-job query surface: `/api/v1/admin/entities` (filter+paginate) and `/api/v1/admin/entities/aggregates` (totals + top-N sub_classes + top-N jobs + duplicate tags). Both `require_super_admin`. UI at `/admin/entities`.

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{org_id}/{job_id}/tmp/` (jobs ≥ 40) or `job_outputs/{job_id}/tmp/` (jobs ≤ 39); never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.
- **Generated secrets must not contain `$`** (use `openssl rand -hex N` — alphanumeric only). Docker Compose treats `$wrv` inside a `.env` value as `${wrv}` and silently substitutes empty, truncating the secret. If a `$`-containing SSM value gets rendered into `.env.*`, escape `$ → $$` (Compose decodes `$$` as literal `$`). Real bug we hit on QA — FEATURES #19.
- **Root-level `*.png` is gitignored** (`/*.png` line in `.gitignore`). Save Playwright / QA screenshots to `themes/screenshots/` (also gitignored), a job-output path, or `tmp/` — never the repo root. Nested PNGs under `design/`, `docs/`, `webapp/` track normally.
- **Local `web`/`cpu-worker` mount only `uploads/`, `job_outputs/`, `webapp_db` — NO source mount.** They run the *built image*, so host edits to any `.py` (esp. repo-root `parser.py`, `pdf_to_tiles.py`, `extractor.py`) won't appear in `docker compose exec web` without `docker compose build`. Test pure-logic changes with host `python3` (stdlib-only modules — `parser.py` needs just `re`) or verify post-deploy.
- **The re-run endpoint is prefix-less: `POST /jobs/{id}/rerun`** (the `jobs.py` router has no prefix), returns a **303** redirect — NOT under `/api/v1`. Frontend callers must use the bare path + handle the redirect (`redirect:"manual"`, treat opaqueredirect as success).
- **SPA `index.html` is served `Cache-Control: no-cache`** (FEATURES #41, `webapp/main.py:spa_fallback`) so browsers always fetch the current asset hash; deploys also auto-purge Cloudflare when SSM `/may26aws/qong-shared/cloudflare-{purge-token,zone-id}` are set. When verifying a *fresh* deploy in a browser, cache-bust the URL (`?cb=...`) — CF/browser can still serve a stale SPA shell.
- **Datetime convention: UTC on the wire, `Z`-suffixed.** Backend → use `utc_iso(dt)` from `webapp/datetime_utils.py`, never bare `dt.isoformat()` (FEATURES #27 — naive isoformat creates a 5:30h display bug on IST browsers because `new Date(iso)` parses it as local). Frontend → use `formatDateTime/formatDate/formatRelative` + `useUserTimezone()` from `webapp/frontend/src/util/datetime.ts`, never bare `toLocaleString()`. Display TZ comes from `User.timezone` (settable in Account page) with browser `Intl.DateTimeFormat` fallback.
- **Do not re-add `TZ=` env on `web` / `cpu-worker` containers.** They run in UTC by design. `TZ=Asia/Kolkata` only changes `datetime.now()` output, not `datetime.utcnow()`, silently mixing IST and UTC writes into the same DB columns.
- **No Alembic.** Schema changes live in `webapp/database.py:run_migrations()`, called once on startup. **ADD COLUMN:** append a tuple to the `new_columns` list (race-safe via the existence probe). **ALTER TYPE / other DDL:** follow the `timestamptz_columns` pattern — Postgres-only, with column-state probe + visible logging on failure (don't silently swallow ALTERs).
- **Frontend type-check: use `npx tsc --noEmit` from `webapp/frontend/`, not `npm run lint`.** The packaged `lint` script runs `tsc -b` which fails on `tsconfig.node.json` having `noEmit: true` (TS6310). Bare `tsc --noEmit` gives same coverage with a clean exit. Use `npx vitest run` for the SPA test suite (21 tests as of FEATURES #27).
- **LS Auto-tile webhook** (FEATURES #30): when a user uploads a PDF via LS's Import UI, LS fires TASKS_CREATED → `POST /api/v1/webhooks/label-studio/tasks-created` → enqueues `webapp.auto_tile.auto_tile_ls_task_rq` on the cpu-worker → downloads PDF, runs `pdf_to_tiles.py`, multipart-uploads 9 PNGs via `/api/projects/<id>/import`, deletes original PDF task. Auth: `LS_WEBHOOK_SECRET` env (SSM `/may26aws/qong-{dev,qa}/ls-webhook-secret`), sent by LS as `X-LS-Webhook-Secret` header, verified with `hmac.compare_digest`. **LS 1.23 Community has no org-level webhooks** — register per-project (33 projects on dev currently registered).
- **Label Studio 1.23 auth: JWT only, refresh-flow required.** The legacy 40-char hex `Token <key>` format returns 401. `LS_API_KEY` env must be a JWT refresh token (3 dot-separated base64 segments starting with `eyJ`) — mint via LS UI → Account → Personal Access Token → Create New Token. `webapp/label_studio_client.py:_headers()` detects JWT shape and auto-refreshes via POST `/api/token/refresh/` (cached until 60s before `exp`). Don't paste the legacy format into SSM; it'll silently break the webapp → LS API path.
- **v1-9.onnx Docker build recipe** (FEATURES #28, fixed 2026-06-05): the RUN step has 3 non-obvious requirements — (1) `curl` must be in apt-install (not in `python:3.11-slim` base); (2) use the GitHub **API** endpoint `https://api.github.com/repos/{R}/releases/assets/{id}` with `Authorization: Bearer <pat>` + `Accept: application/octet-stream` — the public `releases/download/<tag>/<name>` URL redirects to S3 and S3 rejects the forwarded auth header, yielding a sha-mismatched error page; (3) `json.loads(..., strict=False)` for the GitHub API response (release notes contain unescaped control chars that break strict JSON). PAT comes from `.github_pat` file (gitignored, empty placeholder for local; pointed at `/tmp/qong-github-pat.$$` by `deploy-dev.yml` via SSM `/may26aws/qong-shared/github-pat-model-release`).
- **Local LS webhooks must use `http://host.docker.internal:8000`** to reach the webapp container. Django's URLValidator (LS uses it for webhook URL field) rejects single-word hostnames like `http://web:8000` ("Enter a valid URL"). On Docker Desktop, `host.docker.internal` resolves to the host where the webapp's `127.0.0.1:8000` is mapped. On dev/qa: use the public `https://dev.qongsystems.com/...` — same reachability, fewer moving parts.
- **Ubuntu 24.04 dropped `awscli` from apt.** Install via the AWS CLI v2 zip: `curl -sS https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/a.zip && unzip -q /tmp/a.zip -d /tmp/ && sudo /tmp/aws/install`.
- **EBS `/dev/sdf` shows up as `/dev/nvme1n1` on Nitro instances.** Don't parse `lsblk` columns (empty MOUNTPOINT trips up awk); hardcode the device path and verify with `blockdev --getsize64`.
- **AWS Security Group descriptions reject non-ASCII** (em-dash, smart quotes). ASCII only or the API returns `InvalidParameterValue`.
- **`may26-ec2-ssm-role` has SSM + KMS perms but NOT S3 by default.** New buckets need a bucket policy granting `s3:GetObject` + `s3:ListBucket` to `arn:aws:iam::449901518037:role/may26-ec2-ssm-role`. Identity policy is shared with other workloads; prefer bucket policy.
- **`pg_dumpall` includes `ALTER ROLE … WITH PASSWORD`** that overwrites the target's role password to the source value. After restoring into a fresh env with different SSM-generated creds, run `ALTER ROLE <user> WITH PASSWORD '<.env value>'` to re-sync, or webapp can't auth.
- **`qongsystems.com` Cloudflare zone is "Full (Strict)" SSL mode.** Any new origin MUST present a valid TLS cert on 443 or CF returns 521. Copy the CF Origin Cert (`*.qongsystems.com` SAN) + key from QA via SSM; cert lives at `/etc/ssl/qong-{env}/origin.{crt,key}` on each host.
- **`call<T>` in `webapp/frontend/src/studio/api.ts` throws `HttpError` (not plain `Error`) for any non-2xx** since FEATURES #33. So `if (e instanceof HttpError && e.status === 404)` branches work for GETs too — don't add new GET callers that catch the old plain `Error("HTTP NNN")` shape. `HttpError extends Error` so `err.message` consumers stay compatible.
- **Polling a deploy: check Content-Type, not just HTTP status.** The SPA catch-all at `/` returns 200 even when the new API route isn't yet registered — the `text/html` response wins over a JSON 404. Use `application/json` (or another distinguishing signal) when waiting for a freshly-pushed route to land. Cost ~75s of confusion once (2026-06-10).
- **Bbox click reliability on PidCanvas at default zoom:** detection rects are ~10×6 px on screen at 100% zoom, even when `pointer-events: auto` + onClick are wired correctly. Playwright itself fails to land the click reliably — had to dispatch `MouseEvent` via DOM during E2E verification. UX implication: consider an invisible padded hit-rect overlay or auto-zoom into the active tile if user friction surfaces.
- **Duplicate-route shadow:** if you're editing a route in `webapp/main.py` and changes don't take effect, **grep `webapp/routers/*.py` for the same path first.** Router-includes register before `@app.get()` decorators in main, so a duplicate router-side route wins and main.py's version is silently shadowed. Cost ≥3 commits to find this once (FEATURES #24 tile-CORS bug — patches landed on the wrong handler). Drop a comment in main.py pointing at the canonical location instead of leaving a parallel definition.
- **`FileResponse(..., headers=…)` silently drops custom headers for `image/*` media types.** Starlette quirk — `set_stat_headers` runs after `init_headers` and our custom headers don't land on the wire. Set headers post-construction via `resp.headers[k] = v` (which goes through `MutableHeaders` and updates `raw_headers` properly). `JSONResponse(..., headers=…)` is unaffected.
- **`Vary: Origin` on CORS responses or CF caches the wrong thing.** Without it, the first non-CORS request locks a CORS-less response in CF cache for the whole TTL; subsequent LS requests inherit it. Always pair `Access-Control-Allow-Origin` with `Vary: Origin` on cacheable responses.
- **CF over-rides origin `Cache-Control`** at the zone level (Browser Cache TTL — default 4 hours on Free plan). Set "Respect Existing Headers" if origin needs shorter TTL. To recover from a wrong-cached response: dashboard → Caching → Configuration → Purge By URL (paste each URL on Free plan; wildcard on Enterprise).
- **`LABEL_STUDIO_CSRF_TRUSTED_ORIGINS`** (LS-prefixed env var) takes precedence over Django's standard `CSRF_TRUSTED_ORIGINS`. When LS sits behind a new hostname, override the LS-prefixed one or POST forms return `403 CSRF verification failed`. Base compose ships an old `https://dev.qongsystems.com` value.
- **`git pull` aborts on the EC2** when the repo has uncommitted local changes (e.g. files that bootstrap wrote into the working tree before being version-controlled — `docker-compose.override.dev.yml` was the offender). Recovery: `git fetch origin <branch> && git reset --hard origin/<branch>` from `sudo -u ubuntu`. Risk: discards any genuinely-local changes — verify with `git status` first.
- **SSM RunCommand parameter strings reject inline `$()`** — single-letter shell substitutions fail with "Syntax error: \"(\" unexpected". Wrap any non-trivial bash in a base64-encoded heredoc: write script to `/tmp/x.sh` locally, `B64=$(base64 -i /tmp/x.sh | tr -d '\n')`, send as `commands=["echo $B64 | base64 -d | bash"]`. The base64-heredoc pattern is throughout this repo's SSM scripts.

## Repo

- **Repo**: `Qong-Systems/qong_product` (migrated from `Winn-Projects/qong_poc` in Apr 2026)
- SSH alias for Qong-Systems GitHub (local): `qongsystems`
- SSH alias for Qong-Systems GitHub (GCP VM deploy key): `qong-product` (key: `~/.ssh/id_ed25519_qong_product` on VM)
- SSH alias for Winn-Projects GitHub (legacy, local only): `winn-projects`

## GitHub — Org Separation

- **`gh` CLI is authenticated as `tarunhere`** — admin of `Winn-Projects` only; cannot create repos in `Qong-Systems`
- **`git push` to Qong-Systems** works via SSH alias `qongsystems` (key: `~/.ssh/id_qongsystems`)
- **To create a new Qong-Systems repo**: ask user to create it manually on GitHub, then push: `git remote add origin git@qongsystems:Qong-Systems/<repo>.git && git push -u origin main`
- **NEVER create a Qong-Systems repo under Winn-Projects** — completely different org/domain
