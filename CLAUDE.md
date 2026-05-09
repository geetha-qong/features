# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV.
Target: **≥90% recall** on valve identification.

**Current status**: Production webapp live at https://dev.qongsystems.com
**Next phase**: Replace API with own offline model (see `OWN_SYSTEM_DESIGN.md`)

## Detail Index (read on demand)

- [`docs/claude/pipeline.md`](docs/claude/pipeline.md) — P&ID format, CSV schema, architecture, key files, corrections, ground truth, instruments, datasheets, non-standard tags, offline detector recall
- [`docs/claude/webapp.md`](docs/claude/webapp.md) — Webapp & SaaS features, DB schema, admin/password reset, modules, testing
- [`docs/claude/deployment.md`](docs/claude/deployment.md) — GCP VM, docker services, server security, multi-cloud migration
- [`docs/claude/training_and_gpu.md`](docs/claude/training_and_gpu.md) — Annotation, training lessons, offline detector, Label Studio sync, GPU worker (Tailscale/Windows/CUDA/EasyOCR)

## Branches

- `dev` — active development; auto-deploys to `dev.qongsystems.com` on every push via GitHub Actions
- `main` — reserved for future production at `app.qongsystems.com` (do not push until prod infra ready)
- `feature/multi-cloud-saas` — superseded by `dev` (all phases A1-A3, B1-B5 merged in)

## Docker-First Rule

**NEVER install any service or tool directly on the local Mac.** All services (nginx, databases, annotation tools, etc.) must be added as Docker containers in `docker-compose.yml`. This ensures the compose file can be pushed to production as-is.

## Quick Start (local dev)

```bash
docker compose up -d                                           # start all services
docker compose logs -f web                                     # tail webapp logs
docker compose exec web python3 -m pytest tests/unit/ -v      # run unit tests
```

- Webapp: http://localhost:8000
- Label Studio (direct): http://localhost:9001
- Label Studio (via nginx): http://localhost:9000/ls/

## CRITICAL: Two-Mode Architecture — Do NOT Mix

**Production (end users)** → API-based pipeline only (`extractor.py`):
- `pipeline.py` MUST import from `extractor`, NOT `detector`
- Both valve list CSV and instrumentation index CSV are generated via OpenRouter Vision API
- This is what customers see — 93% recall, battle-tested

**Internal/training (team only)** → Offline model (`detector.py`):
- Used for annotation review, YOLO training, accuracy benchmarking
- Run `detector.py` manually or in a separate script — never wire it into the production pipeline
- Goal: get offline recall to ≥93% before considering a switch

**Rule**: `pipeline.py` line 15 must always read `from extractor import ...` — never `from detector import ...`
If someone changes this by mistake, revert it immediately. The offline detector is NOT production-ready yet (73% recall vs 93% API).

## Environment

- Python 3.12 server (Ubuntu 24.04), Python 3.9 local dev
- Use `Optional[X]` not `X | None`, use `python3` not `python`
- OpenRouter API: `OPENROUTER_API_KEY` env var required (not Anthropic directly)
- Default model: `google/gemini-2.0-flash-001` (fast); override via `OPENROUTER_MODEL`
- Temp files → `tmp/` per job in `job_outputs/{job_id}/tmp/` (never commit). Also never commit `webapp.db`, `uploads/`, `job_outputs/`.

## Repo

- **Repo**: `Qong-Systems/qong_product` (migrated from `Winn-Projects/qong_poc` in Apr 2026)
- SSH alias for Qong-Systems GitHub (local): `qongsystems`
- SSH alias for Qong-Systems GitHub (GCP VM deploy key): `qong-product` (key: `~/.ssh/id_ed25519_qong_product` on VM)
- SSH alias for Winn-Projects GitHub (legacy, local only): `winn-projects`

## GitHub — Org Separation

- **`gh` CLI is authenticated as `tarunhere`** — admin of `Winn-Projects` only; cannot create repos in `Qong-Systems`
- **`git push` to Qong-Systems** works via SSH alias `qongsystems` (key: `~/.ssh/id_qongsystems`)
- **To create a new Qong-Systems repo**: ask user to create it manually on GitHub, then push: `git remote add origin git@qongsystems:Qong-Systems/<repo>.git && git push -u origin main`
- **NEVER create a Qong-Systems repo under Winn-Projects** — completely different org/domain
