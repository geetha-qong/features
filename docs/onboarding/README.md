# P&ID Digitization

On-premises software that turns oil-and-gas P&ID drawings into a queryable internal directed graph and a set of proprietary customer deliverables (Valve List, Instrument Index, Datasheets, BOM, Equipment List, Loop Trace report). The graph stays inside the product — no DEXPI / industry-standard export (see FEATURES.md #04). Runs without internet at the client site. Reviewer-assisted.

## For humans joining this codebase

Read in this order:

1. **`PROJECT_VISION.md`** — what we are building and what we are NOT building. 5 minutes.
2. **`ARCHITECTURE.md`** — how the system is wired. 15 minutes.
3. **`REVIEW_UI_SPEC.md`** — the reviewer interface, if you're working on the frontend. 10 minutes.
4. **`ACTIVE_LEARNING_SPEC.md`** — how reviewer corrections improve the models. 10 minutes.
5. **`docs/REFERENCES.md`** — the papers and reference implementations that informed our approach.

You will be productive after that morning of reading. Do not skip it.

## For Claude Code

Read the live **`/CLAUDE.md`** at the repo root first — it tells you the actual session read order (`SESSION_STATE.md` → `FEATURES.md` → `CLAUDE.md`), the update obligations (FEATURES.md is append-only, SESSION_STATE.md is overwritten at end of session), and the rules of this project. The files in this folder are the *vision/onboarding pack* (QS-60), not the live discipline files.

## Quick orientation

| Question | Answer |
|---|---|
| What problem? | Oil-and-gas plants have thousands of P&IDs locked as PDFs. Manually digitizing them takes 3–6 months per facility. We do it in days with a reviewer in the loop. |
| What's the deliverable? | A queryable internal directed graph (Neo4j) plus customer-facing files: Valve List CSV, Instrument Index CSV, Datasheets PDF, BOM XLSX, Equipment List XLSX, Loop Trace report. The raw graph never leaves the product. |
| What's the differentiator? | The review UI and the active-learning loop. Detection accuracy alone is a commodity. |
| Where does this run? | On a single on-premises GPU box at the client site. No internet. |
| Who is the user? | A reviewer (drafter or junior process engineer) who spends 8 hours a day in the review UI. |
| What's the v1 target? | 15 minutes of reviewer time per sheet to reach 99% topological correctness. |

## Local development

Not yet wired up. After Phase 0 ships, the entry point will be:

```bash
docker compose up
```

and the UI will be at `http://localhost:5173`. Until then, follow the symbol-detection POC's local README.

## What lives where

```
pipeline/       Python detection + graph build
api/            FastAPI control plane
web/            React review UI (PixiJS canvas)
training/       Model training scripts and eval harness
schemas/        JSON Schema for internal canonical graph
deploy/         Docker Compose, installer, rollback
docs/           Reference docs, datasets, decision records
```

## How to ask questions

In order of preference: read the spec → search past chats with Claude → ask the team. Do not start coding around a question you haven't answered.

## Status

Pre-v1. Symbol-detection POC exists in a separate repository. This repo is the production system being built on top of it.
