# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read order at the start of every session (do NOT skip)

1. **`SESSION_STATE.md`** — what the previous session did, where it stopped, next concrete step, what's blocked, gotchas the previous session learned. Short on purpose; the journal lives in FEATURES.md.
2. **`FEATURES.md`** — append-only history of every meaningful decision, model swap, threshold change, architecture choice. Read the most recent 5–10 entries.
3. **This file (`CLAUDE.md`)** — repo conventions, branch policy, environment, security rules.
4. **The user's current message** — what they want done now.

## Must do during every session

- When implementing a feature, behavior change, model swap, or architecture decision: **append one entry to `FEATURES.md`**. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`. Recording the *reasoning* matters more than the choice. Format inside FEATURES.md.
- For long discussions, link out to `docs/decisions/NN-title.md` from the FEATURES.md entry.

## Must do at the end of every session

- **Overwrite `SESSION_STATE.md` in full** with: what happened this session, where you stopped (file paths, commit hashes), next concrete step, what's blocked, what the next session should know (gotchas, lessons). Don't accumulate — overwrite. The journal accumulates in FEATURES.md, not here.

## Project Goal

Extract a **Valve List** from scanned P&ID drawings (PDFs) and output a structured CSV today.
Evolving into a **human-in-the-loop digital twin platform** (multi-page graph + new deliverables: valve list, instrument index, datasheets, BOM, loop trace, equipment list) over the next 6-9 months. See FEATURES.md #01 and the plan at `/Users/maahedev/.claude/plans/async-soaring-puppy.md` for the full trajectory.

Headline metric long-term: graph isomorphism (`networkx.is_isomorphic`) — measures topological correctness of the extracted graph vs human ground truth. Short-term (existing product): ≥90% recall on valve identification.

**Current status:** Production webapp live at https://dev.qongsystems.com. v1-9 YOLO ONNX deployed today (2026-05-26).
**Next phase:** Digital Twin MVP — Sprint 1 starts today on branch `feature/digital-twin` (not yet created; SCRUM-54).

## Detail Index (read on demand)

- [`docs/claude/pipeline.md`](docs/claude/pipeline.md) — P&ID format, CSV schema, architecture, key files, corrections, ground truth, instruments, datasheets, non-standard tags, offline detector recall
- [`docs/claude/webapp.md`](docs/claude/webapp.md) — Webapp & SaaS features, DB schema, admin/password reset, modules, testing
- [`docs/claude/deployment.md`](docs/claude/deployment.md) — GCP VM, docker services, server security, multi-cloud migration
- [`docs/claude/training_and_gpu.md`](docs/claude/training_and_gpu.md) — Annotation, training lessons, offline detector, Label Studio sync, GPU worker (Tailscale/Windows/CUDA/EasyOCR)
- [`docs/claude/deliverables.md`](docs/claude/deliverables.md) — Deliverables subsystem (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

## Branches

- `dev` — active development; auto-deploys to `dev.qongsystems.com` on every push via GitHub Actions. Existing valve-list product flows continue shipping here throughout the digital twin build-out.
- `feature/digital-twin` — all digital twin MVP work (Sprints 1-5, ~8-10 weeks). Created in SCRUM-54. Merges back to `dev` at MVP cutover (Sprint 5).
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

## VM access (production troubleshooting)

- SSH via IAP (plain port 22 is firewalled): `gcloud compute ssh qong-dev-server --zone=asia-southeast1-c --tunnel-through-iap --command="..."` — works because gcloud is authed as `theqongglobal@gmail.com`. Same `--tunnel-through-iap` flag on `gcloud compute scp`.
- Query production DB from VM: `psql -U postgres` fails (role doesn't exist). Use the ORM via the web container: `sudo docker compose exec -T web python3 -c "from webapp.database import SessionLocal; from webapp.models import Job; s=SessionLocal(); print(s.get(Job, 41).output_csv_path)"`. Avoid f-strings inside `-c` (quoting hell — use `print(label, value)` with `,` separator).
- Job artifact paths: jobs ≥ 40 use org-scoped `/app/job_outputs/{org_id}/{job_id}/`; jobs ≤ 39 use flat `/app/job_outputs/{job_id}/`. Always read the exact path from `Job.output_csv_path` / `output_annotated_pdf_path` in the DB rather than guessing.

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
- Temp files → `tmp/` per job in `job_outputs/{org_id}/{job_id}/tmp/` (jobs ≥ 40) or `job_outputs/{job_id}/tmp/` (jobs ≤ 39); never commit. Also never commit `webapp.db`, `uploads/`, `job_outputs/`.

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
