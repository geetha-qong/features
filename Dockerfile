# ─── Frontend build stage ────────────────────────────────────────────────────
# Builds the Vite + React SPA. Output (dist/) is copied into the runtime stage.
# Doing this in the image (not on host) means: deploys are self-contained, no
# host-side `npm run build` step required, no risk of bind-mount shadowing an
# empty dist (the bug that took down the QA bring-up — fixed by also dropping
# the ./webapp bind-mount in docker-compose.override.qa.yml).
FROM node:20-alpine AS frontend
WORKDIR /frontend
# BUILD_ID is read at build time by Vite (see webapp/frontend/vite.config.ts
# `define` block) and baked into window.__QONG_BUILD__. CI passes the short
# git SHA; defaults to "dev" if not set (local builds).
ARG BUILD_ID=dev
ENV BUILD_ID=$BUILD_ID
# Cache deps independently of source so source edits don't bust the npm layer.
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build


# ─── Python runtime stage ────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y gcc libgl1 libglib2.0-0 libxcb1 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-webapp.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-webapp.txt -r requirements-dev.txt

COPY . .
# Overwrite whatever the host dist/ might be (often empty / gitignored) with
# the freshly built SPA from the frontend stage.
COPY --from=frontend /frontend/dist /app/webapp/frontend/dist
RUN mkdir -p uploads job_outputs

# ─── YOLO v1-11 ONNX model (FEATURES #41, supersedes v1-10 from FEATURES #30) ─
# Bakes the production object-detection weights into the image so the webapp
# can run in-process inference for canvas bbox surfacing (Job.gpu_detections)
# without depending on the Windows GPU worker callback.
#
# The CSV/deliverable pipeline still uses the OpenRouter Vision API
# (extractor.py) — this model is for bbox overlay only. See
# webapp/inference.py and the "CRITICAL: Two-Mode Architecture" section of
# CLAUDE.md.
#
# v1-11 vs v1-10 (same 23-class layout — drop-in swap, no inference code change):
#   - Trained from yolov8s on ~32,212 LS-sourced annotations (812 train + 80 val),
#     ~+32% more annotation than v1-10, concentrated on the weak arrow/connector
#     and valve_ck/gt/gl classes flagged in FEATURES #30.
#   - mAP50 = 0.805 vs v1-10 = 0.745 on the SAME (leak-free) v1-11 val split
#     (+0.060); recall 0.682 -> 0.759; precision flat. Biggest per-class gains:
#     direction arrows (e.g. arrow_up 0.426 -> 0.673) and valve_ck 0.57 -> 0.76.
#   - (v1-10's headline 0.834 was on its own easier 62-image val set — not
#     comparable; the 0.745 above is v1-10 re-scored on the v1-11 val set.)
#
# Asset: v1-11.onnx, 44.7 MB, sha256:
#   34022c917ae3b5487b6a81d9cc9f12064efdd101ee96540a1c7dd0fec097f4e5
#
# Path 1 (preferred — no secret) — Release asset is public:
#   docker build .
# Path 2 (fallback) — if the asset 404s/403s, pass a GitHub PAT as a build
# secret. The PAT only needs `repo:read` scope on Qong-Systems/qong_product:
#   echo -n "$GITHUB_PAT" > /tmp/pat
#   DOCKER_BUILDKIT=1 docker build --secret id=github_pat,src=/tmp/pat .
# The RUN below first tries plain curl; on non-200 it retries with the
# Authorization header read from the secret file (no-op if not mounted).
RUN --mount=type=secret,id=github_pat,required=false \
    mkdir -p /app/models && \
    REPO="Qong-Systems/qong_product" && \
    TAG="model-v1-11" && \
    ASSET_NAME="v1-11.onnx" && \
    MODEL_SHA="34022c917ae3b5487b6a81d9cc9f12064efdd101ee96540a1c7dd0fec097f4e5" && \
    DEST=/app/models/v1-11.onnx && \
    AUTH_HEADER="" && \
    if [ -s /run/secrets/github_pat ]; then \
        TOKEN=$(cat /run/secrets/github_pat) && \
        AUTH_HEADER="Authorization: Bearer $TOKEN"; \
    fi && \
    echo "[model] Looking up asset id via GitHub API..." && \
    ASSET_JSON=$(curl -sL -H "Accept: application/vnd.github+json" \
        -H "$AUTH_HEADER" \
        "https://api.github.com/repos/$REPO/releases/tags/$TAG") && \
    ASSET_ID=$(echo "$ASSET_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read(), strict=False); a=[x for x in d.get('assets',[]) if x['name']=='$ASSET_NAME']; print(a[0]['id']) if a else sys.exit('no asset (API said: '+str(d.get('message','?'))+')')") && \
    echo "[model] asset_id=$ASSET_ID — downloading via API endpoint..." && \
    HTTP=$(curl -sL -w "%{http_code}" \
        -H "Accept: application/octet-stream" \
        -H "$AUTH_HEADER" \
        -o "$DEST" \
        "https://api.github.com/repos/$REPO/releases/assets/$ASSET_ID") && \
    if [ "$HTTP" != "200" ]; then \
        echo "[model] Download failed with HTTP $HTTP. If the release is private, mount a Buildkit secret: DOCKER_BUILDKIT=1 docker build --secret id=github_pat,src=<file> ..." && \
        rm -f "$DEST" && exit 1; \
    fi && \
    ACTUAL_SHA=$(sha256sum "$DEST" | awk '{print $1}') && \
    if [ "$ACTUAL_SHA" != "$MODEL_SHA" ]; then \
        echo "[model] sha256 mismatch: expected $MODEL_SHA got $ACTUAL_SHA" && \
        head -c 500 "$DEST" && \
        rm -f "$DEST" && exit 1; \
    fi && \
    echo "[model] $DEST verified ($(stat -c%s "$DEST") bytes)"

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
