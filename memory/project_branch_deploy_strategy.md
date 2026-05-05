---
name: Branch and Deployment Strategy
description: Git branch → environment mapping and production domain plan
type: project
---

Two-environment strategy:

- `dev` branch → **dev.qongsystems.com** (GCP VM `qong-dev-server`, 34.124.148.51) — auto-deploys on every push to `dev`
- `main` branch → **app.qongsystems.com** (production, not yet live) — will be set up when ready for launch

**Why:** Keeps dev and prod environments fully isolated; team can push to dev freely without touching prod.

**How to apply:**
- Always merge feature work into `dev` first
- When ready to ship, PR `dev` → `main` for production cutover to `app.qongsystems.com`
- `feature/multi-cloud-saas` was the staging branch during initial GCP migration; it is now superseded by `dev`
- Do NOT push directly to `main` until production infra (app.qongsystems.com, separate GCP VM or same with different compose profile) is set up
