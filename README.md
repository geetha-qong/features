# Qong — P&ID Digital Twin Platform

Extract structured **Valve Lists, Instrument Indexes, Equipment Lists, and Datasheets** from scanned P&ID drawings. Upload a PDF, get auditable CSVs and editable deliverables — with a human-in-the-loop review canvas (Qong Studio).

| Environment | URL | Status |
|---|---|---|
| **Dev** (auto-deploy on push to `dev`) | https://dev.qongsystems.com | live |
| **QA** | https://qa.qongsystems.com | stopped to save cost — restart on demand |
| **Label Studio (dev)** | https://ls-dev.qongsystems.com | live |
| Production (`main` → `app.qongsystems.com`) | not provisioned yet | reserved |

> New on the team? Read this file, then `CLAUDE.md`, then the latest 5–10 entries in `FEATURES.md`, then `SESSION_STATE.md`. That sequence gives you rules → history → current state in ~15 minutes.

---

## What this product does

1. **Upload** a P&ID PDF (one drawing per Job).
2. **Pipeline** tiles the PDF, calls OpenRouter Vision API per tile, parses tags + line numbers, validates, and writes `valve_list.csv`, `instrument_index.csv`, `equipment_list.xlsx`, `datasheet.xlsx`.
3. **Qong Studio** (React + Konva) renders the PDF tile-by-tile with detection overlays and lets reviewers edit entities. Edits land in the `entity_overrides` table and merge into every subsequent export.
4. **Admin tools** manage users, customer-specific deliverable templates, and a feedback queue.

**Current state (June 2026):** React SPA (Marketing, Dashboard, Studio canvas, Admin) live in production on dev. Deliverables subsystem ships four generators + per-customer JSON templates; editable deliverables (`entity_overrides` merge layer) and the cross-job `canonical_entities` index are live. AWS migration complete (ap-south-1), Postgres in all envs, GitHub Actions + SSM auto-deploy on every push to `dev`. Graph-extraction v0 (line detection → graph → DB) is in production. See **What's New** below for the latest, and `FEATURES.md` for the full decision log.

---

## What's New

Plain-language summary of recently shipped features so the team can see what changed without reading the full `FEATURES.md` decision log. Each item links to its FEATURES entry for the *why* and the technical detail.

### June 2026

- **Instrument indexes repaired across all legacy jobs** (FEATURES #51). The emitter now reads both production CSV header schemas (ALL-CAPS and the older Title-Case format), and `backfill_canonical --force` re-emits stale files. Dev went from 3/20 to 20/20 jobs with populated instrument data — the Instrument Index / Datasheet views now fill in for older jobs.
- **Unified symbol taxonomy + label triage** (FEATURES #49, #50). `webapp/taxonomy.json` is now the **single source of truth** for every label's display name, color, glyph, and YOLO routing — backend inference, the Studio palette/canvas, and exports all read from it (no more hand-maintained maps drifting apart). New labels the model emits but the taxonomy doesn't know about are auto-staged into a **Label Triage** queue at **Admin → Label Triage** (`/admin/label-triage`), where a super-admin classifies them; approving appends the new class straight back into `taxonomy.json`. Regenerate the frontend/LS configs after editing the taxonomy — see the *Annotation labels* section below.
- **Studio canvas: P&ID symbol glyphs** (FEATURES #45). Detections now render as proper per-class P&ID symbol glyphs (LS-style colors) instead of plain rectangles, so reviewers recognise valves/instruments at a glance.
- **Deep-zoom that stays sharp** (FEATURES #43, #44). The canvas re-renders the page on-demand at up to 6× and uses layout-based zoom, fixing the pixelation reviewers hit when zooming into dense drawings.
- **Multi-page P&ID sheet attribution** (FEATURES #46). The source page number is threaded through the extractor → parser → emitter, so every row in a multi-sheet deliverable carries the correct **Sheet** number.
- **v1-11 YOLO model deployed** (FEATURES #42). Retrained on +32% annotations; +0.06 mAP50 over v1-10 (arrows +24–29%, valves +10–17%).
- **Local Docker builds no longer need a model PAT** (FEATURES #48). The model-bake step skips cleanly when no GitHub PAT is present, so a fresh clone builds out of the box. (Dev/QA/prod still bake the model via SSM-provided PAT.)

> **Shipping something non-trivial?** Append a `FEATURES.md` entry (the *why*), and if it's user- or team-facing, add a one-line bullet here so the team sees it.

---

## System requirements

| | |
|---|---|
| OS | macOS 12+, Ubuntu 20.04+, or Windows 11 (WSL2) |
| RAM | 8 GB |
| Disk | 10 GB free |
| Docker Desktop | 4.x or later |
| Git | any recent version |

**Everything runs in Docker.** Do not install Python, Postgres, nginx, or Label Studio directly on your machine — the `docker-compose.yml` is the single source of truth and must work as-is in production.

---

## First-time setup

### 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop. After install, open it and wait until the whale icon is steady (not animated).

### 2. Clone the repo

```bash
git clone git@github.com:Qong-Systems/qong_product.git
cd qong_product
```

If your SSH key is configured under a different host alias, use it:

```bash
git clone git@qongsystems:Qong-Systems/qong_product.git
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and ask the team lead for:

| Variable | Notes |
|---|---|
| `OPENROUTER_API_KEY` | Required for PDF extraction. From team lead. |
| `SECRET_KEY` | Signs login cookies. Any random alphanumeric string is fine (`openssl rand -hex 32`). **Avoid `$`** — Docker Compose treats it as a variable substitution and silently truncates the value (FEATURES #19). |
| `LS_API_KEY` | Leave blank for now. Set after step 6 if you need Label Studio integration. |
| `POSTGRES_PASSWORD` | Already in `.env.example`; do not change for local. |
| `ADMIN_PASSWORD` | Used to seed the local `admin` user on first DB bring-up. Pick anything. |

### 4. Build and start the core stack

```bash
docker compose up -d postgres redis web nginx
```

This starts:

| Service | URL | Purpose |
|---|---|---|
| `postgres` | `127.0.0.1:5432` | Primary DB. **Local dev is on Postgres now**, no longer SQLite (FEATURES #20). |
| `redis` | `127.0.0.1:6379` | Job queue + cache. |
| `web` | http://localhost:8000 | FastAPI app + React SPA. |
| `nginx` | http://localhost:9000 | Reverse proxy (mirrors prod topology). |

First build takes ~3 min. Subsequent boots are seconds.

### 5. Log in

Open http://localhost:8000 and sign in with `admin` / the password you set as `ADMIN_PASSWORD` in step 3. Upload any P&ID PDF and you should see a Job queued on the dashboard.

If you need the canonical local admin password used on the team, ask the lead or check `~/.claude/.../memory/reference_local_admin_password.md`.

### 6. (Optional) Start Label Studio for annotation

```bash
docker compose up -d label-studio
```

Open http://localhost:8080. First run, register with your team email. Then **Account & Settings → Access Token → Copy** and paste into `.env`:

```env
LS_API_KEY=your-token-here
```

```bash
docker compose restart web
```

### 7. (Optional) MinIO + GPU worker

`minio` and `gpu-worker` services are defined in `docker-compose.yml` but are off by default for local dev. Start them only if you're working on the GPU detection path:

```bash
docker compose up -d minio gpu-worker
```

---

## Daily commands

```bash
# Bring up the standard stack
docker compose up -d postgres redis web nginx

# Tail webapp logs
docker compose logs -f web

# Run unit tests inside the web container
docker compose exec web python3 -m pytest tests/unit/ -v

# Open a Python shell with DB context
docker compose exec web python3

# Stop everything
docker compose down
```

---

## Repo layout

```
qong_product/
├── CLAUDE.md              # Conventions, branch policy, gotchas. Read on every session.
├── FEATURES.md            # Append-only decision journal. Latest entries are at the bottom.
├── SESSION_STATE.md       # One-page handoff: what stopped, what's blocked, next step.
├── docker-compose.yml     # All services. Single source of truth.
├── docker-compose.override.{dev,qa}.yml  # Env-specific overrides (committed)
├── .env.example           # Template for local secrets
│
├── pipeline.py            # PDF → CSV orchestrator (production path via extractor.py)
├── extractor.py           # OpenRouter Vision API client (PRODUCTION)
├── detector.py            # Offline YOLO+OCR (INTERNAL / training only — see CLAUDE.md)
├── parser.py              # Tag + line-number parsing
├── instrument_parser.py   # Instrumentation index parser
├── corrections.py         # Per-drawing manual overrides
├── prompts.py             # Vision prompt templates
│
├── webapp/                # FastAPI app
│   ├── main.py              # ASGI entrypoint
│   ├── routers/             # API endpoints (api_v1.py, jobs.py, admin.py …)
│   ├── deliverables/        # Canonical schema + generator registry + customer templates
│   ├── models.py            # SQLAlchemy models (User, Job, EntityOverride …)
│   ├── frontend/            # React 19 + Vite SPA
│   │   └── src/
│   │       ├── marketing/   # Public landing page (/)
│   │       ├── dashboard/   # Logged-in project list
│   │       ├── studio/      # Qong Studio canvas (Konva), datasheet drawer, bulk review
│   │       ├── admin/       # User + template management
│   │       └── routes/      # React Router config
│   └── templates/           # Jinja shells (mostly deprecated — SPA serves everything)
│
├── annotate/              # Label Studio export scripts + tile cache
├── datasets/              # YOLO training dataset (images gitignored)
├── models/                # ONNX weights (gitignored)
├── nginx/                 # Reverse-proxy config
├── compose/, deploy/      # Build artifacts
└── docs/
    ├── claude/              # Detail index (pipeline, webapp, deployment, training)
    ├── decisions/           # Long-form architecture decisions
    └── onboarding/          # Vision pack for new team members
```

**Important read-on-demand docs:**

| If you're working on… | Read |
|---|---|
| Pipeline / OCR / detection | `docs/claude/pipeline.md` |
| Webapp / SaaS features | `docs/claude/webapp.md` |
| Deployment / AWS / nginx | `docs/claude/deployment.md` |
| Training / GPU / annotation | `docs/claude/training_and_gpu.md` |
| Deliverables / templates | `docs/claude/deliverables.md` |

---

## Branches & deploy flow

| Branch | Purpose | Auto-deploys to |
|---|---|---|
| `dev` | Active development; branch features off this and PR back | `dev.qongsystems.com` via `.github/workflows/deploy-dev.yml` |
| `qa` | QA release candidate | `qa.qongsystems.com` via **manual** `deploy-qa.yml` (workflow_dispatch) |
| `main` | Reserved for production cutover | nothing yet — prod infra not provisioned |
| `dt/*` | Experimental graph-extraction R&D track (`experiments/digital_twin/`) | nothing — never deploys; merges into `dev` only at handoff |

Push to `dev` triggers GitHub Actions, which uses SSM Session Manager to deploy onto the EC2 instance (no SSH keys, no public port 22). Workflow runs ~3 min end-to-end.

QA deploys are **manual** via `deploy-qa.yml` workflow_dispatch. QA EC2 is **stopped** by default to save ~$30/mo — restart from the AWS console or `aws ec2 start-instances --instance-ids i-04be6af1fb7929a0c --region ap-south-1 --profile tnbqong`, then update the Cloudflare A-record for `qa.qongsystems.com` (new public IP each restart).

---

## Annotation labels — `webapp/taxonomy.json` is the source of truth

The label set is no longer a hand-kept list in this README (it used to drift). As of FEATURES #49/#50 **every label lives in `webapp/taxonomy.json`** — currently **43 classes** (23 the YOLO model can detect, plus 20 palette-only classes reviewers can mark by hand). That one file drives the YOLO class order, display names, colors, canvas glyphs, the Studio palette, and the Label Studio annotation config.

**Don't edit label lists in code or in Label Studio by hand.** Instead:

1. Edit `webapp/taxonomy.json` (add a class, change a display name/color/glyph).
2. Regenerate the downstream configs:
   ```bash
   python3 scripts/gen_taxonomy_ts.py      # → webapp/frontend/src/studio/taxonomy.generated.ts
   python3 scripts/gen_ls_label_config.py  # → Label Studio labeling config
   ```
3. On startup the webapp upserts the taxonomy into the `label_taxonomy` table (`webapp/taxonomy_db.py`), keeping the DB read-index in sync.

When the model emits a label the taxonomy doesn't recognise, it's auto-staged into the **Label Triage** queue (**Admin → Label Triage**) for a super-admin to classify — approving writes the new class back into `taxonomy.json`. So the live taxonomy grows through review, not ad-hoc code edits.

> Annotators: open the live palette in Qong Studio (or `webapp/taxonomy.json`) for the current names, colors, and glyphs. Tag formats the parser accepts (KKS, etc.) are documented in `docs/claude/pipeline.md`.

---

## Onboarding checklist

Day 1:
- [ ] Clone the repo, set up `.env`, run `docker compose up -d postgres redis web nginx`.
- [ ] Log in at http://localhost:8000 with `admin` / your `ADMIN_PASSWORD`.
- [ ] Upload `docs/INPUT-MUK-62-1-15-1004-001-24C7-D.pdf` (sample drawing). Confirm a Job appears, runs to `completed`, and you can download the valve list CSV.
- [ ] Read `CLAUDE.md` end to end.

Day 2:
- [ ] Read the last 10 entries of `FEATURES.md`.
- [ ] Read `SESSION_STATE.md` and ask the lead about anything marked "blocked" or "next".
- [ ] Browse `docs/claude/` and pick the detail file that matches your assignment.
- [ ] (Web devs) `cd webapp/frontend && npm install && npm run dev` for the Vite hot-reload UX. SPA runs at http://localhost:5173 and proxies API calls to the dockerised webapp on :8000.

Day 3+:
- [ ] Pick a Jira ticket (project **SCRUM** / future **QS**) and branch off `dev`.
- [ ] When you ship something non-trivial, **append a `FEATURES.md` entry** describing the *why* and *what*. Do not edit past entries.

---

## Troubleshooting

**Docker build fails on first run.** Make sure Docker Desktop is fully started (whale icon steady), then `docker compose build --no-cache web`.

**"OPENROUTER_API_KEY not set" error.** Confirm `.env` exists and the key has no `$` characters. `docker compose restart web`.

**Webapp 500 on `/` after pull.** There is **no Alembic** — schema changes run automatically on startup via `webapp/database.py:run_migrations()`. Just restart the container: `docker compose restart web`, then check `docker compose logs web` for a migration error.

**Jobs stuck in "processing" after restart.** Normal — startup hook resets them to `failed`. Re-run from the dashboard.

**Label Studio 500 after first login.** See `CLAUDE.md` for the org-creator fix snippet.

**Port 8000, 9000, or 5432 already in use.** Stop whatever's holding it, or remap in `docker-compose.override.yml` (or a personal `docker-compose.local.yml` — gitignored).

**`git push` to `Qong-Systems` says permission denied.** The `gh` CLI is authed as `tarunhere` (admin of `Winn-Projects` only). Use the `qongsystems` SSH alias for git pushes; ask the lead before creating new Qong-Systems repos.

**Local edits to a route in `webapp/main.py` aren't taking effect.** Grep `webapp/routers/*.py` for the same path — router-includes register before `@app.get` decorators in `main.py`, so a duplicate router-side route silently shadows it (CLAUDE.md / FEATURES #24).

---

## Getting help

- Check `SESSION_STATE.md` first — the previous session's blockers and next steps are spelled out.
- Detailed conventions and the long list of footguns are in `CLAUDE.md`.
- For long-form architecture decisions, see `docs/decisions/`.
- Team lead: Tarunkumar Bhambava (`leo.tarunb@gmail.com`).
