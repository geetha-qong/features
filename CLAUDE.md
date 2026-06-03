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

**Current status:** Production webapp live at https://dev.qongsystems.com. v1-9 YOLO ONNX deployed today (2026-05-26).
**Next phase:** Digital Twin MVP — Sprint 1 starts today on branch `feature/digital-twin` (not yet created; SCRUM-54).

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

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{org_id}/{job_id}/tmp/` (jobs ≥ 40) or `job_outputs/{job_id}/tmp/` (jobs ≤ 39); never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.
- **Generated secrets must not contain `$`** (use `openssl rand -hex N` — alphanumeric only). Docker Compose treats `$wrv` inside a `.env` value as `${wrv}` and silently substitutes empty, truncating the secret. If a `$`-containing SSM value gets rendered into `.env.*`, escape `$ → $$` (Compose decodes `$$` as literal `$`). Real bug we hit on QA — FEATURES #19.
- **Root-level `*.png` is gitignored** (`/*.png` line in `.gitignore`). Save Playwright / QA screenshots to `themes/screenshots/` (also gitignored), a job-output path, or `tmp/` — never the repo root. Nested PNGs under `design/`, `docs/`, `webapp/` track normally.
- **Ubuntu 24.04 dropped `awscli` from apt.** Install via the AWS CLI v2 zip: `curl -sS https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/a.zip && unzip -q /tmp/a.zip -d /tmp/ && sudo /tmp/aws/install`.
- **EBS `/dev/sdf` shows up as `/dev/nvme1n1` on Nitro instances.** Don't parse `lsblk` columns (empty MOUNTPOINT trips up awk); hardcode the device path and verify with `blockdev --getsize64`.
- **AWS Security Group descriptions reject non-ASCII** (em-dash, smart quotes). ASCII only or the API returns `InvalidParameterValue`.
- **`may26-ec2-ssm-role` has SSM + KMS perms but NOT S3 by default.** New buckets need a bucket policy granting `s3:GetObject` + `s3:ListBucket` to `arn:aws:iam::449901518037:role/may26-ec2-ssm-role`. Identity policy is shared with other workloads; prefer bucket policy.
- **`pg_dumpall` includes `ALTER ROLE … WITH PASSWORD`** that overwrites the target's role password to the source value. After restoring into a fresh env with different SSM-generated creds, run `ALTER ROLE <user> WITH PASSWORD '<.env value>'` to re-sync, or webapp can't auth.
- **`qongsystems.com` Cloudflare zone is "Full (Strict)" SSL mode.** Any new origin MUST present a valid TLS cert on 443 or CF returns 521. Copy the CF Origin Cert (`*.qongsystems.com` SAN) + key from QA via SSM; cert lives at `/etc/ssl/qong-{env}/origin.{crt,key}` on each host.
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
