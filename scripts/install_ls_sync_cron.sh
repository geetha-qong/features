#!/usr/bin/env bash
# Install a cron job that runs ls_sync_labels.py hourly so any newly created
# LS project (or any drift from scripts/ls_label_config.xml) is auto-corrected.
#
# Idempotent: re-running replaces the entry rather than duplicating it.
#
# Usage (on dev VM):
#   bash /app/qong_poc/scripts/install_ls_sync_cron.sh

set -euo pipefail

REPO=/app/qong_poc
SCRIPT="$REPO/scripts/ls_sync_labels.py"
LOG="$HOME/ls_sync.log"
MARKER="# qong-ls-sync (managed by install_ls_sync_cron.sh)"

touch "$LOG"

# Cron entry: every hour at :05, only log when changes happen
NEW_ENTRY="5 * * * * cd $REPO && /usr/bin/python3 $SCRIPT --apply 2>&1 | grep -E 'updated|FAILED|✗' >> $LOG || true  $MARKER"

# Strip any previous managed entry (|| true keeps `set -e` happy when the
# crontab is empty or has no matching lines) then append the new one
{ crontab -l 2>/dev/null | grep -v -F "$MARKER" || true; echo "$NEW_ENTRY"; } | crontab -

echo "Installed cron entry:"
crontab -l | grep -F "$MARKER"
echo
echo "Logs: $LOG"
