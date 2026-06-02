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

EXPOSE 8000
CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
