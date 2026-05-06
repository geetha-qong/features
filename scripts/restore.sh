#!/usr/bin/env bash
# Disaster recovery: rebuild server from scratch using GCS backup.
# Run on a FRESH GCP VM (Debian 12) as root or sudo-capable user.
# Target: <10 minutes end-to-end.
#
# Usage:
#   bash restore.sh                         # restore latest pg_dump
#   bash restore.sh 2026-05-05              # restore specific date
set -euo pipefail

RESTORE_DATE="${1:-latest}"
BUCKET="gs://qong-backups"
APP_DIR="/app/qong_poc"
REPO="qong-product:Qong-Systems/qong_product.git"

echo "=== Qong Disaster Recovery ==="
echo "    Date: $RESTORE_DATE"
echo "    Started: $(date)"
echo ""

# ── 1. Install Docker + gcloud (if not present) ───────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[1/7] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$USER" || true
else
    echo "[1/7] Docker already installed"
fi

# ── 2. Clone repo ─────────────────────────────────────────────────────────────
echo "[2/7] Cloning repo..."
mkdir -p /app
if [ ! -d "$APP_DIR/.git" ]; then
    git clone "git@$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
git checkout dev
git pull origin dev

# ── 3. Copy .env (must be restored manually or from secure store) ─────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[3/7] WARNING: .env not found — copy from secure store before continuing"
    echo "      Required vars: OPENROUTER_API_KEY, SECRET_KEY, DATABASE_URL,"
    echo "      LS_API_KEY, WEBAPP_BASE_URL, LS_EXTERNAL_URL"
    read -rp "      Press Enter once .env is in place..."
else
    echo "[3/7] .env found"
fi

# ── 4. Start containers ───────────────────────────────────────────────────────
echo "[4/7] Starting containers..."
sudo docker compose up -d postgres redis
sleep 5   # wait for postgres to be ready

# ── 5. Restore pg_dump ────────────────────────────────────────────────────────
echo "[5/7] Restoring Postgres..."
if [ "$RESTORE_DATE" = "latest" ]; then
    DUMP_FILE=$(gsutil ls "$BUCKET/postgres/" | sort | tail -1)
else
    DUMP_FILE="$BUCKET/postgres/qong-postgres-${RESTORE_DATE}.sql.gz"
fi
echo "      Using: $DUMP_FILE"
gsutil cp "$DUMP_FILE" /tmp/restore.sql.gz
gunzip -c /tmp/restore.sql.gz | sudo docker compose exec -T postgres psql -U qong qong
rm -f /tmp/restore.sql.gz
echo "      Postgres restored"

# ── 6. Restore files from GCS ─────────────────────────────────────────────────
echo "[6/7] Restoring uploads and job outputs..."
mkdir -p "$APP_DIR/uploads" "$APP_DIR/job_outputs"
gsutil -m rsync -r "$BUCKET/uploads/" "$APP_DIR/uploads/"
gsutil -m rsync -r "$BUCKET/job_outputs/" "$APP_DIR/job_outputs/"

# ── 7. Start all services ─────────────────────────────────────────────────────
echo "[7/7] Starting all services..."
sudo docker compose up -d
sudo docker compose restart nginx

echo ""
echo "=== Restore complete: $(date) ==="
echo "    Verify: curl https://dev.qongsystems.com/healthz"
