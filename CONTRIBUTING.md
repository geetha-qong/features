# Contributing — Qong Product

How we make changes to `Qong-Systems/qong_product`. **Everyone follows this.**

> **Important:** the repo is **private on the GitHub Free plan**, so branch
> rulesets are **not enforced** by GitHub. The 2-approval gate below is a
> **team convention** — GitHub will still show a green "Merge" button without
> approvals. **Do not click Merge until the rule is satisfied.** We rely on
> discipline, not enforcement.

## Branch model

| Branch | Role | How it changes |
|--------|------|----------------|
| `dev`  | Integration + **review gate**. Auto-deploys to dev.qongsystems.com on every push/merge. | **PR only** (see below) — no direct pushes. |
| `qa`   | QA release candidate (qa.qongsystems.com, manual deploy). | Fast-forward from `dev`. |
| `main` | Future production (app.qongsystems.com). | Fast-forward from `qa`. |

`dev` is where review happens. Once something is approved and merged into `dev`,
promotion to `qa` and `main` is just a fast-forward — no second review needed.

## The workflow (every change)

1. **Branch off `dev`:** `git checkout dev && git pull && git checkout -b feature/<short-name>` (or `fix/<short-name>`).
2. **Commit + push the branch:** `git push -u origin feature/<short-name>`.
3. **Open a Pull Request into `dev`.**
4. **Get 2 approvals** from teammates **other than the author** before merging.
   - If new commits are pushed after approval, re-request review (treat prior approvals as stale).
   - Resolve all PR conversations before merging.
5. **Merge** → `dev` auto-deploys. Watch the deploy (the live SPA bundle hash on `/` flips when it's live).
6. **Promote when ready:** `dev → qa → main` by fast-forward only.

**Never push directly to `dev`, `qa`, or `main`.**

## Don't break a running job

A deploy recreates the `cpu-worker` container and will kill an in-flight job.
Before merging to `dev`, make sure no job is processing (the running job fails
with `No heartbeat for >90s`). See `CLAUDE.md` → VM access for how to check.

## Repo safeguards (enforced — set by an org owner)

- **Repository deletion disabled** for members: Org → Settings → Member privileges
  → "Repository deletion and transfer" unchecked. Only org owners can delete a repo.
- **Members have `write`, not `admin`** — write users cannot delete or transfer the repo.
- **2FA required** org-wide.

## Commit / PR conventions

- Match the existing commit style (`type(scope): summary`, e.g. `feat(studio): …`, `fix(datasheet): …`).
- Append one entry to **`FEATURES.md`** for every meaningful feature / behavior change / decision (newest first; never edit past entries). See `CLAUDE.md`.
- End commit messages with the Co-Authored-By trailer used in this repo when applicable.

See **`CLAUDE.md`** for environment, deploy mechanics, and the full set of gotchas.
