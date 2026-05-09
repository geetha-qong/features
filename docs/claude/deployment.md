# Deployment & Infrastructure

GCP VM, docker services, security hardening, multi-cloud migration. See `CLAUDE.md` for top-level rules.

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

## Docker Services

### Additional services (in docker-compose.yml)
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

## Server Security (GCP VM — applied 2026-05-06)

- **All internal ports bound to `127.0.0.1`** in docker-compose.yml — postgres (5432), redis (6379), minio (9100/9101), web (8000), label-studio (8080) are NOT reachable from the internet
- **GCP firewall**: only `qong-allow-http-https` (80/443) and `default-allow-ssh` (22) remain; `qong-allow-web` and `default-allow-rdp` were deleted — do NOT recreate them
- **`.env` permissions**: `chmod 600 /app/qong_poc/.env` — must stay 600; re-apply after any manual file copy
- **After port binding changes in docker-compose.yml**: use `--force-recreate` — plain `up -d` won't rebind already-running containers
- **MinIO bucket**: anonymous download removed — use `storage.presigned_url()` for download links; never run `mc anonymous set download` again
- **Redis requires auth (2026-05-07)**: Redis has `--requirepass ${REDIS_PASSWORD}`; URL format: `redis://:${REDIS_PASSWORD}@redis:6379/0` (internal), `redis://:${REDIS_PASSWORD}@100.127.190.88:6379/0` (GPU Tailscale)
- **`docker compose up -d` does NOT restart redis/minio** after docker-compose.yml changes — use `sudo docker compose up -d --force-recreate redis minio` explicitly when changing their config
- **All credentials in .env — no compose defaults**: REDIS_PASSWORD, MINIO_ROOT_USER/PASSWORD, STORAGE_ACCESS_KEY/SECRET_KEY, POSTGRES_PASSWORD — none have fallback values in compose; missing any will fail on startup
- **fail2ban active**: installed on GCP VM; monitors sshd; auto-bans after 5 failed attempts in 10 min. Check status: `sudo fail2ban-client status sshd`
- **GCS buckets hardened**: uniform IAM + public access prevention on `qong-backups`; verify: `gcloud storage buckets describe gs://qong-backups` (use text format, not `--format=json` — JSON misleadingly shows None for some settings)
- **Windows GPU worker Redis update**: to push env changes to Windows, write a `.ps1` to `/tmp/`, `gcloud compute scp` to GCP VM, then `sshpass scp` to Windows, then `sshpass ssh ... powershell`. Inline PowerShell in 3-hop bash→gcloud→sshpass chain fails due to quoting.

## Multi-Cloud Migration (in progress on dev branch)

Architecture upgrade: SQLite + threads → GCP (Postgres + Redis + RQ + GCS).

**Phases complete**: A1 (S3 adapter + MinIO), A2 (Postgres + RQ), A3 (GCP VM live, data migrated), A4 (GPU worker on Windows — deps, model, ONNX session, Redis all verified), A5 (GPU callback endpoint + LS pre-annotations), A6 (/healthz, nightly pg_dump→GCS, restore script), B1–B2 (credits ledger + pre-flight), B3–B4 (admin panel v2 + account pages), B5 (REST API v1)

**Phases pending**:
- B6/B7 — Stripe Checkout (deferred until 5+ paying customers)

**A6 details**:
- `scripts/backup.sh` — pg_dump + `gcloud storage rsync uploads/ job_outputs/` → `gs://qong-backups`; 30-day retention on pg_dumps
- `scripts/restore.sh` — full server rebuild from GCS backup in <10 min
- `.github/workflows/backup.yml` — runs 02:00 IST daily via `schedule:`; manual trigger via `workflow_dispatch` in Actions UI
- **GCS bucket**: `gs://qong-backups` (asia-southeast1); VM service account needs `roles/storage.objectAdmin`
- **Nightly backup**: GitHub Actions SSHs into VM → runs `scripts/backup.sh` using same `GSP_DEV_SSH_KEY` secret

Full architecture plan: `sparkling-exploring-blum.md` in Claude plans folder.
