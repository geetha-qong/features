# SESSION_STATE — 2026-06-24 (stale-detection + graph-tracer OOM fix; job 43 healed 7→207)

**Last updated:** 2026-06-24. **Active branch:** `fix/stale-gpu-detections-reinfer` HEAD `505bfb8` (committed, NOT pushed).
Base: `dev` `3a3d8f2`. **dev DATA already healed live; code NOT yet deployed.**
**Resumption rule:** read this file, then the last 5–8 FEATURES.md entries (newest #65).

**TL;DR:** Diagnosed why job 43's process graph showed only 7 nodes / 4 wrong edges. NOT a
model problem — the deliverables (API/`extractor.py`) found all 44 entities; the *graph* is
built from `Job.gpu_detections` (YOLO), and job 43 held **7 stale boxes from a dead old model**
(`valve_gen`/`valve_gl`). Live v1-11 finds **268**. Fixed the staleness (rerun now clears
`gpu_detections`; inference re-infers obsolete-taxonomy rows) AND a tracer OOM that the fix
exposed. Healed all 6 stale jobs on dev. See FEATURES #65.

---

## What shipped this session
- **FEATURES #65 (branch `fix/stale-gpu-detections-reinfer`, commit `505bfb8`).** 3 prod files + 2 test files + FEATURES.
  - `webapp/routers/jobs.py` `rerun_job`: clears `job.gpu_detections = None` (re-process now forces fresh inference — the user-facing root cause).
  - `webapp/pipeline_runner.py`: `_detections_are_stale()` + skip-guard re-infers when stored labels are outside `taxonomy.class_names()`. Legacy *schema* w/ current names is NOT stale (GPU worker writes that shape).
  - `webapp/graph/tracer.py`: `OpenCVLineTracer` downscales pages > `max_trace_dim`=4000 and scales coords back; per-component scan windowed to stat-bbox; frees intermediates. Fixes the OOM (int32 label map ~350MB @8000px + per-component full-array `np.where`).
  - Tests: `test_stale_detections.py` (6), `test_graph_tracer.py` (+2). **391 pass** (1 pre-existing `test_sheets_empty_when_no_tiles` failure, unrelated, confirmed on baseline).

## dev DATA healed (durable on EBS + graph DB; the in-container tracer patch is temporary)
Re-inferred + rebuilt graphs for all 6 stale jobs, no OOM:
**job 43: 7→207 nodes** (5 edges), 38→202 (11), 1→135 (89), 41→93 (147), 42→98 (69), 39→76 (80).
Heal used the fixed `tracer.py` hot-`docker cp`'d into the running `qong-web-1` (image unchanged —
a redeploy/restart reverts the in-container tracer, but the healed data persists).
Scratchpad scripts: `heal2.py` (job-43-first, detached, logs to /tmp/heal.log), `audit_dets.py`.

## NEXT STEP — deploy the recurrence fix
The dev DATA is fixed, but the recurrence prevention (rerun-clear + stale-reinfer) is only LIVE
after deploy. Per the PR workflow (S331): push branch → PR into `dev` → review → merge →
auto-deploy. Deploy rebuilds the image with the proper `tracer.py` (replacing the hot-patch).
**Watch the model-bake PAT** (`/may26aws/qong-shared/github-pat-model-release`) — it expired last
session; if the deploy build 401s, rotate it (see #64 note + reference_model_release_pat memory).

## Open follow-ups (NOT done)
- **Edge tracing weak on dense pages (priority).** Job 43 = 5 CV edges for 207 nodes and the
  LLM-fallback gate did NOT fire; lower-node jobs DID fall back. Downscaling may thin 1–2px pipe
  lines. Revisit `webapp/graph/fallback.py:should_use_fallback` for high node counts + edge recall.
- Graph extraction is ~110–155s/dense-page on the 3.8GB dev box (acceptable, not fast).
- **Self-Learning Phase 2 (the original ask) is still not started.** Key reframe from this session:
  YOLO is NOT the deliverables bottleneck (API finds entities); it only feeds overlay+graph. Design:
  `docs/superpowers/specs/2026-06-17-self-learning-loop-design.md`. NEVER auto-promote w/o eval gate.

## Gotchas / lessons
- **Graph nodes come from `gpu_detections` (YOLO), deliverables from `extractor.py` (API) — different pipelines.** A bad graph ≠ bad detection.
- **SSM serializes RunCommand + 24KB stdout cap + ~10min command ceiling.** Long jobs (graph build) MUST run detached (`docker exec -d ... > /tmp/x.log`) and be polled via separate cheap log reads; a synchronous SSM call times out.
- **Graph extraction OOMs on small boxes once detection counts are realistic.** The old 7-node graphs "worked" only because stale data was tiny.
- Run the full unit suite via `docker run --rm -v $(pwd):/app ... qong_poc-web:latest python3 -m pytest` — local host is Py3.9 and can't even collect routers (`int | None` in jobs.py:323).
