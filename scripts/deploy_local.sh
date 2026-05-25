#!/usr/bin/env bash
# Manual deploy of the current branch on this VM.
# Same sequence as .github/workflows/deploy-dev.yml — keep them in sync.
#
# Usage (on the VM):
#   sudo /app/qong_poc/scripts/deploy_local.sh
#
# Use this when you need to deploy without going through git push + GH Actions
# (e.g. testing a hot-fix, recovering from a half-deploy, or replacing best.onnx
# alongside a code change). The nginx restart at the end refreshes its cached
# upstream IPs for web/cpu-worker if they were recreated.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Current commit"
git log -1 --format="%h %s"

echo "==> Build web + cpu-worker"
docker compose build web cpu-worker

echo "==> Recreate web + cpu-worker"
docker compose up -d web cpu-worker

echo "==> Recreate nginx (force-recreate, not just restart)"
# `restart` reuses the existing container, which means a `git reset --hard`
# that wrote nginx.conf at a new inode leaves the container reading the OLD
# file via its stale bind mount. `up -d --force-recreate` rebinds the mount.
docker compose up -d --force-recreate nginx

echo "==> Final status"
docker compose ps --format "table {{.Name}}\t{{.Status}}" | head -10

echo "==> Smoke test: tile endpoint"
curl -sI https://dev.qongsystems.com/healthz 2>&1 | head -1 || true
