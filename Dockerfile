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

# ─── YOLO ONNX model — MOUNTED AT RUNTIME, not baked (FEATURES #133) ─────────
# The model is NOT downloaded during the image build anymore. It is bind-mounted
# into the container at /app/models from the host (docker-compose `volumes:`),
# sourced from MODEL_DIR (the persistent data volume on dev/qa). Rationale:
#   - The old bake step sat AFTER `COPY . .`, so ANY code change invalidated its
#     layer and re-downloaded the 44 MB asset on EVERY deploy — and an expired
#     model-release PAT silently broke ALL deploys (even code-only ones).
#   - The model only changes on a new release, so fetching it on every build is
#     wasteful and fragile. Now the PAT is needed ONLY at model-release time, via
#     `scripts/fetch_model.sh` (run once per release to populate MODEL_DIR).
# The webapp loads /app/models/v1-11.onnx at runtime (webapp/inference.py); if
# the mount is empty (e.g. local dev without a model) it raises InferenceError
# only when inference is actually requested — the image builds + serves fine.
RUN mkdir -p /app/models

EXPOSE 8000
# Shell form so ${UVICORN_WORKERS} (set via compose env) substitutes at runtime;
# `exec` replaces the shell with uvicorn so SIGTERM from `docker stop` reaches it
# directly (clean shutdown). Defaults to 1 worker for local/single-core; dev/qa
# set UVICORN_WORKERS=3 in their compose override (FEATURES #121).
CMD exec uvicorn webapp.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}
