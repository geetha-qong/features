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

**Current state (June 2026):** Phase 1–4 frontend ported to React SPA (Marketing, Dashboard, Studio canvas, Admin). Deliverables subsystem live with four generators + per-customer JSON templates. Spec A Day 1 (editable deliverables backend) shipped — `entity_overrides` + merge layer + `GET/PATCH /api/v1/jobs/{id}/entities`. AWS migration complete (ap-south-1), Postgres in all envs, GitHub Actions + SSM auto-deploys on dev. See `FEATURES.md` #21–26 for the most recent changes.

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
| `dev` | Active development | `dev.qongsystems.com` via `.github/workflows/deploy-dev.yml` |
| `feature/digital-twin` | Long-running MVP work (stale — to be deleted after soak) | nothing |
| `main` | Reserved for production cutover | nothing yet — prod infra not provisioned |

Push to `dev` triggers GitHub Actions, which uses SSM Session Manager to deploy onto the EC2 instance (no SSH keys, no public port 22). Workflow runs ~3 min end-to-end.

QA deploys are **manual** via `deploy-qa.yml` workflow_dispatch. QA EC2 is **stopped** by default to save ~$30/mo — restart from the AWS console or `aws ec2 start-instances --instance-ids i-04be6af1fb7929a0c --region ap-south-1 --profile tnbqong`, then update the Cloudflare A-record for `qa.qongsystems.com` (new public IP each restart).

---

## Annotation labels (13 classes)

When annotating tiles in Label Studio, use **exactly** these label names — the pipeline parser is case- and underscore-sensitive.

### Valves
| Label | Symbol |
|---|---|
| `valve_bf` | Butterfly — bowtie / diamond shape |
| `valve_bv` | Ball — circle with line through it |
| `valve_ck` | Check — arrowhead or half-circle |
| `valve_gl` | Globe — circle with plug/bonnet on top |
| `valve_db` | Double Block & Bleed — cluster of 3 small symbols |
| `valve_cv` | Control valve — circle with dome actuator on top |
| `valve_gen` | Generic (gate, needle, safety, pressure, flow valves) |

### Actuators
| Label | Symbol |
|---|---|
| `actuator_motor` | Square box with letter **M** |
| `actuator_pneu` | Dome/diaphragm shape above valve |
| `actuator_sol` | Box labelled **SL** or coil symbol |

### Instruments
| Label | Symbol |
|---|---|
| `inst_bubble` | Circle with tag text (PT, TT, FT, LT, PDT, PI, PS, ZS…) — draw box around circle + text |
| `inst_cv` | Control/shutdown valve (FCV, XV) — full symbol including actuator |
| `inst_solenoid` | Solenoid box/coil (FY, XY) |

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

**Webapp 500 on `/` after pull.** Run database migrations: `docker compose exec web python3 -m alembic upgrade head`.

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
