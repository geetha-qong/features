# Digital Twin — Experimental Track

A fast-iteration sandbox for building the **graph-extraction** layer of Qong's digital-twin platform. Lives in the same repo as `qong_poc` but on a separate branch family (`dt/*`) so the team's daily work on `dev` stays uninterrupted.

## Why this exists

- **Team track (`dev` branch, `webapp/`):** interns ramping up on the production codebase at their own pace.
- **Experimental track (`dt/*` branches, `experiments/digital_twin/`):** the lead builds the next-generation graph-extraction tool with Claude Code assistance, faster than the team can keep up with. When ready, the experimental code merges back into `dev` and the team takes over maintenance — by which point their basics are solid enough to operate it.

Same repo, same data, separate working surface.

## What's in here

```
experiments/digital_twin/
├── README.md         ← you are here
├── pyproject.toml    ← Python deps (uv / pip both work)
├── notebooks/        ← exploratory Jupyter notebooks; pixel-tracing experiments live here
├── backend/          ← FastAPI service once the algorithm stabilises (port 9100)
├── data/             ← gitignored; symlinks/refs into ../../job_outputs/ for fixtures
└── docs/             ← design notes specific to this track
```

## Shared assets (read-only — do not modify from here)

The experimental track *reads* these from the parent repo. Never write back into them:

- `../../models/v1-9.onnx` — YOLO symbol detector (FEATURES #28)
- `../../job_outputs/{org_id}/{job_id}/` — completed jobs with canonical.json + tiles
- `../../pdf_to_tiles.py` — tile renderer (3× zoom, 3×3 grid, 20% overlap)
- `../../webapp/inference.py` — in-process YOLO inference helper

If we need to evolve any of those, the change goes into the team's track on `dev` (with a FEATURES.md entry), not silently inside `experiments/`.

## Branch policy

- `dt/main` — long-running base for this track. Never merged into `dev` until the tool is ready for handoff.
- `dt/<topic>` — short-lived feature branches off `dt/main`; merge back via PR or fast-forward.
- `.github/workflows/deploy-dev.yml` only fires on `branches: [dev]`, so `dt/*` pushes deploy nothing. Zero noise on dev.qongsystems.com.

## Memory and context

Memory continues to live in the repo root:
- `CLAUDE.md` — see the `## Experimental track (digital_twin)` section
- `FEATURES.md` — entries from this track are tagged `[DT]` so they're easy to filter
- `SESSION_STATE.md` — notes which track the previous session was working on

## Running locally

The first phase is notebook-based exploration (no service). To get started:

```bash
cd experiments/digital_twin
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
jupyter lab notebooks/
```

A `docker-compose.yml` will be added once we have a backend service worth running.

## Design docs

- `docs/superpowers/specs/2026-06-05-graph-extraction-design.md` (repo root) — the v0 design that justifies this track.
