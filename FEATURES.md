# FEATURES — Append-only decision log

> Every meaningful feature, model swap, threshold change, architecture decision, bugfix, experiment, or business decision gets one entry here. **Newest first. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`.** Recording the *reasoning* matters more than the choice.

**Why this file exists:** so we don't repeat ourselves. Every Claude Code session, every team standup, every "why did we decide that?" question — answer is here. Convention adopted from the QS-60 vision pack (see `docs/onboarding/`).

**Format for each entry** (keep under 200 words; long discussions go in `docs/decisions/NN-title.md` and link here):

```
## [YYYY-MM-DD] #NN — <short title, sentence case>

**Type:** feature | model-swap | threshold-tune | architecture | bugfix | experiment | decision | business
**Stage:** ingestion | preprocess | symbols | lines | direction | text | associate | graph | validate | review | export | training | infra | webapp
**Status:** shipped | experimental | reverted | superseded-by-#NN

**Why:** 2–4 sentences. What problem, where the request originated. Origin matters more than description.

**What:** What was built or changed. Files touched. Public interfaces added or modified.

**Result (if measurable):** Numbers, not adjectives.

**Notes:** Weird things next session should know. Hardcoded values that should become config. Dead ends. Links.
```

---

## [2026-05-27] #08 — Qong Studio MVP scope locked: agency beachhead, 4 deliverables, Aug '26, Level-2 vendor inclusion via separate Laravel portal

**Type:** decision, architecture
**Stage:** infra, webapp
**Status:** shipped (design doc); implementation plan to follow

**Why:** The 9-month phased plan in `docs/onboarding/ARCHITECTURE.md` §5 was written before the MVP shape was sharpened around a beachhead persona and the marketplace revenue model. Brainstorm session 2026-05-27 surfaced: (a) the customer is P&ID-digitization **agencies**, not big-oil or individual engineers; (b) the Datasheet deliverable specifically needs vendor data to be a complete product, which means at least Level-2 vendor inclusion is required for MVP; (c) Omprakash is the team capacity bottleneck — the only way to fit Level-2 in 14 weeks is for Tarunkumar to own the vendor portal as a separate Laravel app, freeing Omprakash to focus on Qong Studio canvas + templates + deliverable generators. Without this scoping, the team would spend 6 months building a maximalist version of what only needs to be focused.

**What:** Wrote `docs/decisions/01-qong-studio-mvp-design.md` — the authoritative MVP spec. Locks four deliverables (Valve List, Instrument Index, Datasheet, Equipment List), per-customer template engine (3-5 hardcoded JSON templates), Qong Studio React/Konva canvas, free-for-design-partners MVP with manual invoicing on paid signups, separate Laravel vendor portal owned by Tarunkumar, vendor data living in Qong's Postgres as single source of truth with Laravel calling Qong's REST API. Explicit deferral list: Line List + topology + Cable Schedule + JB Schedule + Manuals + Cause & Effect + Control Narrative → FLEDGE Oct '27; Stripe + in-house quote management + customer-editable template editor + collaborative review → v1.5 (Q4 '26 / Q1 '27); SSO + on-prem + DGX Spark → post-MVP. Sprint 1 work in QS-48/50/52/54/56/60/62/64/65/66/68 continues unchanged; this design doc tells subsequent sprints what they're building toward.

**Result:** Per-person FTE-week budget now balances: Omprakash 14/14, Geetha 13/14, Swaraj 9/14, Tarunkumar partial-FT. Capacity gap that the brainstorm started with (32 weeks of work on Omprakash) is closed without slipping the Aug '26 target.

**Notes:** Reversible only by formal supersession with a new `docs/decisions/NN-...md` entry — not by drift. Several items intentionally left as open questions in the design doc §8 to resolve in the implementation-plan step (seed vendor list, Laravel build-or-contract call, hosting topology, org-role schema, PaddleOCR upgrade scope, design-partner agency list). FEATURES.md entries #04 (no DEXPI), #03 (Konva), #06 (no GPU queue) all remain load-bearing for this design.

---

## [2026-05-27] #07 — QS-60 vision pack lands in `docs/onboarding/`; root discipline files stay canonical

**Type:** decision, architecture
**Stage:** infra
**Status:** shipped

**Why:** QS-60 (Omprakash onboarding) produced a 10-file "full-project-guide" pack — `PROJECT_VISION.md`, `ARCHITECTURE.md`, `REVIEW_UI_SPEC.md`, `ACTIVE_LEARNING_SPEC.md`, `DATASETS.md`, `REFERENCES.md`, `README.md`, plus its own copies of `CLAUDE.md` / `FEATURES.md` / `SESSION_STATE.md`. Sitting at repo root as `full-project-guide/`, the latter three would silently shadow the live root discipline files during any `Read CLAUDE.md` lookup. Risk: a future session reads the pack's template SESSION_STATE.md (dated 2026-05-25 "initial seed") instead of the real one and wipes the actual handoff. The pack is reference material, not active state.

**What:** Moved 7 vision/spec files from `full-project-guide/` to `docs/onboarding/`. Deleted the 3 conflicting duplicates. Removed empty `full-project-guide/`. Patched `docs/onboarding/README.md` to point new joiners at the live root `CLAUDE.md` instead of its (deleted) sibling. Also: deleted loose root one-offs `intern_jd.html`, `intern_offer_letter.html`, `readfirst.txt`. Committed `ref/` (5.4 MB customer PDFs for the Ronesans/Ebara instrument-index investigation), `patent.md`, and `Dockerfile.{mcp,trainer}` (already wired into `docker-compose.yml`; fresh clones could not build without them). `.gitignore` extended for `/*.pt`, `datasets/**/*.cache`, `annotate/exports/*.zip`.

**Result:** N/A (docs reorg). Repo size unchanged on disk; no large binaries now tracked.

**Notes:** `data_room/` additions (investor HTML pack) left untracked for now — owned by Vrushab, not core eng. `yolov8s.pt` (22 MB base weights) and `annotate/exports/*.zip` (24 MB LS export) intentionally ignored — regenerable. The vision pack still describes the *future* monorepo layout (`pipeline/`, `api/`, `web/`, etc.) which doesn't match today's flat layout — that's expected, it's the north-star doc.

---

## [2026-05-26] #06 — No backend GPU job queue; shared IAM role + per-user IAM users + runs.jsonl

**Type:** architecture, decision
**Stage:** training, infra
**Status:** shipped (rollout in Sprint 1 via QS-48 + QS-52)

**Why:** Training cadence is 1-3 runs/week (manual ad-hoc) growing to weekly automated by Sprint 4. Building a backend queue (REST endpoint + UI + status polling) is ~1-2 weeks of work for no benefit at this volume — there's no real concurrency to coordinate, and AWS spot/on-demand instances don't care about parallel launches.

**What:**
- One shared IAM role `qong-trainer-burst` with EC2 + S3 + SSM permissions
- Four IAM users (`tarunkumar`, `geetha`, `swaraj`, `omprakash`) — each with MFA — assume the shared role
- `s3://qong-training-artifacts/runs.jsonl` is the team-visible log of every training run: `aws_train_burst.sh` appends one line at start (status=running) and one at end (status=success/failed + cost + model artifact). Anyone reads with `aws s3 cp s3://.../runs.jsonl - | jq`.
- CloudTrail provides full per-user audit for free.
- Instance type: **on-demand** g5.xlarge for now (~$1/hr, no termination risk). Switch to spot in Sprint 4 when checkpointing is added.

**Result:** ~3 hours of additional work in Sprint 1 (folded into QS-48 + QS-52 — no new tickets) vs ~1-2 weeks for a real queue. Equivalent visibility for the team via the runs.jsonl log.

**Notes:** Revisit if/when training runs exceed ~5/day AND coordination problems appear (e.g., same experiment launched twice). Probably never at team size 4. The Sprint 4 active-learning loop will use the same shared role + runs.jsonl, so we're not building this twice.

---

## [2026-05-26] #05 — Project Jira (SCRUM) + Confluence wired; Sprint 1 ready

**Type:** infra
**Stage:** infra
**Status:** shipped

**Why:** Need a single board the whole team (lead + 3 interns + CEO as customer-tester) coordinates from. Pure-doc planning doesn't survive a multi-month project.

**What:** Created 8 Jira epics in SCRUM project (project name "QS-Customers"; key will be renamed SCRUM→QS via admin UI), 11 Sprint 1 stories balanced 3/2/3/3 across Tarunkumar/Omprakash/Geetha/Swaraj. Two Confluence pages: full technical plan (SD space) + customer-flow exec summary (Q space).

**Result:** Sprint 1 stories visible at https://qongsystems.atlassian.net/browse/SCRUM-48 ... SCRUM-68. All assignees set with Atlassian account IDs.

**Notes:** Project rename SCRUM→QS pending — admin must do via Project Settings → Details → Key. Old issue links auto-redirect after rename. Vrushab (CEO) is *not* in Jira as a developer; he's the customer-tester from Sprint 3 onwards.

---

## [2026-05-26] #04 — No DEXPI XML export — proprietary deliverables only

**Type:** business decision
**Stage:** export
**Status:** shipped

**Why:** The earlier architecture spec (`full-project-guide/`) treated DEXPI 2.0 as the canonical output format. Strategic reversal: providing a clean industry-standard exit format makes it easy for customers to migrate off our platform. We want lock-in.

**What:** All customer deliverables stay in proprietary CSV / PDF / XLSX. The graph data model + queryable graph stay internal. No `pydexpi` integration. Sprint 15-16 deliverables (BOM, equipment list, loop trace) are derived from the graph but exported in our formats only.

**Notes:** Reversible later if a paying customer specifically demands DEXPI for procurement integration. Document any such request and weigh per-customer.

---

## [2026-05-26] #03 — Frontend stack locked: React 19 + Vite + react-konva + Zustand + TanStack Query

**Type:** architecture
**Stage:** review (UI)
**Status:** shipped

**Why:** Review UI is the product wedge. Spec targets `<800ms first paint, 60fps pan/zoom` on 4K P&IDs — needs a real SPA, not server-rendered templates. Konva chosen over PixiJS because real P&IDs peak at 5K–10K elements (well within Konva's smooth range); PixiJS only wins above 10K and costs 6–8 weeks WebGL ramp-up.

**What:** New directory `webapp/frontend/` will contain the React app. Mounted at `/jobs/{id}/review` via FastAPI static-files. Pydantic-derived TS types from `webapp/schemas/`. Vitest unit tests + Playwright E2E. Stack lifted directly from `full-project-guide/REVIEW_UI_SPEC.md` + decision #03 in `full-project-guide/FEATURES.md`.

**Notes:** Omprakash (sole web dev) owns the entire frontend. Risk: 8-10 week MVP slips to 12 weeks if React learning curve hits hard. Lead pair-programs with him 2hr/week to mitigate + learn alongside.

---

## [2026-05-26] #02 — AWS burst-mode EC2 replaces Windows GPU + Tailscale for training

**Type:** infra
**Stage:** training
**Status:** shipped (rollout in Sprint 1)

**Why:** Windows GPU + Tailscale is a single point of failure with a fragile connection. After v1-9 training run today (multiple hours of Tailscale debugging), the cost-of-fragility is unacceptable for a team that will retrain weekly via active learning.

**What:** AWS account + IAM role `qong-trainer-burst` + S3 bucket `qong-training-artifacts` (ap-south-1 / Mumbai) + EC2 launch template `qong-train-burst` (g5.xlarge spot, ~$0.30/hr, NVIDIA A10G 24GB VRAM, Ubuntu 22.04 + CUDA 12 AMI). New `scripts/aws_train_burst.sh` does spin-up → SCP dataset → SSM-run train_gpu.py → SCP model back → terminate. SSM (not SSH) for instance access — no key management.

**Result (target):** v1-10 retraining completes in 60-90 min for $5-15 per run. Documented in Sprint 1 SCRUM-52.

**Notes:** Windows GPU stays as fallback for 30 days then decommissioned. Tailscale link removed once decommissioning is confirmed.

---

## [2026-05-26] #01 — Digital twin platform project kicked off — human-in-the-loop wedge

**Type:** architecture, business decision
**Stage:** webapp, review, training
**Status:** shipped (planning + Sprint 1 ready)

**Why:** Customer feedback: the current valve-list extraction is good but customers do the work twice — they get a CSV, then manually fix what's missing. They want all deliverables in one sitting: valve list + instrument index + datasheets + future BOM / loop trace / equipment list. End-state: ship as on-premises **Qong Box** appliance once models are good enough.

**What:** Single-product trajectory in same repo. New branch `feature/digital-twin` from `dev`. Existing valve-list flow keeps running for paying customers throughout. 8-10 week MVP across Sprints 1-5 = shadow graph + review UI + active learning loop. Post-MVP Months 3-6 = multi-page + cross-page, pipe tracing + flow direction, new deliverables (BOM, equipment list, loop trace), production switchover from API to graph-derived outputs.

Plan: `/Users/maahedev/.claude/plans/async-soaring-puppy.md` (also in Confluence SD space).

**Notes:** **Auto-improving model loop** is built in Sprint 4 (Weeks 7-8), not Sprint 1. Sprint 1 lands the *plumbing* (ReviewEvent + TrainingEvent schemas + LS migration). Until Sprint 4 ships, model retraining stays manual. Headline metric is graph isomorphism (`networkx.is_isomorphic`) not symbol mAP.
