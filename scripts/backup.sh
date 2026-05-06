#!/usr/bin/env bash
# Nightly backup: pg_dump + file sync → GCS
# Run on GCP VM as: bash /app/qong_poc/scripts/backup.sh
set -euo pipefail

APP_DIR="/app/qong_poc"
BUCKET="gs://qong-backups"
DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)

echo "[$TIMESTAMP] Starting backup..."

# ── 1. Postgres dump ──────────────────────────────────────────────────────────
DUMP_FILE="/tmp/qong-postgres-${DATE}.sql.gz"
echo "  pg_dump → $DUMP_FILE"
sudo docker compose -f "$APP_DIR/docker-compose.yml" exec -T postgres \
    pg_dump -U qong qong | gzip > "$DUMP_FILE"

echo "  uploading to $BUCKET/postgres/"
gcloud storage cp "$DUMP_FILE" "$BUCKET/postgres/qong-postgres-${DATE}.sql.gz"
rm -f "$DUMP_FILE"

# ── 2. Sync uploads (PDFs) ────────────────────────────────────────────────────
echo "  syncing uploads/ → $BUCKET/uploads/"
gcloud storage rsync -r --delete-unmatched-destination-objects "$APP_DIR/uploads/" "$BUCKET/uploads/"

# ── 3. Sync job outputs (CSVs, tiles) ────────────────────────────────────────
echo "  syncing job_outputs/ → $BUCKET/job_outputs/"
gcloud storage rsync -r "$APP_DIR/job_outputs/" "$BUCKET/job_outputs/"

# ── 4. Prune pg_dump files older than 30 days ────────────────────────────────
echo "  pruning backups older than 30 days..."
CUTOFF=$(date -d "30 days ago" +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d)
gcloud storage ls "$BUCKET/postgres/" | while read f; do
    FILE_DATE=$(basename "$f" | grep -oP '\d{4}-\d{2}-\d{2}' || true)
    if [[ -n "$FILE_DATE" && "$FILE_DATE" < "$CUTOFF" ]]; then
        gcloud storage rm "$f"
        echo "    deleted old backup: $f"
    fi
done

echo "  ✓ Backup complete: $(date +%Y-%m-%dT%H:%M:%S)"
