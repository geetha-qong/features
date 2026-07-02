# Resilient OCR-Completion Gate — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorm), pending implementation plan
**Branch base:** `dev` (NOT `feat/graph-gt-freeze` — the `ocr_status` gate, the
`Job.ocr_status` column, and `_effective_status` only exist on `dev`).

## Problem

The dashboard holds a job's card at **"Preparing"** while extraction is `done`
but the background OCR tag-resolution step is still `pending` (FEATURES
#132/#134). This is the intended UX: only show a job as openable once *all*
background work has succeeded.

The gate has no failure or timeout safety. The background OCR runner
(`run_detections_ocr_rq` in `webapp/routers/bbox_ocr.py`) has **no exception
handling**: it calls `compute_tagged_detections(job)` and only then sets
`job.ocr_status = "done"`. If that call raises, or the cpu-worker is recreated
mid-run (the documented "don't push to dev while a job is processing" hazard —
the dominant failure mode), or the queue never picks the job up, the
`"done"` line is never reached. RQ may mark its own job `failed`, but nothing
writes that back to `Job.ocr_status`, so the job sits `pending` **forever** and
the card is trapped at "Preparing" with no way out.

Real instances: jobs 14, 28, 29, 32 (all 2026-03-27) sat `done`+`pending`
indefinitely until manually flipped this session.

## Goal

A job's card must **never** trap at "Preparing." Keep the hard gate (card stays
"Preparing" until OCR completes, *then* becomes openable), but make it resilient:
a stuck or failed OCR job recovers — preferably by actually succeeding, and
failing that, by releasing the card to **Done** (graceful degradation: the
detections simply lack OCR-resolved tag enrichment).

This is a behavior-hardening change, not a UX redesign. The "Preparing → Done"
flow the user already has is preserved; only the dead-end is removed.

## Non-Goals

- No soft-gate / "tags resolving…" badge (explicitly rejected — keep the hard gate).
- No distinct `"ocr_failed"` status or visible failure badge — released state is
  plain `"done"`.
- No change to how OCR itself computes tags (`compute_tagged_detections` is
  untouched except for being wrapped in a failure handler at its RQ call site).
- No new scheduler infrastructure (no rq-scheduler / cron). Recovery uses the
  existing request read path, the existing RQ worker, and the existing startup
  leader-lock reconcile block.

## Design Decisions (from brainstorm)

1. **Gate model:** keep the hard gate, make it resilient (not a soft gate).
2. **Recovery:** retry once (catch the transient deploy-kill), then
   timeout-release. Defense-in-depth across three layers.
3. **Timeout backstop:** 20 minutes, measured from OCR enqueue time. Above a
   normal multi-minute run and above a single 15-min RQ attempt, so a
   still-working job is never falsely released.
4. **Released state:** `"done"` (graceful degradation), not a distinct failed state.

## Architecture — Three Layers + One Supporting Change

The split is driven by a hard constraint: `api_list_jobs` and `job_status` are
`async def`. CLAUDE.md forbids blocking synchronous calls (e.g. a DB write)
inside an `async def` endpoint — it freezes the worker event loop (the cause of
the prior 50s page loads). Therefore the **read path stays pure computation
(no DB writes)**, and all *persistence* of recovered state happens outside the
request path (on the cpu-worker, or in the startup reconcile).

### Supporting change — `Job.ocr_enqueued_at` timestamp

The timeout needs to know how long a job has been pending.

- Add nullable `ocr_enqueued_at` (timestamptz) to the `Job` model
  (`webapp/models.py`) and to `run_migrations()` `new_columns` in
  `webapp/database.py` (no Alembic; race-safe existence probe pattern).
- Set it to the current UTC time at **every** site that sets
  `ocr_status="pending"`:
  - `webapp/pipeline_runner.py` (~line 466)
  - `webapp/routers/bbox_ocr.py:_enqueue_detections_ocr` (the pending-set block)
- Use `webapp/datetime_utils.py` for UTC (never bare `datetime.now()`); the
  column is timestamptz per the repo's UTC-on-the-wire convention.
- **NULL semantics:** a NULL `ocr_enqueued_at` (legacy jobs, or a pending set
  before this change) is treated as **not overdue** by the read path (Layer 1)
  so display logic never touches it, but it **is** swept on startup (Layer 3)
  so the DB gets cleaned exactly once.

### Layer 1 — Read-time display backstop (card never *visually* traps)

In `webapp/routers/api_v1.py:_effective_status` and
`webapp/routers/jobs.py:job_status`, extend the existing pure read-time status
computation:

```
if job.status == "done" and job.ocr_status == "pending":
    if job.ocr_enqueued_at is not None and (now_utc - job.ocr_enqueued_at) > 20 min:
        return "done"      # overdue → display as done
    return "processing"    # still within window → hold at Preparing
return job.status
```

- **No DB write** — pure computation, respects the async constraint.
- Guarantees an overdue card releases the instant anyone loads the dashboard,
  even if no worker handler or sweep ran.
- The 20-minute threshold is a single shared module-level constant
  (e.g. `OCR_STALE_AFTER = timedelta(minutes=20)`) so Layers 1 and 3 cannot drift.

### Layer 2 — Worker failure reflection + retry (tries to succeed; persists truth)

In `webapp/routers/bbox_ocr.py`:

- **Retry:** enqueue OCR with `rq.Retry(max=1)` in `_enqueue_detections_ocr`'s
  `q.enqueue(...)` call. A deploy-killed first attempt auto-retries — the common
  transient self-heals and OCR genuinely succeeds.
- **Failure reflection:** wrap the `compute_tagged_detections(job)` call in
  `run_detections_ocr_rq` in try/except. On exception (this is the *final*
  attempt RQ hands to the function), persist `job.ocr_status = "done"` and
  commit, then re-raise so RQ still records the job as failed for observability.
  This runs on the cpu-worker (not an async request), so the DB write is safe
  and the gate releases immediately rather than waiting for the 20-min backstop.

### Layer 3 — Startup reconcile sweep (persists truth for unviewed jobs)

In `webapp/startup.py` (the Redis `SET NX` leader-lock block that already runs
import-time reconciliation — watchdog, LS reconcile, stale-reset, once per
deploy in exactly one worker):

- Add a one-time sweep: `UPDATE jobs SET ocr_status='done' WHERE status='done'
  AND ocr_status='pending' AND (ocr_enqueued_at IS NULL OR
  ocr_enqueued_at < now_utc - 20 min)`.
- Persists the released state so cross-job consumers (admin dashboards,
  `score_graph`, entity index) never see phantom pendings, and heals jobs whose
  worker died and were never re-enqueued (including the NULL-timestamp legacy
  pendings).
- Runs outside any request path → DB write is safe.
- Idempotent and cheap (single UPDATE, indexed on a small predicate).

## Data Flow Summary

```
pipeline run → ocr_status=pending, ocr_enqueued_at=now → enqueue (Retry max=1)
   │
   ├─ attempt succeeds              → ocr_status=done                     (normal)
   ├─ attempt killed by deploy      → RQ auto-retries → succeeds → done   (transient self-heal)
   ├─ both attempts raise           → worker try/except persists done + re-raises (immediate release)
   ├─ worker never runs / dead queue
   │     ├─ someone loads dashboard → read-time backstop displays done   (>20min, no write)
   │     └─ next deploy/startup     → sweep persists done                (>20min)
   └─ legacy NULL-timestamp pending → read path: not overdue (untouched)
                                      startup sweep: swept once → done
```

## Error Handling

- Read path (Layer 1): cannot fail — pure arithmetic on a nullable datetime.
  The `ocr_enqueued_at is not None` guard short-circuits the overdue check, so a
  NULL timestamp on a `done`+`pending` job yields `processing` (held at
  Preparing). This is a transient migration state: any pending set after this
  change carries a timestamp, and the first startup sweep (Layer 3) clears every
  pre-existing NULL-timestamp pending. So NULL pendings can only linger between
  deploys, and the deploy that ships this change clears them.
- Worker handler (Layer 2): the try/except must not swallow the original error
  silently — log it (logger.warning with job id + exception) and re-raise after
  persisting, so RQ failure observability is retained.
- Startup sweep (Layer 3): wrap in try/except with visible logging (follow the
  existing reconcile-block error pattern); a sweep failure must not block
  startup.

## Testing

Unit tests (host pytest needs `SECRET_KEY` ≥32 chars):

1. **`_effective_status` / `job_status` read-time backstop:**
   - done + pending + `ocr_enqueued_at` 21 min ago → `done`.
   - done + pending + `ocr_enqueued_at` 5 min ago → `processing`.
   - done + pending + `ocr_enqueued_at` NULL → `processing` (not overdue).
   - done + ocr_status done → `done`.
   - done + ocr_status NULL (legacy, never enqueued) → `done` (unchanged #134 behavior).
2. **Worker failure reflection (`run_detections_ocr_rq`):**
   - `compute_tagged_detections` raises → `ocr_status` persisted `done` AND the
     exception re-raised (assert both).
   - `compute_tagged_detections` succeeds → `ocr_status` done (existing behavior intact).
3. **Enqueue sets timestamp + Retry:**
   - `_enqueue_detections_ocr` sets `ocr_enqueued_at` when it sets pending.
   - enqueue call passes `retry=Retry(max=1)` (assert via a mock/spy on the queue).
4. **Startup sweep:**
   - pending + `ocr_enqueued_at` 25 min ago → swept to done.
   - pending + `ocr_enqueued_at` 5 min ago → left pending.
   - pending + NULL timestamp → swept to done.
   - non-pending jobs untouched.
5. **Migration:** `ocr_enqueued_at` column added idempotently (re-run safe).

Shared constant test: Layers 1 and 3 reference the same `OCR_STALE_AFTER`.

## Files Touched

- `webapp/models.py` — add `ocr_enqueued_at` column.
- `webapp/database.py` — `run_migrations()` `new_columns` entry.
- `webapp/routers/api_v1.py` — `_effective_status` read-time backstop + import constant.
- `webapp/routers/jobs.py` — `job_status` read-time backstop.
- `webapp/pipeline_runner.py` — set `ocr_enqueued_at` at the pending-set site.
- `webapp/routers/bbox_ocr.py` — `Retry(max=1)`, set timestamp, worker try/except,
  define/host the `OCR_STALE_AFTER` constant (or a small shared module).
- `webapp/startup.py` — startup reconcile sweep.
- Tests under `tests/unit/` for each layer.

## Rollout

- Branch off `dev`, PR back per the 2-approval policy.
- The migration is additive (nullable column) — safe on deploy.
- Existing already-`done` legacy jobs (ocr_status NULL) are unaffected by the
  display path and are not pending, so the startup sweep skips them.
- After deploy, verify a freshly-stuck case clears: no remaining
  `status=done AND ocr_status=pending AND ocr_enqueued_at < now-20m`.
```
