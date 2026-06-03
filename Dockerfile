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

RUN apt-get update && apt-get install -y gcc libgl1 libglib2.0-0 libxcb1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-webapp.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-webapp.txt -r requirements-dev.txt

COPY . .
# Overwrite whatever the host dist/ might be (often empty / gitignored) with
# the freshly built SPA from the frontend stage.
COPY --from=frontend /frontend/dist /app/webapp/frontend/dist
RUN mkdir -p uploads job_outputs

# ─── YOLO v1-9 ONNX model (FEATURES #28) ──────────────────────────────────────
# Bakes the production object-detection weights into the image so the webapp
# can run in-process inference for canvas bbox surfacing (Job.gpu_detections)
# without depending on the Windows GPU worker callback.
#
# The CSV/deliverable pipeline still uses the OpenRouter Vision API
# (extractor.py) — this model is for bbox overlay only. See
# webapp/inference.py and the "CRITICAL: Two-Mode Architecture" section of
# CLAUDE.md.
#
# Asset: v1-9.onnx, 43 MB, sha256:
#   11e29b47dea7a36b5609f315a7f589c53f0d0f8e24f0b95e74ecb9447f526178
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
    MODEL_URL="https://github.com/Qong-Systems/qong_product/releases/download/model-v1-9/v1-9.onnx" && \
    MODEL_SHA="11e29b47dea7a36b5609f315a7f589c53f0d0f8e24f0b95e74ecb9447f526178" && \
    DEST=/app/models/v1-9.onnx && \
    echo "[model] Attempting public download..." && \
    HTTP=$(curl -sL -w "%{http_code}" -o "$DEST" "$MODEL_URL") && \
    if [ "$HTTP" != "200" ]; then \
        echo "[model] Public download returned HTTP $HTTP — retrying with PAT" && \
        if [ ! -s /run/secrets/github_pat ]; then \
            echo "[model] No github_pat secret mounted; cannot retry. Pass --secret id=github_pat,src=<file>." && exit 1; \
        fi && \
        TOKEN=$(cat /run/secrets/github_pat) && \
        curl -sL -H "Authorization: token $TOKEN" \
            -H "Accept: application/octet-stream" \
            -o "$DEST" "$MODEL_URL" || exit 1; \
    fi && \
    ACTUAL_SHA=$(sha256sum "$DEST" | awk '{print $1}') && \
    if [ "$ACTUAL_SHA" != "$MODEL_SHA" ]; then \
        echo "[model] sha256 mismatch: expected $MODEL_SHA got $ACTUAL_SHA" && \
        rm -f "$DEST" && exit 1; \
    fi && \
    echo "[model] $DEST verified ($(stat -c%s "$DEST") bytes)"

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
