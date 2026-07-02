#!/usr/bin/env bash
# fetch_model.sh — download the YOLO ONNX model into MODEL_DIR (FEATURES #133).
#
# The model is NO LONGER baked into the Docker image. It is mounted at runtime
# from MODEL_DIR (see docker-compose.yml). Run this ONCE per model release to
# populate that directory; ordinary code deploys never touch the model or the
# GitHub PAT.
#
# Usage:
#   MODEL_DIR=/mnt/qong-data/models ./scripts/fetch_model.sh
#   # PAT resolution order: $GITHUB_PAT env  →  SSM (on the EC2)  →  unauthenticated
#   # (public release). Override the asset with TAG / ASSET_NAME / MODEL_SHA env.
#
# On the dev/qa EC2 the PAT is read from SSM:
#   /may26aws/qong-shared/github-pat-model-release
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-./models}"
TAG="${TAG:-model-v1-11}"
ASSET_NAME="${ASSET_NAME:-v1-11.onnx}"
MODEL_SHA="${MODEL_SHA:-34022c917ae3b5487b6a81d9cc9f12064efdd101ee96540a1c7dd0fec097f4e5}"
REPO="${REPO:-Qong-Systems/qong_product}"
DEST="${MODEL_DIR%/}/${ASSET_NAME}"

mkdir -p "$MODEL_DIR"

# Skip if already present + valid (idempotent — safe to re-run).
if [ -f "$DEST" ] && [ "$(sha256sum "$DEST" | awk '{print $1}')" = "$MODEL_SHA" ]; then
  echo "[model] $DEST already present and verified — nothing to do."
  exit 0
fi

# Resolve a PAT: explicit env first, else SSM (EC2), else none (public release).
TOKEN="${GITHUB_PAT:-}"
if [ -z "$TOKEN" ] && command -v aws >/dev/null 2>&1; then
  TOKEN="$(aws ssm get-parameter --name /may26aws/qong-shared/github-pat-model-release \
            --with-decryption --region ap-south-1 --query Parameter.Value --output text 2>/dev/null || true)"
  [ "$TOKEN" = "None" ] && TOKEN=""
fi
AUTH=(); [ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")

echo "[model] resolving asset id for $REPO release $TAG ($ASSET_NAME)..."
ASSET_JSON="$(curl -sL -H "Accept: application/vnd.github+json" "${AUTH[@]}" \
  "https://api.github.com/repos/$REPO/releases/tags/$TAG")"
ASSET_ID="$(echo "$ASSET_JSON" | python3 -c \
  "import json,sys; d=json.loads(sys.stdin.read(), strict=False); a=[x for x in d.get('assets',[]) if x['name']=='$ASSET_NAME']; print(a[0]['id']) if a else sys.exit('no asset (API said: '+str(d.get('message','?'))+')')")"

echo "[model] downloading asset_id=$ASSET_ID -> $DEST ..."
HTTP="$(curl -sL -w '%{http_code}' -H "Accept: application/octet-stream" "${AUTH[@]}" \
  -o "$DEST.partial" "https://api.github.com/repos/$REPO/releases/assets/$ASSET_ID")"
if [ "$HTTP" != "200" ]; then
  echo "[model] download failed: HTTP $HTTP"; rm -f "$DEST.partial"; exit 1
fi

ACTUAL_SHA="$(sha256sum "$DEST.partial" | awk '{print $1}')"
if [ "$ACTUAL_SHA" != "$MODEL_SHA" ]; then
  echo "[model] sha256 mismatch: expected $MODEL_SHA got $ACTUAL_SHA"; rm -f "$DEST.partial"; exit 1
fi
mv "$DEST.partial" "$DEST"
echo "[model] $DEST verified ($(stat -c%s "$DEST" 2>/dev/null || stat -f%z "$DEST") bytes)."
