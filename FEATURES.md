# FEATURES — Append-only decision log

> Every meaningful feature, model swap, threshold change, architecture decision, bugfix, experiment, or business decision gets one entry here. **Newest first. Never edit past entries — mark superseded with `SUPERSEDED BY #NN`.** Recording the *reasoning* matters more than the choice.

**Why this file exists:** so we don't repeat ourselves. Every Claude Code session, every team standup, every "why did we decide that?" question — answer is here. Convention adopted from the QS-60 vision pack (see `docs/onboarding/`).

---

## [2026-06-30] #140 — Graph drawing UX: draw.io-style connections

**Type:** feature (Studio graph editing — frontend)
**Stage:** `webapp/frontend/src/studio/connect.ts` (new pure logic), `GraphLayer.tsx`, `PidCanvas.tsx`, `Studio.tsx`; tests `connect.test.ts` + `GraphLayer.test.tsx`.
**Status:** merged to dev 2026-06-30. Tasks 1–5 subagent-TDD + per-task review (clean); Task 6 (drag wiring) controller-written — tsc clean, 137 vitest pass, only the 6 pre-existing GraphLayer/EdgeMetadataDrawer failures. **Drag GESTURE verified on dev via Playwright (see SESSION_STATE).**
**Spec/plan:** `docs/superpowers/specs/2026-06-30-graph-drawing-ux-design.md`, `docs/superpowers/plans/2026-06-30-graph-drawing-ux.md`.

**Why:** team hand-correcting job 38 reported connecting nodes was painful: nodes didn't auto-connect (the old `nodeAtPoint` required an EXACT bbox hit and **skipped type-B nodes**, so a near-miss became a `freepoint` floating endpoint and the 33 unadopted nodes couldn't be connected at all); no draw.io-style connectors; existing lines blocked drawing.

**What:** draw.io-style press-drag-release (hover a node → cardinal anchor handles appear → drag → target snaps). All connect *logic* is in the pure, unit-tested `connect.ts`: `resolveEndpoint(pt, graph, natural, snapRadiusPx)` (bbox-contains → nearest node center within radius → none; returns type-B nodes, not skipped) + `connectEndpoints(src, tgt, deps)` (auto-adopts type-B endpoints via `#135` `adoptNode`, which now returns the new `entity_id`, then emits a **node-to-node** edge — no schema change, ports are visual only). `PidCanvas` only translates mouse events → page pixels. Edges go `pointer-events:none` in draw-edge mode (draw over lines); GraphLayer node onClick is suppressed in draw-edge so it can't fight the gesture. The freepoint fallback is removed (off-node gesture = no-op). The 2-click flow still works through the same routine.

**Decisions / notes:**
- **Node-to-node only** (entity→entity), ports visual — matches the graph-isomorphism metric (topology), zero schema change.
- **Auto-adopt-on-connect** — dragging to a type-B node adopts it (class from YOLO label) then connects, one gesture.
- **Hybrid execution:** subagents for the 5 unit-testable tasks; controller for the drag wiring + dev Playwright (jsdom can't exercise drag).
- **Follow-up minors:** untyped bbox tuple + untested multi-candidate/null-graph paths in `resolveEndpoint`; dead `[[0,0],[0,0]]` poly fallback in `connectEndpoints`; no live snap-target highlight during drag (anchors + release-snap suffice).

---

## [2026-06-30] #139 — Graph view merges tag overrides (edited tags persist on refresh)

**Type:** bugfix (graph read API)
**Stage:** `webapp/routers/graph.py` (`_merge_tag_overrides` + `get_job_graph`); tests `test_graph_tag_override_merge.py` + `test_node_corrections.py`.
**Status:** merged to dev 2026-06-30. 4 unit + 1 endpoint test; 30 sibling graph tests green.

**Why:** team reported (job 38) "edited tags revert on refresh." Root-caused on dev: **NO data loss** — tag edits write `EntityOverride(field_name="tag")` correctly (job 38: 31 overrides, 27 differing from the file value). But `get_job_graph` served node tags straight from `canonical_graph.json` and only merged `__rejected__` overrides — never `tag` — so the graph view re-showed the original OCR tag on refresh, while deliverables (which merge overrides) showed the new tag.

**What:** pure `_merge_tag_overrides(nodes, tag_by_eid)` + a query of `EntityOverride` rows where `field_name=="tag"`, applied to the final node set BEFORE any return path (Neo4j base_graph + JSON fallback). `new_value` is a JSON column → a tag override deserializes to a plain str. **Scoped to `tag` only** — `sub_class` deliberately NOT merged (the graph node's `class` is the YOLO detection label, distinct from entity sub_class).

---

## [2026-06-30] #138 — Resilient OCR-completion gate (card never traps at "Preparing")

**Type:** hardening (dashboard status gate)
**Stage:** `webapp/ocr_gate.py` (new — single source of gate logic), `webapp/models.py` + `webapp/database.py` (new nullable `Job.ocr_enqueued_at` column + migration), `webapp/routers/{api_v1,jobs,bbox_ocr}.py`, `webapp/pipeline_runner.py`, `webapp/main.py`; tests `tests/unit/{test_ocr_gate,test_ocr_enqueued_at_column,test_ocr_enqueue_stamps_timestamp,test_ocr_worker_failure,test_sweep_stale_ocr}.py` + `test_api_v1.py`.
**Status:** implemented on `feat/resilient-ocr-gate` (off dev), 6-task TDD (subagent-driven), OCR-gate suite green + opus whole-branch review **READY TO MERGE**; **PENDING dev deploy** (held to avoid a second interruption to the team's active manual-drawing — deploy when they pause).
**Spec/plan:** `docs/superpowers/specs/2026-06-30-resilient-ocr-gate-design.md`, `docs/superpowers/plans/2026-06-30-resilient-ocr-gate.md`.

**Why:** the dashboard holds a card at "Preparing" while extraction is `done` but background OCR is `ocr_status="pending"` (#132/#134 — intended: only show openable once all background work succeeds). But `run_detections_ocr_rq` had **no failure handling**: if `compute_tagged_detections` raised, or the cpu-worker was recreated mid-run (the documented "don't push while a job is processing" hazard — the dominant failure), or the queue never ran, the `ocr_status="done"` line was never reached. RQ recorded its own job failed, but nothing wrote that back to `Job.ocr_status` → the job sat `pending` **forever** and the card trapped at "Preparing" with no exit (real cases: jobs 14/28/29/32, manually cleared this session).

**What:** keep the hard gate, make it self-heal. Three layers share one constant `OCR_STALE_AFTER = timedelta(minutes=20)` and a new nullable `Job.ocr_enqueued_at` anchor:
- **Layer 1 — read-time backstop (pure):** `ocr_gate.effective_status(status, ocr_status, ocr_enqueued_at)` displays an overdue-pending job (`> 20 min`) as `"done"`. Wired into `api_list_jobs._effective_status` and `job_status` with **NO DB write** — these are `async def`, and a synchronous write would freeze the event loop (the prior 50s-page-load bug). Guarantees the card never *visually* traps the instant anyone loads the dashboard.
- **Layer 2 — worker retry + failure reflection:** enqueue with `rq.Retry(max=1)` (absorbs the transient deploy-kill — the common case); `run_detections_ocr_rq` wraps the compute in try/except, persists `ocr_status="done"` on failure, then **re-raises** (RQ still records the failure / retries). Releases the gate immediately on real failures.
- **Layer 3 — startup reconcile sweep:** `ocr_gate.sweep_stale_ocr(db)` flips `pending → done` for jobs stuck past 20 min (or with NULL timestamp — legacy), run once per deploy in `webapp/main.py` under the existing `_IS_STARTUP_LEADER` lock. Persists truth for jobs nobody is viewing and heals dead-worker pendings.

**Decisions / notes:**
- **Hard gate kept (not a soft "tags resolving…" gate)** — preserves the "only show when fully ready" UX the user asked for; the fix is resilience, not a redesign.
- **Released state is plain `"done"`** (graceful degradation — detections just lack OCR tag enrichment); no distinct `"ocr_failed"` state / badge (YAGNI).
- **Read path stays pure** (compute only) per the async-handler constraint; all *persistence* happens off the request path (worker + startup sweep).
- **NULL `ocr_enqueued_at`** = NOT overdue in the read path (held at Preparing) but IS swept on startup — a migration-transition state cleared by the first deploy.
- **20 min** sits above a normal multi-minute run AND a single 15-min RQ attempt, so a still-working job is never falsely released.
- **Carried minors (follow-up, none block):** unused `from datetime import timezone` in three test files; deprecated `Query.get()` in tests. **Out-of-scope pre-existing:** `test_api_v1.py::test_sheets_empty_when_no_tiles` fails only in a working copy with a populated `job_outputs/1/` (reads the real FS) — passes in a clean checkout at HEAD; test-isolation gap, not this branch.
- **Post-deploy verify:** no rows with `status='done' AND ocr_status='pending' AND (ocr_enqueued_at IS NULL OR ocr_enqueued_at < now-20m)` remain.

---

## [2026-06-30] #137 — Enlarged transparent hit target for graph nodes (type-B nodes clickable on large drawings)

**Type:** bugfix (Studio graph canvas)
**Stage:** `webapp/frontend/src/studio/GraphLayer.tsx` + `webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx`.
**Status:** **SHIPPED to dev 2026-06-30** (branch `fix/graph-node-hit-target` → dev FF, bundle `index-D-Qvb1Fu.js`); verified on dev with a real `page.mouse.click` → adopt panel "Confirm as PUMP/DWG PUMP" opened.

**Why:** user reported (job 58) "I see dotted boxes but clicking them gives no edit option" and asked whether to **delete or reprocess all jobs**. Investigated on dev — **neither**: not a data bug. Job 58's graph has 303 valid type-B nodes (all with bbox + resolvable class) and clicking the exact type-B node opened the #135 adopt flow correctly. Root cause is **render hit-target size**: `GraphLayer` node radius is SVG-user-space (`nodeRadius = sw*2.2`, `sw = natural.w/1200`), so on a large drawing (~8000px page) each node collapses to **~2.7px on screen** at fit-zoom → effectively unclickable by hand (the documented "bbox click reliability at default zoom" gotcha). The visible "dotted boxes" the user clicks are the 683 dashed detection-overlay rects (select layer), which by design show an info panel, not adopt.

**What:** a transparent enlarged hit circle (`hitRadius = max(nodeRadius, sw*12)`) behind the visible dot; the visible dot size is unchanged. Because `sw = natural.w/1200`, an sw-relative radius **cancels `natural.w`** → the hit area is a roughly **constant on-screen size across all jobs** regardless of page resolution (~14.7px diameter on a ~900px-wide canvas, verified on dev). Confound to avoid in testing: `isUnmatched = floating || entity_id===null`, but adopt routing fires ONLY on `entity_id===null` — ~20 job-58 nodes are floating-but-have-entity_id and correctly route to select; test by clicking a node KNOWN to have `entity_id===null` (fetch `/api/v1/jobs/{id}/graph`). +1 vitest (GraphLayer test file has 5 PRE-EXISTING failures from a `cy/ph<0.08` margin-guard excluding old fixtures — not ours).

**Decisions / notes:**
- **One frontend fix covers EVERY job — no reprocessing, no deletion** (reprocessing regenerates identical coords → identical 2.7px dots). Immediate workaround if not deployed: zoom in (nodes are SVG-space, grow with zoom).
- Deployed standalone (separate from #138) to unblock the team's active manual-drawing on jobs 38/58.

---

## [2026-06-30] #136 — Cross-tile detection de-duplication + 1:1 entity matching

**Type:** feature (detection layer / entity matching)
**Stage:** `webapp/graph/detection_dedup.py` (new), `webapp/graph/page_geometry.py` (new), `webapp/routers/bbox_ocr.py`, `webapp/routers/api_v1.py`, `webapp/graph/loader.py`; tests `tests/unit/{test_detection_dedup,test_bbox_ocr_dedup,test_graph_loader_dedup}.py` + `test_api_v1.py`.
**Status:** implemented on `feat/detection-dedup` (off dev); 45 feature tests + full suite green (same 11 pre-existing failures as dev); **pending dev deploy + measured validation**.
**Spec/plan:** `docs/superpowers/specs/2026-06-30-cross-tile-detection-dedup-design.md`, `docs/superpowers/plans/2026-06-30-cross-tile-detection-dedup.md`.

**Why:** "Click one element → N highlight." Root cause (measured): pages are tiled 3×3 with 20% overlap and `gpu_detections` is never de-duplicated across overlapping tiles, so a glyph on a tile seam is detected up to 4× (4-tile corner). **39% of all detections (972/2490 across 7 jobs) are cross-tile duplicates.** The OCR matcher (`bbox_ocr` `tag_to_entity.get()` with no consume) then binds every duplicate to one entity (job 38: `61-HS-00471` → 9 detections). Conflated in that: phantom tile-copies (the bulk) AND genuinely-distinct glyphs sharing a tag — a BPCS circle + SIS diamond, which **are two separate entities** per domain.

**What:**
- New pure `detection_dedup.dedupe_detections_page_space(dets, tile_offsets, iou=0.5)` — page-space greedy NMS per class (highest-confidence survivor; different classes never suppress each other, so circle+diamond both survive); reuses `orphan_dedup.bbox_iou`. Non-destructive (drops suppressed copies, never mutates a bbox; `gpu_detections` on disk untouched).
- New `detection_dedup.enforce_one_to_one(dets)` — each entity_id binds to one detection; extras unmatched (`entity_id=None`, `entity_tag` retained) → surface as adoptable type-B nodes (#135). This delivers BPCS/SIS as **two entities**: the circle claims `61-HS-00471`, the diamond is adopted as its own SIS entity.
- New shared `page_geometry.page_dims_for_job` (reads `canonical_graph.json` dims). De-dup applied **read-time** (no re-inference; fixes all existing jobs) at three consumers, gated on page-dims: `bbox_ocr.compute_tagged_detections` (before matching → also cuts ~39% of OCR calls), `api_v1.api_job_detections`, and `loader.build_job_input` (before page translation).

**Decisions / notes:**
- **Read-time, non-destructive** (chosen over a write-time `gpu_detections` rewrite) so all 56 jobs are fixed with no GPU re-run.
- **1:1 matching is safe only because de-dup runs first** (without it, 1:1 would wrongly split phantom same-class copies). Bonus: 1:1 consume also stops the stray valve-proximity bleed from double-binding.
- **Out of scope (tracked):** the `_run_valve_ocr` 600px-context-window proximity bleed (only 2 cases across all jobs); auto-creating the second (SIS) entity without a user adopt (the #135 path covers it).
- **Follow-up minors (final-review log):** in-function imports in `bbox_ocr`/`loader` (verify no circular import before moving to module top); narrow `page_geometry` bare `except`; one loader test degrades to a vacuous assert when cv2 is absent (sibling test covers it via skip).

---

## [2026-06-30] #135 — Type-B graph nodes adoptable as full first-class entities

**Type:** feature (Studio graph editing + deliverables)
**Stage:** `webapp/graph/orphan_dedup.py` (new), `webapp/routers/annotations.py` (server-side resolver), `webapp/routers/graph.py`, `webapp/scripts/freeze_graph_gt.py`, `webapp/frontend/src/studio/{GraphLayer,PidCanvas,PropertiesPanel,Studio}.tsx`; tests in `tests/unit/{test_orphan_dedup,test_graph_orphan_dedup_merge,test_freeze_graph_gt,test_adopt_node_e2e,test_detection_claim_resolve}.py` + frontend vitest. `resolveDetectionIndex.ts` removed (superseded by server-side resolution).
**Status:** implemented on branch `feat/graph-typeb-first-class` (off dev), all tests green; pending PR + manual verify on job 38.
**Spec/plan:** `docs/superpowers/specs/2026-06-30-graph-typeb-first-class-entities-design.md`, `docs/superpowers/plans/2026-06-30-graph-typeb-first-class.md`.

**Why:** "Type-B" graph nodes — YOLO detections the canonical matcher never bound to an `entity_id` — rendered in the graph but couldn't be selected, connected, or removed, yet still landed in the frozen GT. On job 38 that's 33/91 nodes (36%, mostly valves), blocking the #128 ground-truth workflow (can't draw the true pipes to 36% of nodes). Re-marking with Mark-Symbol duplicated them (`onDropMark` hardcoded `linked_detection_index: null`) — the "USER-TT junk nodes" seen previously.

**What:** A user adopts a type-B node via a one-click **"Confirm as &lt;class&gt;"** in `PropertiesPanel` (class pre-filled from the YOLO label). Adoption creates a *claiming* `UserAnnotation` with `linked_detection_index` resolved **server-side** from the page-pixel bbox (tile-offset-corrected via `canonical_graph.json` page dims + `compute_tile_offsets` → `to_page_pixel_detections`), so the correct detection is claimed regardless of which tile it lives in — a client-side match against tile-local coords silently failed for every non-top-left tile, producing spurious `ModelCorrection('add')` rows. Claimed detection → `user_confirmed` (correct training signal); no overlapping detection → `linked_detection_index` stays None → `user_added` + `ModelCorrection('add')` (correct for genuinely new marks). Bbox is preserved — never `(0,0,0,0)`. The already-existing `_sync_annotation_to_canonical` mirrors the **tagged** annotation into `canonical.json` → element list + valve list + instrument index + datasheets. Graph connect/reject work for free once an `entity_id` exists. **No-duplicate comes from the graph dedup** (shared `orphan_dedup.superseded_auto_ids`, bbox IoU ≥ 0.5) which drops the now-superseded orphan auto-node in **both** the live `GET /graph` merge and the freeze builder — not from `linked_detection_index`. Mark-Symbol `onDropMark` passes `linked_detection_index: null` to the same server-side resolver.

**Decisions / notes:**
- **Supersedes the rejected `feature/orphan-promotion` branch** (auto-promotes ALL OCR-tagged orphans into canonical.json with bbox=0): we chose per-node user-vetted adoption (lower false-positive risk, preserves bbox, no second canonical-mutation path). That branch is to be closed.
- **Reuses, not rebuilds:** the deliverable half (`_sync_annotation_to_canonical`, `_entity_dict_from_annotation`, `_detection_label_to_class`, admin DB index sync) already existed (2026-06-17 rule); this feature's genuinely new code is the graph-side orphan dedup + the adopt UI + the server-side resolver.
- **Non-goals (v1):** bulk/auto-adopt; OCR tag re-resolution beyond the single at-adopt read.
- **Representation note:** `UserAnnotation.entity_id` is dashless hex32; `CanonicalEntity.entity_id` is a dashed UUID — the dedup is bbox-based so it's unaffected; the e2e test normalizes via `str(UUID(...))`.
- **Tests:** backend tests cover the non-zero-tile-offset claim path (test_detection_claim_resolve.py), the existing e2e (explicit index still honoured), and all prior dedup/freeze/canonical-sync tests. Frontend vitest + `tsc --noEmit` clean. The 11 pre-existing full-suite failures (opencv-missing `test_graph_tracer`, `test_taxonomy*`, deliverables emitter) are present identically on `origin/dev` — not introduced here.
- **Follow-ups (separate branches):** (1) remove inert Neo4j code; (2) fix the 6 pre-existing `GraphLayer.test.tsx`/`EdgeMetadataDrawer` frontend test failures (component/test drift on dev, unrelated to this feature).

---

## [2026-06-30] #134 — Fix: OCR Done-gate masked ALL legacy jobs as "processing" (regression from #132)

**Type:** bugfix (dashboard / regression)
**Stage:** `webapp/routers/api_v1.py` (`/api/v1/jobs` list), `webapp/routers/jobs.py` (`/jobs/{id}/status`), `tests/unit/test_api_v1.py`
**Status:** shipped to dev (fast-forward merge `fix/ocr-done-gate-null` → dev, container `2026-06-30T02:01Z`). Verified live: dashboard chips Preparing 0 / Done 66 (was Preparing 67 / Done 0).

**Symptom:** user reported "dev is loading infinite." The dashboard rendered fine but **every one of the 67 projects showed "Preparing" / "Still extracting — opens when ready", "Currently extracting: 67 / Done: 0"** — none openable. Reads as a perpetually-loading workspace.

**Root cause:** #132 added the `ocr_status` column (NULL → pending → done) and gated the dashboard "Done" on it. Both the list endpoint (#132's follow-up da76092) and the single-job status endpoint used `if job.status == "done" and job.ocr_status != "done": return "processing"`. The column is **NULL for all 66 pre-existing done jobs** (the per-pipeline OCR enqueue only fires on *new* runs; #132's `ocr_status='done'` backfill ran on local dev only, never on the dev EC2). `NULL != "done"` is true → every legacy done job flipped to "processing". Classic gate-on-a-freshly-added-nullable-column regression.

**Fix:** gate on `ocr_status == "pending"` instead of `!= "done"`. Hold a job at "processing" only while OCR is *actively* running (the #132 intent for fresh uploads); treat NULL (OCR never enqueued / legacy / non-OCR pipeline) as done. No DB backfill needed — the NULL rows resolve correctly. 3 regression tests pin NULL→done, pending→processing, done→done.

**Notes / gotchas found:**
- **Deploy-health (verified after this fix — an earlier "stale image" worry was a FALSE ALARM):** I first thought the dev image was stale because `Job.__table__.columns` lacked heartbeat/stage/killer — but those columns live on the separate **`JobRun`** (`job_runs`) table, never on `Job`. A full probe confirmed dev is healthy: all 20 model tables present in the DB (`run_migrations()` fully applied), `job_runs` has `last_heartbeat_at`/`current_stage`/`killer`, and the #133 model runtime-mount works end-to-end (`/app/models/v1-11.onnx`, 44.7 MB, loads via `inference._get_session()`). Lesson: introspect the right table before declaring deploy drift.
- Stuck job 67 (status=processing) was terminated to `failed` by the cpu-worker recreate on deploy (user-authorized fast-track).

---

## [2026-06-29] #133 — YOLO model mounted at runtime, not baked into the image

**Type:** infra / deploy (build pipeline)
**Stage:** `Dockerfile`, `docker-compose.yml`, `scripts/fetch_model.sh` (new). On branch `infra/model-runtime-mount`.
**Status:** implemented + compose-config validated. Dev rollout = seed `MODEL_DIR` + set `.env.dev` before merge (see below).

**Why:** The model-bake `RUN` sat **after `COPY . .`** in the Dockerfile, so Docker's layer cache invalidated it on **every** code change → the 44 MB `v1-11.onnx` was re-downloaded from GitHub releases on **every deploy**. Worse, that download used the model-release PAT (`/may26aws/qong-shared/github-pat-model-release`); when it expired, the model-bake step 401'd → image never rebuilt → **every dev deploy silently kept serving the old container** (hit 2026-06-29: #22 and #24 both failed to deploy; root-caused to this). The model only changes on a new release, so baking it per build is wasteful and fragile.

**What:** The image no longer downloads the model. `Dockerfile` model-bake `RUN` (+ the `--mount=type=secret,id=github_pat`) removed → just `mkdir -p /app/models`. `docker-compose.yml` removes the `github_pat` build secret from `web`/`cpu-worker` (and the now-unused top-level `secrets:` block) and bind-mounts the model **read-only at runtime**: `${MODEL_DIR:-./models}:/app/models:ro`. The webapp loads `/app/models/v1-11.onnx` at runtime (`webapp/inference.py`); an empty mount only raises `InferenceError` when inference is actually requested — the image builds + serves fine. New `scripts/fetch_model.sh` downloads + sha-verifies the asset into `MODEL_DIR` (PAT from `$GITHUB_PAT` → SSM → public, idempotent) — **the only place the PAT is used now**, run once per model release.

**Consequence:** code deploys no longer touch GitHub releases or the PAT → a PAT expiry can never again break a code deploy. **Supersedes the model-bake half of #28/#41.** The CLAUDE.md "model-release PAT expiry silently breaks dev deploys" gotcha is resolved for code deploys (still applies to `fetch_model.sh` at release time). `deploy-dev.yml`'s PAT-from-SSM step is now a vestigial no-op (build ignores it) — optional cleanup later.

**Dev rollout (before merging):** set `MODEL_DIR=/mnt/qong-data/models` in `/opt/qong/.env.dev` (+ SSM) and seed `/mnt/qong-data/models/v1-11.onnx` (copy from the current running container or `scripts/fetch_model.sh`). Otherwise the post-merge deploy mounts an empty `./models` and inference breaks. Local dev: defaults to `./models` (no v1-11.onnx ⇒ InferenceError on inference only — same as the old no-PAT local build).

---

## [2026-06-29] #132 — Dashboard "Done" only after OCR; graph pill removed

**Type:** UX + backend
**Stage:** `webapp/models.py`, `webapp/database.py`, `webapp/routers/bbox_ocr.py`, `webapp/routers/jobs.py`, `webapp/frontend/src/dashboard/ProjectCard.tsx`
**Status:** implemented, local dev

**Why:** Jobs were flipping to "Done" on the dashboard as soon as extraction + graph completed, while OCR was still running (~3 min). Users opened the Studio immediately, saw FIFO-matched (wrong) detections, and thought OCR was broken. The "Graph: Building…" pill was internal noise that confused users and didn't map to anything they needed to act on.

**What:**
- Added `ocr_status` column to `Job` (`None` → `pending` → `done`), migrated via `new_columns` in `database.py`.
- `_enqueue_detections_ocr` sets `ocr_status='pending'`; `run_detections_ocr_rq` sets `ocr_status='done'` on completion.
- Jobs status endpoint now returns `effective_status='processing'` (→ card shows "Preparing") when `status=done` but `ocr_status != 'done'`. Card only flips to "Done" after OCR finishes.
- Removed `Graph: Building / Pending / Failed` pill from `ProjectCard.tsx` entirely.
- Backfilled `ocr_status='done'` for 19 existing jobs that already had completed OCR cache.

---

## [2026-06-29] #131 — OCR correctness fixes: re-attach, max_tokens, entity_tag priority, BPCS/SIS prompts

**Type:** bugfix (OCR / instrument extraction)
**Stage:** `webapp/routers/bbox_ocr.py`, `webapp/routers/api_v1.py`, `extractor.py`, `instrument_prompts.py`
**Status:** implemented, local dev

**Why:** Multiple compounding issues caused instruments to show wrong or missing sidebar data after hard refresh or new uploads:

1. **FIFO re-attach regression** (`bbox_ocr.py`): a previous fix added re-attach code that called `_attach_entity_ids()` on every cache serve. That function resets ALL entity_ids to `None` then re-runs FIFO — FIFO could steal an entity before a tagged detection claimed it, wiping correct matches from the cache.
2. **max_tokens=2048 truncation** (`extractor.py`): tiles with 20+ instruments generated JSON longer than 2048 tokens; response was cut mid-array, `extract_json_array` returned `[]` silently → 0 instruments extracted from that tile.
3. **entity_tag not prioritised** (`api_v1.py`): `_attach_entity_ids` checked `valve_tag`, `tag`, `label` but not `entity_tag` (set by instrument circle OCR — the most reliable source). OCR-resolved tags were ignored during entity matching.
4. **BPCS/SIS instruments not extracted** (`instrument_prompts.py`): double-circle (BPCS) and diamond-circle (SIS) instrument symbols had no explicit mention in the extraction prompt, so the Vision model skipped them.

**Fixes:**
- `bbox_ocr.py` re-attach: now only fills `entity_id` for detections with `entity_tag` set but `entity_id=None` (true gaps). Existing correct matches are never touched. No FIFO collisions.
- `extractor.py`: `max_tokens` in `extract_instruments()` raised from 2048 → 8192.
- `api_v1.py`: `entity_tag` added as first candidate in `_attach_entity_ids` tag-equality loop.
- `instrument_prompts.py`: added `BPCS AND SIS INSTRUMENTS — NEVER SKIP` section with explicit double-circle and diamond-circle symbol descriptions; added "BPCS"/"SIS" to location enum and functional symbol → location mapping.

---

## [2026-06-29] #130 — Graph GT-freeze tool + node-reject auto-edge omission fix

**Type:** tooling + bugfix (graph)
**Stage:** `webapp/scripts/freeze_graph_gt.py` (new), `webapp/routers/graph.py`, `tests/unit/test_freeze_graph_gt.py` (new)
**Status:** implemented + unit-tested + freeze→score loop smoke-tested on local job 2. On branch `feat/graph-gt-freeze`.

**Why:** Unblocks ground-truth scoring (the gate for validating #128). Now that a human can hand-correct a job's graph in Studio (#129 — add/remove nodes, draw edges), we need to snapshot the corrected graph as the frozen GT the scorer reads.

**What:** `python -m webapp.scripts.freeze_graph_gt --job-id N [--out PATH] [--status verified]` writes the **merged** graph (auto extraction + user node/edge corrections, reusing the exact `webapp.routers.graph` helpers) to `tests/graph_ground_truth/job_N.json`. Unlike `GET /graph` (which returns rejected nodes flagged for UI ghosting), the GT is the **clean truth**: rejected nodes + edges touching them are dropped; user-added nodes/edges included. `score_graph` reads it unchanged. Smoke-tested: freeze job 2 → score extracted vs GT → node/edge F1 1.0, isomorphic (perfect self-score, no corrections).

**Bug fixed (from #129):** node reject only dropped **user** edges, not **auto/detected** edges — auto edges key on graph `node_id` (`n_NNN`), not `entity_id`, so `_edge_touches_rejected` (keyed on entity_id) never matched them → rejecting a detected node left **dangling auto-edges** to a ghosted node. Fix: compute `rejected_node_ids` (map rejected entity_ids → their node_ids) and omit edges by **both** id spaces (`reject_keys = rejected_ids | rejected_node_ids`) in `get_job_graph` (JSON + Neo4j paths) and the freeze tool. Covered by `test_freeze_graph_gt.py::test_rejected_node_dropped_with_its_auto_edge`.

**Next:** a human hand-corrects a real job's graph in Studio → freeze it → use it to validate/tune #128 (`max_factor`) before merging #128.

---

## [2026-06-28] #129 — Studio: real unified node corrections (add / remove graph nodes)

**Type:** feature (Studio editing / graph + deliverables)
**Stage:** `webapp/routers/graph.py`, `webapp/deliverables/overrides.py`, `webapp/frontend/src/studio/*`
**Status:** implemented + tested on branch `feature/studio-node-corrections` (commit `51c5b86`). Brainstormed design + multi-agent build (backend + frontend in parallel) + adversarial review + live Playwright e2e. Spec: `docs/superpowers/specs/2026-06-28-studio-node-corrections-design.md`.

**Why:** Users could correct **edges** but not **nodes** — "Mark Symbol" created a deliverable annotation that never became a graph node (not connectable), and there was no way to remove a false-positive YOLO node. Graph correctness (isomorphism) needs the right node-set AND edges, so this blocked ground-truth and undermined the digital twin. (Empirically confirmed 2026-06-28: `POST /annotations` returned 201 but the node was absent from `GET /graph`.)

**What (Approach A — read-time merge, reuse stores, `entity_id` is the spine, no new tables):**
- **Add** = existing `UserAnnotation` (Mark Symbol). `GET /graph` now tags nodes `source=auto|user`, merges annotation rows as connectable graph nodes (deduped against canonical entity_ids), and the Mark-Symbol flow auto-OCRs the dropped box to prefill the tag.
- **Remove** = soft **reject** via `EntityOverride field_name="__rejected__"` (reversible). `GET /graph` returns rejected nodes flagged (UI ghosts + Restore) and omits edges touching them (JSON + Neo4j paths). `deliverables/overrides.py` drops `__rejected__` entities (and never applies the flag as a field) → one change propagates removal to valve list / instrument index / datasheets / bulk review. New idempotent `POST`/`DELETE /jobs/{id}/nodes/{entity_id}/reject` (IDOR-scoped).
- **UX:** Properties-panel **Remove** (widened to any real node) routes hard-delete (user-added) vs soft-reject (detected) with an **Undo** toast; ghosted nodes show **Restore**. Connect-with-direction already worked.

**Verified:** 10 backend unit tests + 3 vitest; live Playwright e2e on job 2 — add → connect (directed) → reject (graph rejected + valve list 26→25) → undo (back to 26). Review fixed 3 issues (annotation↔canonical dedup, Neo4j edge omission, prototype-id guard); no criticals; IDOR mitigated.

**Out of scope (follow-ups):** GT-freeze (snapshot merged graph → `tests/graph_ground_truth/job_N.json`) + pointing the scorer at the merged graph; best-effort reject→YOLO training signal.

---

## [2026-06-28] #127 — Studio datasheet drawer: restore compact multi-column form (regression from #64)

**Type:** UX fix (frontend / regression)
**Stage:** frontend (Studio DatasheetDrawer + shared `sectioned.tsx` + bulk-review `DatasheetPanel`)
**Status:** implemented on `dev` working tree (not yet committed/deployed); `tsc --noEmit` + `vite build` + datasheet vitest all clean. **Live-verified** in local Studio (job 2, instrument `62-BF-151031`): Instrument Datasheet drawer now packs 2–3 inputs/row (Identity 13 fields → 7 rows; Operating & Design 14 → 7; Commercial 15 → 7 with By/Chk/Appr/Date 4-across), Valve List path 13 fields → 6 rows.

**Why:** User reported that after the last 2–3 PR merges the datasheet drawer renders every field as a **one-per-row long list** instead of the compact multi-input-per-row form from the v3 design (`design/qong-studio-v3/project/datasheet.jsx`).

**Root cause:** PR #64 (`7f3d789`, `sectioned.tsx`) overrode the existing CSS grid. `studio.css` `.ds-fields` defines a deliberate **4-column dense grid** (`repeat(4, minmax(0,1fr))` + `grid-auto-flow: row dense`) driven by per-field width hints (`.span-xs/sm/md/full` = 1/2/3/4 cols). The refactor (a) replaced that with an inline `gridTemplateColumns: repeat(auto-fill, minmax(180px,1fr))` (~3 equal tracks in the 720px drawer) and (b) hardcoded `span-sm` (= `grid-column: span 2`) on **every** field. 3 tracks × span-2-each → only one field fits per row → the long list. `EntityFieldList` (valve/index path in `DatasheetDrawer.tsx`) had the analogous bug: inline `repeat(4,1fr)` + every field `span-sm` → stuck at 2/row, width hints ignored.

**What:** Restored the v3 behaviour. (1) Removed the inline `gridTemplateColumns` overrides on all three `.ds-fields` containers so the CSS 4-col dense grid applies again. (2) Added `spanForField(header)` in `sectioned.tsx` — a label-driven heuristic that infers a width hint the backend schemas don't carry (long free-text like Description/Remarks/Narrative → `full`; medium descriptors Service/Range/Location → `md`; short identifiers Tag/Size/Rev/Loop/Type/By/Chk/… or ≤4 chars → `xs`; default `sm`). (3) Threaded a `span?: FieldSpan` prop through `EditableCell`/`ReadOnlyCell` (default `"sm"`), applied as `span-${span}`. (4) **Removed the redundant absolute `.ds-hint "Manual"`** in `EditableCell` — it was `position:absolute; right:12px; top:50%` (CSS uppercased it to "MANUAL"), so in the now-narrower columns it overlapped the input value AND duplicated the `.ds-source "MANUAL"` label badge that #64 added. Kept the coherent label-badge set (P&ID / EDITED / MANUAL). Both surfaces benefit: drawer (720px) packs 2–4 inputs/row; bulk-review side panel uses `.ds-wide` (560px) so the same grid stays readable.

**Lesson (gotcha):** the canonical datasheet grid is the CSS `.ds-fields` 4-col dense grid + `.span-*` width hints (studio.css ~L1770). Don't re-define the grid inline in components, and don't hardcode one span on every field — derive it (or pass it through) so the form stays compact. Backend `DatasheetFieldOut`/`EntityColumn` carry **no** width hint; `spanForField` is the single client-side source for it.

---

## [2026-06-27] #126 — Studio: loader on canvas load (kill the "sample PID" flash)

**Type:** UX fix
**Stage:** frontend (Studio canvas)
**Status:** shipped (direct to `dev`)

**Why:** On refresh, the Studio canvas showed the legacy hardcoded prototype P&ID (`PidCanvas.tsx` `useProto` branch — the `EDGES`/`ELEMENTS` demo drawing) for ~2 s before the real page render loaded, because while `sheets` are still being fetched `pageFullUrl`/`tileImageUrl` are null → `useProto` is true. Users read this demo drawing as a real (wrong) drawing momentarily — confusing.

**What:** Added a `loading` prop to `PidCanvas` (fed by a new `sheetsLoading` state in `Studio.tsx`, true until the sheets fetch settles via `.finally`). The `useProto` branch now renders a centered spinner + "Loading drawing…" (`.canvas-loader`, reuses the existing `spin` keyframe, theme-aware via `--fg`/`--border` tokens, respects `prefers-reduced-motion`) while loading; the prototype SVG only renders for a genuinely empty job once loading has settled. Real-data path (`useFullPage`) is untouched; its in-image shimmer (#125) still covers the image-decode phase. So the load sequence is now: spinner (sheets) → shimmer (image) → real P&ID + detections.

---

## [2026-06-27] #125 — Studio canvas blank-overlay fix: cached-image `onLoad` race (regression from #5)

**Type:** bugfix (frontend / regression)
**Stage:** frontend (Studio canvas)
**Status:** shipped (direct to `dev` — user-authorized critical hotfix, 2-approval gate waived for this one)

**Why:** Users reported the Studio "felt slow" / some jobs "wouldn't load" (concretely: job 63 on dev). Investigation ruled out everything else first — backend endpoints 6–25 ms server-side (measured inside the EC2, bypassing nginx; #120/#122 still holds), hover/zoom 60–118 fps in-browser, image decode ~46 ms. The real symptom: on revisit, the page **image** rendered but the **detection overlay showed 0 of 136 detections** — the loading shimmer stayed up (`imgLoaded === false`) even though the cached page image was `complete`.

**Root cause:** PR #5 (`1a1baa6`, feature/graph) added an `imgLoaded` fade-in state to `PidCanvas.tsx` and gated the detection overlay on it (`{imgLoaded && natural && (…overlay…)}`), with `imgLoaded`/`natural` set **only inside the `<img onLoad>` handler**. The page-full image is served `Cache-Control: immutable`, so on every revisit it's served from cache and is already `complete` before React attaches `onLoad` → the handler never fires → `imgLoaded` stays false → overlay never renders. Intermittent by cache state + timing (job 64 happened to load cold; job 63 hit the cached path), which is why it read as "slow/flaky" rather than a hard error. Backend was never involved — the graph/detections data was present and fast.

**What:** In both `PidCanvas.tsx` overlay components (`PageWithOverlays` full-page + `TileWithOverlay` tile mode) added a post-commit `useEffect` that re-syncs from the element when the cached `onLoad` is missed: `if (!imgLoaded && img.complete && img.naturalWidth > 0) { setNatural(...); onNaturalSize?.(...); setImgLoaded(true); }`, keyed on the image src (+ `imgLoaded`/`natural` guard so it's idempotent and can't loop even if the parent passes a non-memoized `onNaturalSize`). `onLoad` still covers the cold network path. Verified: `tsc --noEmit` clean, `vite build` clean, change isolated to `PidCanvas.tsx`.

**Lesson (gotcha):** any state set *only* in an `<img onLoad>` is unreliable for cached/`immutable` images — always pair it with a `complete && naturalWidth` check in an effect. This is now in CLAUDE.md.

---

## [2026-06-27] #124 — Vendor-match dropdown: server-side proxy (key out of the browser) + dev env

**Type:** bugfix / security
**Stage:** webapp, frontend, deployment
**Status:** shipped (branch `feat/vendor-match-proxy`, PR → `dev`)

**Why:** The Studio "Select Vendor" dropdown (`BulkReviewScreen.tsx`) was dead on dev — it fetched a **hardcoded, expired ngrok URL** (`dill-payday-chirping.ngrok-free.dev`) with a **placeholder key** (`qong-local-dev-key-…`). Two problems: (1) wrong URL/key → silently no data; (2) the pattern itself ships the vendor API key in the SPA bundle (the live `qong_8653…` key was hardcoded in the frontend on the `line_list` branch — a real leak). The backend's own `VENDOR_MATCH_API_URL`/`VENDOR_MATCH_API_KEY` were also empty on dev, so pipeline-time vendor fields never populated.

**What:**
- `webapp/routers/vendor.py` (new) — `POST /api/v1/vendor-match` proxy (cookie-auth via `get_current_user`). Calls the vendor API **server-side** with the env key and returns the raw `{success, instType, data:[…]}` so the dropdown lists every product. 503 if unconfigured, 502 on upstream failure, 422 on blank instType.
- `webapp/deliverables/vendor_match_client.py` — added `fetch_vendor_catalog(inst_type)` (full product list, raw response) + `vendor_api_configured()`. Existing `fetch_vendor_fields` (pipeline best-match) unchanged.
- `webapp/frontend/src/studio/bulk-review/BulkReviewScreen.tsx` — dropdown now fetches the same-origin `/api/v1/vendor-match` with **no URL and no key in the browser**. The vendor URL is purely an env value now, so prod is a one-line `.env.prod` change (no code edit).
- `webapp/main.py` — wired the vendor router.
- Dev config: `VENDOR_MATCH_API_URL=https://dev-vendors.qongsystems.com` + `VENDOR_MATCH_API_KEY=qong_8653…` set in `/opt/qong/.env.dev` and SSM (`/may26aws/qong-dev/vendor-match-{url,key}`). This fixes BOTH the dropdown (via proxy) and pipeline-time vendor fields.
- Tests: `tests/unit/test_vendor_match_proxy.py` (6) — configured-guard + route 422/503/502/success.

**Notes:** the vendor API uses `X-API-KEY` (POST `/api/qong-instrument`); the returned `datasheet_url` PDF is public (no key), so the "view datasheet" button works as-is. **The `qong_8653…` key is the same one exposed in `line_list` git history — rotate it** (then update SSM + `.env.dev`/`.env.prod`).

---

## [2026-06-27] #123 — Graph-only backfill script + job-38 finding

**Type:** tooling / graph
**Stage:** webapp, graph
**Status:** shipped (branch `feat/graph-backfill`, PR → `dev`); applied to job 38

**Why:** Roadmap item 1 — backfill the other "healed" jobs (1/38/39/41/42) through the #66 graph pipeline (entity node-dedup + chunked LLM edge fallback) so more real graphs exist to measure. The only existing tool, `backfill_gpu_detections`, re-runs YOLO inference; there was **no graph-only rebuild**. The obvious path (`POST /rerun`) re-runs the paid deliverables pipeline and would change deliverables — and violates the "never auto-rerun jobs" policy. The graph is YOLO-derived and orthogonal to deliverables (CLAUDE.md "Third path"), so a graph-only rebuild is the right, cheap, deliverable-safe tool.

**What:** `webapp/scripts/backfill_graph.py` — per job: re-run OpenCV line detection → `extract_graph(..., tile_local_detections=True)` → `sync_graph_to_db` (replace semantics), **no** deliverable re-run, **no** re-inference. A pure `_backfill_decision()` guard REFUSES missing / no-detections / **stale** detections (must run `backfill_gpu_detections` first), so it can never silently re-infer. `--job-id` (repeatable) + `--dry-run`. Tests: `tests/unit/test_backfill_graph.py` (8, guard logic).

**Finding (the important part):** a read-only probe showed the 5 jobs are NOT all broken — 41/42 already show dedup + healthy edge density (already-#66), 1/39 look acceptable; **only job 38 was clearly broken (202 nodes / 11 edges**, the pre-#66 sparse-edge symptom). None are stale. Ran the backfill on **job 38 only** (rebuilding already-healthy graphs is risky: the LLM fallback is non-deterministic and we have no frozen ground truth to *measure* improvement yet — that's roadmap item 2). Result: **202/11 → 91/20** (`fallback_used=True`). Node dedup worked (202→91, phantom tile-overlap duplicates collapsed) and the chunked fallback fired, but **20 edges on 91 nodes is still sparse** vs healed job 43 (128/155). So job 38 is *more correct* than before but not *healed* — its under-connection is deeper than a backfill can fix, pointing at **cross-tile pipe stitching (roadmap item 2)** and/or line-detection quality on this drawing. Left 1/39/41/42 untouched.

**Notes:** the script was `docker cp`'d into the dev cpu-worker for the job-38 run; a `--build` (or this PR merging + deploy) is needed for it to live in the image. Decision to NOT mass-rebuild healthy graphs is deliberate — revisit once roadmap item 2 gives a measured isomorphism signal.

---

## [2026-06-27] #122 — Background OCR for detections-tagged (instant GET + cpu-worker pipeline)

**Type:** performance / architecture
**Stage:** webapp, frontend
**Status:** shipped (branch `feat/web-concurrency-bg-ocr`, PR → `dev`)

**Why:** #120 moved the OCR off the event loop (→ threadpool), which fixed the *app-wide* freeze. But the work itself (one Vision call per instrument circle + one per tile) still ran **inline on the GET**, so a job's first load blocked *that* request for ~40 API calls, and a burst of job-page loads could still saturate the threadpool. The follow-up flagged in #120's Notes.

**What:**
- `webapp/routers/bbox_ocr.py` — extracted the expensive pipeline into `compute_tagged_detections(db, job, refresh)` (parse → FIFO attach → `_run_ocr` → `_run_valve_ocr` → cache write) and an RQ entry `run_detections_ocr_rq(job_id, refresh)` that runs on the **cpu-worker**. `_enqueue_detections_ocr` enqueues on the `cpu` queue **deduped by a deterministic RQ job id** (`detections-ocr-{id}`) so a page-load burst collapses to one running job. The GET endpoint is now cheap: serve cache when present (`ocr_status="ready"`), answer `"empty"` inline when there's nothing to OCR, otherwise enqueue + return `{detections: [], ocr_run: false, ocr_status: "pending"}` immediately.
- `webapp/frontend/src/studio/api.ts` — `DetectionsTaggedResp.ocr_status?: "ready"|"empty"|"pending"` (absent on legacy caches → treat as ready).
- `webapp/frontend/src/studio/Studio.tsx` — replaced the one-shot tagged fetch with a **poll loop** (every 4s, ≤60 attempts) that bypasses `cachedFetch` (so the transient "pending" is never cached) and merges OCR tags onto the canvas once `ocr_status != "pending"`. Canvas already renders from the plain `detections` call, so this is purely additive.
- Tests: `tests/unit/test_detections_tagged_bg.py` (10) — parse, empty-compute cache, endpoint pending/empty/cache-hit/403 decisions, enqueue dedup.

**Result:** `detections-tagged` returns in ~ms regardless of OCR cost; the Vision-OCR storm runs on the cpu-worker (where pipeline jobs already run) and the canvas lights up with tags when ready. The threadpool can no longer be saturated by OCR on GETs.

**Notes:** the cpu-worker shares the same image + `OPENROUTER_API_KEY`, so no new infra. Pairs with #121 (multi-worker web).

---

## [2026-06-27] #121 — Multi-worker uvicorn + Redis startup leader-lock

**Type:** infra / reliability
**Stage:** webapp, deployment
**Status:** shipped (branch `feat/web-concurrency-bg-ocr`, PR → `dev`)

**Why:** The root amplifier behind the #118–#120 slowdowns was that `web` ran a **single uvicorn worker** (`Dockerfile` CMD had no `--workers`), so anything that blocked one process degraded *every* page. We want ≥2–4 workers so a saturating burst on one worker no longer takes down the site. The catch: `webapp/main.py` runs migrations, stale-job reset, LS reconcile, and the heartbeat watchdog **at import time**, so N workers would run all of that N× in parallel — concurrent DDL races + N watchdog reaper threads + N LS API sweeps.

**What:**
- `webapp/startup.py` (new) — `should_run_startup_tasks()` elects exactly one worker via Redis `SET NX` (key `qong:web:startup-leader`, 30s TTL, never explicitly released — covers uvicorn's near-instant worker spawn, expires long before any redeploy). Degrades to **True** (run them) when `REDIS_URL` is unset or Redis is unreachable, so a blip can never leave the deploy with no watchdog at all.
- `webapp/main.py` — `run_migrations()` stays **per-worker** on purpose (it's race-safe via existence/column-state probes and must finish before that worker serves a request touching a new column). The genuinely-duplicative side-effects (`start_watchdog`, `_reconcile_ls_webhooks`, `_reset_stale_jobs`, `_ensure_super_admin`, agent-memory init) are gated behind `_IS_STARTUP_LEADER`.
- `Dockerfile` — CMD → shell form `exec uvicorn … --workers ${UVICORN_WORKERS:-1}` (`exec` so SIGTERM reaches uvicorn for clean shutdown). Default 1 (local/single-core).
- `docker-compose.yml` — `UVICORN_WORKERS=${UVICORN_WORKERS:-1}` passthrough on `web`. `docker-compose.override.dev.yml` — sets `UVICORN_WORKERS=3` for dev.
- Drive-by: `webapp/routers/jobs.py` `w: int | None` → `Optional[int]` (the repo rule is "Use `Optional[X]` not `X | None`"; the 3.10 union broke host py3.9 pytest collection of the entire `api_v1`/`jobs` import chain).
- Tests: `tests/unit/test_startup_leader_lock.py` (5) — no-redis runs, first-wins/rest-skip, distinct keys independent, redis-failure degrades to running.

**Result:** dev runs 3 workers; one blocked/slow worker no longer freezes the whole site, and the one-shot startup work runs exactly once per boot.

**Notes:** worker count is env-tunable per environment without a rebuild. YOLO model RAM is fine — it's lazy-loaded per process and in-process inference rarely runs in `web` (the GPU worker handles detection).

---

## [2026-06-26] #120 — detections-tagged: stop blocking the event loop (real fix for slow page loads)

**Type:** bugfix / performance
**Stage:** webapp
**Status:** shipped (branch `fix/detections-tagged-blocking`, PR → `dev`)

**Why:** Even after #118/#119 (Neo4j), dev pages were still slow — `GET /` (SPA shell) measured up to 50s and the browser timed out on the dashboard/signin. Direct app timing proved the app itself was instant (0.00s) in isolation; the slowness only appeared **under concurrent load**, pointing at the **single uvicorn worker** (`uvicorn webapp.main:app`, no `--workers`). Root cause: `GET /api/v1/jobs/{id}/detections-tagged` (`bbox_ocr.py`, added in PR #5, fired on every job-page load) was declared **`async def` but did blocking, synchronous Vision-OCR calls** (`OpenAI().chat.completions.create`, one per instrument circle + one per tile, via `_run_ocr`/`_run_valve_ocr`). Running on the single event loop, its OCR storm (often failing + retrying — `Tile tags OCR API call failed` in logs) **froze the whole app**, so unrelated requests (dashboard, signin, `/`) queued behind it.

**What:**
- `webapp/routers/bbox_ocr.py` — changed `api_job_detections_tagged` from `async def` → **`def`** (it does no `await`), so Starlette runs it in the **threadpool**; the blocking OCR no longer blocks the event loop / other requests.
- Added a **30s timeout + `max_retries=1`** to the OCR `OpenAI` client (was the 600s default) so a stalled/failing OCR call can't hold a threadpool worker for 10 minutes.

**Result:** the OCR work still runs for uncached jobs (and is cached after), but it no longer freezes the app — dashboard/signin/job pages stay responsive while it runs.

**Notes:** (1) Broader hardening for later: run uvicorn with >1 worker, and/or move per-bbox OCR to a background job so the GET returns cached-or-empty immediately. (2) Several other endpoints are `async def` doing quick sync DB work — fine on the loop (sub-ms), unlike the multi-second OCR; left as-is.

---

## [2026-06-26] #119 — Skip Neo4j connections when disabled (fix site-wide slow page loads)

**Type:** bugfix / performance
**Stage:** infra, webapp
**Status:** shipped (branch `fix/neo4j-skip-when-disabled`, PR → `dev`)

**Why:** After #118 removed the Neo4j container, every page on dev became intermittently slow — `GET /` (SPA shell) measured **34s** while nginx `/healthz` was 0.11s, and the browser timed out (60s) loading even `/signin` and the dashboard. Root cause: the app still *attempted* Neo4j connections (`read_graph_from_neo4j` on every `/graph` load, `initialize_schema` at startup, edge mirroring), and resolving the now-absent `neo4j` host fails **slowly** (`Cannot resolve address neo4j:7687`, ~30s DNS failure with retries). Those slow requests saturated the limited worker pool, so unrelated requests (dashboard, signin, the SPA shell) queued behind them. The `try/except` fallbacks caught the *error* but not the *latency*.

**What:** Added a `_neo4j_enabled()` guard (`bool(os.environ.get("NEO4J_PASSWORD"))`, read live) to both Neo4j modules and short-circuit **before** any driver is created:
- `webapp/graph/neo4j_writer.py` — early-return in `read_graph_from_neo4j` (→ None, transparent fallback), `write_graph_to_neo4j`, `write_user_edge_to_neo4j`, `delete_user_edge_from_neo4j`.
- `webapp/graph/agent_memory.py` — `initialize_schema` returns early (no startup hang); `_get_driver` raises fast when disabled so chat functions fail instantly via their existing try/except.
- Tests: `tests/unit/test_neo4j_disabled.py` (6) — verifies instant skip (<0.1s) and that opt-in is preserved when `NEO4J_PASSWORD` is set.

**Result:** With Neo4j disabled, `read_graph_from_neo4j` returns in **0.0ms** (was ~30s on DNS failure). No Neo4j connection is attempted anywhere, so no worker-pool saturation → page loads return to normal.

**Notes:** Opt-in is intact — set `NEO4J_PASSWORD` (+ re-add the service) and all Neo4j paths re-activate. This is the runtime-safety complement to #118.

---

## [2026-06-26] #118 — Remove Neo4j from the runtime (unblock dev deploy)

**Type:** bugfix / infra
**Stage:** infra
**Status:** shipped (branch `fix/remove-neo4j`, PR → `dev`)

**Why:** Every dev deploy since PR #5 (which added a Neo4j service) **failed** at `docker compose up` with `required variable NEO4J_PASSWORD is missing a value`. dev's `.env.dev` never had it, so the container was frozen at the 2026-06-26 05:58 image — meaning PR #5 (Line List / I/O List enablement, vendor dropdown after Pair No.) **and** #117 (instrument sort + Process Function column) were merged but never went live. Diagnosed via Playwright (live UI showed Line List "SOON", no vendor dropdown) + container `.Created` 05:58 + SSM deploy logs (`NEO4J_PASSWORD missing`).

**What:** Removed Neo4j from `docker-compose.yml` — deleted the `neo4j` service + `neo4j_data` volume, removed `NEO4J_*` env from `web`/`cpu-worker`, and dropped `neo4j` from both services' `depends_on`. The Neo4j **app code is intentionally kept** (`graph/neo4j_writer.py`, `graph/agent_memory.py`, `routers/graph.py` twin view, `routers/agent.py` chat, edge mirroring): every call is already `try/except`-guarded with a Postgres/canonical fallback, so it no-ops gracefully with no Neo4j present. Core deliverables (instrument index, datasheets, valve/line/equipment lists) never used Neo4j.

**Result:** `docker compose` no longer hard-requires `NEO4J_PASSWORD`; deploy proceeds and `up web cpu-worker` no longer pulls a Neo4j container (no memory load on the 3.8 GB box). Unblocks #117 + PR #5 features going live.

**Notes:** (1) Reversible — re-add the service + a `NEO4J_PASSWORD` (SSM + `.env`) to restore the digital-twin/agent-memory features. (2) The graph read still attempts a bolt connection per load and fast-fails to the canonical fallback (negligible); a follow-up could short-circuit when `NEO4J_PASSWORD` is unset, or rip out the Neo4j code entirely. (3) Base compose is shared across envs; Neo4j was new in PR #5 and not yet on qa/prod, so removal is env-safe.

---

## [2026-06-26] #117 — Instrument Index: validated ISA function-ladder sort + Process Function column

**Type:** feature
**Stage:** export, review
**Status:** shipped (branch `feat/instrument-isa-sort`, PR off `dev`)

**Why:** PR #3 reviewers wanted the Instrument Index ordered like an engineering index and to show tag number + process function. dev had recently merged a first-cut `sort_utils.instrument_sort_key` (PR #5), but its order contradicted what the user validated against real data: it grouped by **measured-variable** (not loop number) and placed **PDI before PDIT** (user wants PDIT before PDI), and had no controller/valve/switch handling. The user validated the correct order with me against real job-43 (28 instruments) + job-55 (18) sets.

**What:**
- `webapp/deliverables/sort_utils.py` — rewrote `instrument_sort_key(tag)` (same signature, so both callers auto-upgrade) to the validated key `(area, loop_number, loop_suffix, function_rank, alarm_rank, tag)`: **loop number primary**, then the ISA ladder **TW→E→G→T(transmitter family)→I→C→A(H,HH,L,LL)→final-element(V/Y)→switch(S)→other**. Code read from the first all-alpha tag segment (handles `62-FE-151010` and `422-11-PT-006A`); A/B loop suffix groups parallel trains. Used by `instrument_index.py` (CSV+XLSX) and `entities.py` (on-screen rows) unchanged.
- Templates `default/muk/ronesans.json` — added **Process Function** (`sub_class`) column (dev already had a `tag` column). Default index 35 → 36 cols.
- Tests: `tests/unit/test_sort_utils.py` (13, incl. full job-43/55 orders); updated `test_instrument_index.py` (36-col assert) + regenerated golden CSV fixture.

**Result:** Live generator on real job-55 canonical → validated order (loop 151025 = PDIT before PDI), 36 cols incl. Process Function. `pytest` deliverables+sort suite green except 3 pre-existing dev failures (`pipeline_emitter` vendor_match + `equipment_list`, from PR #5's vendor-masking/equipment refactor — confirmed failing on clean dev).

**Notes:** (1) Supersedes PR #5's `sort_utils` ordering. (2) Function rank derives from the tag's alpha segment (== `tag_type_code` in real data); `sub_class` is descriptive + inconsistent, so not the sort source. (3) PR #3 (feature/dropdown) is superseded — its vendor-dropdown work already shipped on dev via PR #5; only this sort+column delta was net-new. (4) Ladder is an editable table (`_BUCKET_RANK`).

---

## [2026-06-26] #116 — Multi-signal recovery validator + adaptive project-aware line-number parser

**Type:** feature / extraction / deliverable
**Stage:** webapp / extraction
**Status:** implemented (uncommitted), branch `feature/graph`

**Why:** (a) A recovered line passing a regex isn't trustworthy — `SP5LC` vs `SP5XX` both look fine to a regex, and job 24's `1200-WWE-XXXX-SP5XX` was a likely OCR artifact presented as confirmed. (b) Line-number parsing was a naive `split("-")` that broke on fractional sizes (`1-1/2"`), parenthesised classes (`AC(PFA)`), and assumed a fixed segment count — and a junk explicit `fields.size` ("NOT DEFINED") overrode the real first-segment size.

**What:**
- **Multi-signal recovery validator** (`line_orient_ocr.py`): recovered lines are scored on cross-ROI occurrence, source diversity (pipe / connector / continuation / truncated), orientation agreement (same value at multiple rotations — the sweep no longer early-breaks), and conformance to the project's learned size/fluid/class vocab + typical segment count. `SP5LC`-vs-`SP5XX` stem conflicts resolve to the project-known class. Below threshold (`LINE_ORIENT_OCR_CONFIRM`=0.60) or ambiguous → kept but `_status="needs_review"` (Line List Remarks shows "NEEDS REVIEW — recovered (orientation OCR) (conf X) — ambiguous vs …"). Confirmed reads that match an existing line just corroborate (no dup). `line_coverage.json` now reports confirmed/needs_review counts + per-pipeline confidence.
- **Adaptive parser** (`line_parser.py`, new, pure-stdlib): `learn_convention(lines)` + `parse_line(line, convention, explicit_service)`. Peels fractional size before splitting; paren-aware segment tokenizer; sequence = longest digit run (modal index only as fallback); class = segment after sequence (parens kept whole); insulation = separate trailing segment only. Confidence-gated — blanks rather than guesses. See `docs/superpowers/specs/2026-06-26-adaptive-line-number-parser-design.md`.
- **Line List wiring** (`webapp/deliverables/line_list.py`): UI (`generate_line_list`) + export (`synthesize_recovered_line_entities`) both learn the convention per-job and parse via it. Size precedence: confidently-parsed first segment is authoritative (fixes "NOT DEFINED"/"15" overriding `300`/`200`); `_real()` filters placeholder non-values; insulation now populated from the parse.

**Verification:** validator unit test — `300-WWE-XXXX-SP5LC` (corroborated, known class) → 1.00 CONFIRMED; `1200-WWE-XXXX-SP5XX` (one-off, unknown class) → 0.15 needs_review. Parser — all gold spec examples pass (`AC(PFA)` preserved, `1/2"` preserved, `151045B`-vs-`62`). Zero-API multi-job audit (10/11/12/13/24): size 54/54, **0 duplicates**, class 39/54 + insulation 13 (rest correctly blank). Multi-job orientation report (cap 40): 55 pipelines, 19 recovered, 3 confirmed / 16 needs_review, **0 duplicates** — validator correctly quarantines tracer-noise reads.

**Gotcha:** images were rebuilt once before this entry, but `line_parser.py` (new) + the latest `line_list.py`/`line_orient_ocr.py` edits are only `docker cp`'d into the running web container for testing — a fresh `docker compose build web cpu-worker` is required before new uploads use them. The adaptive parser is API-free (re-parses existing line numbers), so deliverable re-checks cost nothing; only the orientation pass spends Vision calls.

---

## [2026-06-26] #115 — Pass 4.5: orientation-aware line-number coverage pass (flag-gated)

**Type:** feature / extraction
**Stage:** webapp / extraction
**Status:** shipped behind flag (branch `feature/graph`), default OFF

**Why:** Engineering line numbers appear vertically, rotated 90/180/270°, and along inclined pipes. Pass 4 sends whole tiles to Gemini Vision (which reads most orientations) but has no coverage guarantee, no cross-tile handling, and emits truncated identifiers (`4"-X`, `20"-W`). Spec required: trace every pipeline, find attached text in any orientation, normalise crops to horizontal before OCR, and only report "no line number" after exhausting rotated/merged-ROI attempts — without changing the production architecture.

**What:** New `line_orient_ocr.py` (repo root) — `apply_orientation_pass(job_dir)`, wired into `webapp/pipeline_runner.py` right after Pass 4, gated by env `LINE_ORIENT_OCR=1` (unset ⇒ byte-identical behaviour/API-usage/output). Design: `docs/superpowers/specs/2026-06-26-orientation-aware-line-ocr-design.md`.
- **Gemini Vision is the ONLY OCR engine** — no EasyOCR/PaddleOCR/Tesseract/RapidOCR. The OpenCV tracer (`webapp/graph/tracer.py`, read-only) + candidate logic only select better crops + estimate orientation; all recognition is the Vision API.
- **Additive/repair only** — runs only on *unresolved* targets: traced pipes with no nearby valid line, entities whose `fields.line` failed validation, and right/bottom edge-band tables (continuation / off-page connector tables — req: don't depend only on the tracer). Never deletes Pass-4 data.
- **Candidate ordering is high-value-first** — truncated-entity repairs → edge-band connector/continuation tables → traced pipes longest-first. Critical: a tight `MAX_CALLS` budget must not be starved by tracer noise (on job 24 the original pipe-first order spent all 40 calls on skeleton fragments and never reached the connector table; reordering fixed it).
- **Full-page ROIs** from `tmp/page_0_full.png` — no re-tiling (avoids split numbers / tile-boundary truncation), tile generation untouched.
- **Orientation sweep** per ROI: original → estimated pipe orientation → 90 → 270 → 180; stop on first candidate passing engineering validation (most-complete-first).
- **Engineering-aware validation** `_engineering_line_valid`: numeric size prefix + ≥3 dash segments + well-formed segments; rejects `4"-X`/`20"-W`/`BGA`/`XXXX-AS1LC`, accepts `300-WWE-XXXX-AS1LC`/`50-ABL-XXXX-AS2LC`/`3"-P-62151007-BGA`.
- **Merge/dedup** by normalised key across Pass 4 + all ROI sources — never duplicates.
- **Cost cap** `LINE_ORIENT_OCR_MAX_CALLS` (default 40) bounds total Vision calls regardless of candidate count.
- **`line_coverage.json`** written for QA only (pipeline id, traced, line_number_found, extraction_source, validation_status) — NOT exposed by any production API.
- **Line List deliverable is now a UNION** (req: "represents engineering pipelines, not valve entities"). `webapp/deliverables/line_list.py:generate_line_list` (UI `/jobs/{id}/line-list`) emits rows from canonical entities with a valid `fields.line` **+ recovered pipelines present only in `line_list_data.json`**, keyed/deduped on normalised Line No (entity fields preferred on merge; recovered rows tagged `Remarks="Recovered (orientation OCR)"`). Export path (`exports.py` → `LineList{CSV,XLSX}Generator`) gets the same union via `synthesize_recovered_line_entities` appended to a **request-local** canonical copy (scoped to `line_list` only — recovered pseudo-entities never leak into the Valve List). Also fixed `line_list.py:_VALID_LINE_RE` to make the inch symbol optional (was dropping mm-format lines like `50-ABL-…` from exports — same bug fixed earlier in entities.py).

**Validation:** validator passes all approved accept/reject examples; orientation order correct (vertical pipe → [0,270,90,180]). Zero-cost smoke test on job 11 (`LINE_ORIENT_OCR_MAX_CALLS=0`): tracer→84 segments, 86 candidate ROIs, `line_list_data.json` byte-identical (additive proof), `line_coverage.json` written. **Real-API run on job 24 (latest):** Pass 4 populated its 4 lines (fluids merged); Pass 4.5 traced 83 segments, examined the edge connector table + longest pipes, independently re-read `300-WWE-XXXX-SP5LC` (off-page connector) + `50-ABL-XXXX-AS2LC` (pipe) and correctly **deduped to 0 new** — job 24 had no missed/rotated line to recover, so the pass *confirmed coverage*. Line-list deliverable now shows 4 rows with fluid/size/class. **Row-surfacing verified:** deterministic test (inject a recovered-only line → appears as a new row in BOTH UI and export, no dupes); and a real exhaustive rerun (cap 120) recovered a genuinely-new line `1200-WWE-XXXX-SP5XX` from a traced pipe (not on any entity) → surfaced as a 5th Line List row tagged "Recovered (orientation OCR) [pipe]". (NB: that specific recovery's `…SP5XX` tail should be QA-eyeballed against the drawing — possible OCR artifact; this is exactly what the Remarks tag + line_coverage.json are for.)

**Gotcha:** the tracer was tuned for graph topology; on sparse-line jobs nearly every traced segment reads as "uncovered," so the cost cap (not segment count) is what bounds spend. Raise `LINE_ORIENT_OCR_MAX_CALLS` to widen coverage. Tracer-tuning for line-ROI selection is a future refinement.

---

## [2026-06-26] #114 — Studio performance: API cache + parallel loading + BulkReview lazy mount + React.memo

**Type:** performance / frontend
**Stage:** webapp
**Status:** shipped (branch `fix/graph-edge-quality`)

**Why:** Studio page fired 6–8 sequential API calls every time it mounted, including a duplicate re-fire when the user navigated to Bulk Review and back (the early `return <BulkReviewScreen>` unmounted Studio entirely, destroying all loaded state). On slower connections this caused a visible re-render stutter on every Bulk Review toggle.

**What:**
- `webapp/frontend/src/queryCache.ts` (new): in-memory TTL cache keyed by URL. TTLs: sheets 5 min, detections/OCR 2 min, entities 2 min, graph 10 min. `invalidateJob(id)` clears all keys for a job (call after reprocess). Zero API calls on re-open within TTL window.
- `Studio.tsx` useEffect rewritten: sheets + detections fire immediately in parallel; OCR tags fire concurrently (not waiting for detections); entity lists fire as `Promise.all`; graph deferred 1500 ms so it never races canvas render resources.
- BulkReview lazy mount + CSS hide/show: replaced early `return <BulkReviewScreen>` with `bulkEverOpened` ref — component mounts on first visit, then lives hidden behind `display: none` rather than unmounting. Studio's own div uses `display: none` when in bulk mode, no style override when in studio mode (critical: must not set `display: block` or it overrides the CSS `display: flex` on `.studio` and collapses the layout).
- `PropertiesPanel.tsx`: wrapped with `React.memo` — prevents re-render on Studio state changes that don't touch panel props (zoom, pan, graph toggle, etc.).
- GzipMiddleware: `fastapi.middleware.gzip.GZipMiddleware(minimum_size=1000)` added to `webapp/main.py` — all JSON responses >1 KB now compressed; ~60–70% size reduction on entity lists and detection payloads.

**Gotcha:** Setting `style={{ display: "block" }}` on `.studio` div overrides its CSS `display: flex`, collapsing the entire three-pane layout. Always use `style={condition ? { display: "none" } : undefined}` — no inline style at all when showing, so the CSS class wins.

---

## [2026-06-26] #113 — Motor/Pump cross-assignment fix in entity matching

**Type:** bugfix
**Stage:** webapp / detections
**Status:** shipped (branch `fix/graph-edge-quality`)

**Why:** Job 21 showed 3/21 pumps matched and 11/18 motors matched, with 6 cross-assignments — motor detections were consuming pump canonical entities. Root cause: `_attach_entity_ids` in `api_v1.py` had a `same_system` guard (prevents Motor detections stealing Pump entities when both exist), but when `same_system=False` (no motor entities in canonical) it fell back to class-only matching — which consumed pump entities under the shared `equipment` class.

**What:** Added `class_has_sub` guard in `api_v1.py:_attach_entity_ids`. Logic: if ANY entity in the same `entity_class` has a non-null `sub_class`, never fall back to class-only matching for any sub_class in that class. Motors will match nothing rather than steal Pumps. After fix: job 21 shows 9/21 pumps matched (exactly the 9 canonical pump entities), 0 motors matched, 0 cross-assignments.

---

## [2026-06-26] #112 — Pass 4 entity_id mismatch fix + scan-all-tiles fallback

**Type:** bugfix
**Stage:** extraction
**Status:** shipped (branch `fix/graph-edge-quality`)

**Why:** Jobs 20/21 had no line list data. Root cause for job 20: job was reprocessed → canonical got new entity_ids → `detections_ocr.json` still had old entity_ids → Pass 4 built an empty entity→tile mapping → no tiles to query → skipped. Jobs 2/6/8/10 had no `detections_ocr.json` at all (pre-OCR runs) → Pass 4 hard-exited immediately.

**What (extractor.py `apply_fourth_pass`):**
- `detections_ocr.json` made optional: missing file sets `detections_ocr = {}` instead of returning early.
- Tag-based fallback: build `tag_to_tile` from detection dicts (uses `entity_tag` field) and `eid_to_tag` from canonical. If entity_id lookup misses, fall back to tag match. Fixes reprocessed-job mismatch without needing to re-run OCR.
- Scan-all-tiles fallback: if unmapped lines remain after both id+tag lookups, iterate all `tile_p0_r*.png` in the job's `tmp/` dir and queue the lines against every tile. Ensures Pass 4 always runs even with zero OCR data.
- All 5 affected jobs (2, 6, 8, 10, 20) now produce `line_list_data.json` after re-run.

---

## [2026-06-25] #111 — Pass 5 prompt hardening: truncation guard + max_tokens increase

**Type:** improvement
**Stage:** extraction
**Status:** shipped

**Why:** Pass 5 Vision OCR was truncating multi-word spec values — `HORIZONTAL CENTRIFUGAL` → `HORIZON`, `DUPLEX SS` → `DUPLEX S`, `4900 US gpm` → `4900 US`. Root causes: (1) `max_tokens=512` caused mid-word cutoff on long JSON responses; (2) prompt didn't warn against abbreviation.

**What:**
- `prompts.py` FIFTH_PASS_SYSTEM: added explicit WRONG/CORRECT truncation examples in the rules block
- `prompts.py` FIFTH_PASS_USER_TEMPLATE: clarified that spec block may appear above/below/beside the symbol (not just "right of"); added "read all words, do not truncate" instruction on multi-word fields
- `extractor.py apply_fifth_pass()`: `max_tokens` 512 → 1024

---

## [2026-06-25] #110 — Equipment spec job 17: manual correction from screenshot

**Type:** data fix
**Stage:** deliverables
**Status:** shipped

**Why:** Pass 5 Vision OCR ran on job 17 and produced truncated/typo values for `62-P-151005` and `62-S-151002`. User provided a screenshot of the actual spec block on the drawing.

**What:** `job_outputs/1/17/equipment_specs.json` patched directly:
- `62-P-151005.type`: `"HORIZON"` → `"HORIZONTAL CENTRIFUGAL"`
- `62-P-151005.material`: `"DUPLEX S"` → `"DUPLEX SS"`
- `62-P-151005.design_temperature`: `"212 °F"` → `"212 F"`
- `62-S-151002.type`: `"CONICAL STRANER"` → `"CONICAL STRAINER"`

---

## [2026-06-25] #109 — Line List: Insulation Type from piping class suffix

**Type:** feature
**Stage:** deliverables, bulk-review
**Status:** shipped

**Why:** The Insulation Type column ("Type" under the INSULATION group header) in the Line List was always blank. The insulation/tracing type code IS encoded in the line number — it's the alpha suffix after the base piping spec code: `BGA-H` → H (Heat Traced), `BGA-HD` → HD, `BGA-ET` → ET, `BGA` alone → no insulation.

**What:** `entities.py get_entities()` — after the piping_class derivation step, extracts the trailing alpha suffix from `fields.piping_class` and sets `fields.insulation_type`. Guard: `isalpha()` + `len 1–4` prevents serial numbers (`24C7`) or numeric segments from being misclassified.

**Notes:** Verified on job 17: `BGA-H` → `H`, `BGA-HD` → `HD`, `BGA` → blank (correct).

---

## [2026-06-25] #108 — Line List Bulk Review: Fluid/Size/Phase/Piping Class from canonical at read time

**Type:** bugfix
**Stage:** deliverables, bulk-review
**Status:** shipped

**Why:** Bulk Review Line List showed blank Fluid, Nominal Pipe Size, Phase, and partial Piping Class despite the data existing in canonical. Root causes:
- `fields.fluid_type` (template column) is never written by the emitter — emitter writes `fields.fluid_code`
- `fields.size` on valve entities is the **valve bore** ("NOT DEFINED" for diaphragm valves), not the pipe diameter — pipe size is the prefix of the line number tag (`20"-W-…` → `20"`)
- `fields.phase` is never emitted — inferrable from fluid code

**What:** `entities.py get_entities()` — added line_list derivation block before OCR injection and `rows.append()`:
1. Parses `size / fluid_code / piping_class` from `fields.line` tag (same logic as `line_list.py _parse_line_no()`)
2. Fills `fields.fluid_type` from `fields.fluid_code` if blank
3. Fills `fields.size` from parsed line prefix if blank or "NOT DEFINED"
4. Fills `fields.piping_class` from parsed line tag if blank
5. Infers `fields.phase`: W/WAP/FW/CW/SW/O/LO/HO/P/GO → Liquid; G/GAS/NG/FG → Gas

**Notes:** Pressure/Temp/Material stay blank for job 17 — those columns require the P&ID to have printed annotation blocks next to the pipe lines. Job 17's drawing does not have them.

---

## [2026-06-25] #107 — Pass 5 Vision OCR: equipment spec extraction → equipment_specs.json

**Type:** feature
**Stage:** extraction, deliverables
**Status:** shipped

**Why:** Equipment data blocks (QUANTITY, TYPE, RATED CAPACITY, DIFFERENTIAL PRESSURE, DESIGN TEMPERATURE, MOTOR RATING, MATERIAL) are printed near equipment symbols on P&IDs but were never extracted or stored. Equipment List columns for these fields were always blank.

**What:**
- `prompts.py`: `FIFTH_PASS_SYSTEM` + `FIFTH_PASS_USER_TEMPLATE`
- `extractor.py apply_fifth_pass()`: loads canonical equipment entities with tags; maps entity_id → tile via `detections_ocr.json`; one Vision API call per equipment; writes `equipment_specs.json` keyed by tag
- `pipeline_runner.py`: non-fatal try/except after `apply_fourth_pass()`
- `equipment_list.py`: `_load_equipment_specs()` + `_enrich_equipment()` helpers; both CSV/XLSX generators call `_enrich_equipment()` at generate time
- `entities.py`: loads `equipment_specs.json` at request-time for `equipment_list`; injects 7 spec fields (type, rated_capacity, differential_pressure, design_temperature, motor_rating, material, quantity) before `rows.append()`
- `default.json`, `muk.json`, `ronesans.json`: equipment_list section expanded with all 7 new spec columns

**Notes:** `detections_ocr.json` (entity_id → tile) is the bridge. Equipment entities without a detection entry are silently skipped. Spec block may appear above/below/beside the symbol — full tile is sent, not a cropped bbox.

---

## [2026-06-25] #106 — Studio UX: zoom-to-cursor, renderWidthPx step-down, Bulk Review natural sort

**Type:** ux, bugfix
**Stage:** frontend
**Status:** shipped

**Why:** Three independent UX regressions bundled in one commit: (1) scroll-to-zoom was anchored to canvas origin, not cursor — disorienting on large drawings; (2) `renderWidthPx` only stepped up on zoom-in, so high-res images stayed loaded after zooming out (memory + banding); (3) Bulk Review tables used default string sort, scrambling tag numbers (e.g. 10 before 2).

**What:**
- `PidCanvas.tsx`: wheel handler now anchors zoom to pointer position (`newPan = { x: cx - (cx - p.x) * realFactor, y: cy - (cy - p.y) * realFactor }`); `animTimerRef` debounce prevents mid-scroll transition glitches
- `Studio.tsx`: added `currentZoomRef` to track live zoom inside async callbacks; `renderWidthPx` can now step DOWN when zoom drops below the 50% threshold
- `entities.py`: natural ascending sort (natsort / manual) applied to all deliverable table types in Bulk Review

---

## [2026-06-25] #105 — IO List: _classify_system word-boundary fix + FIELD reclassification at read time

**Type:** bugfix
**Stage:** deliverables, io-list
**Status:** shipped

**Why:** 15 instruments in job 17 showed `system='FIELD'` — a legacy CSV-import artifact. Additionally, `_classify_system()` had a substring bug: `"SIS" in "ANALYSIS ELEMENT"` is True, causing analysis instruments to be wrongly classified as SIS. canonical.json must not be modified.

**What:**
- `pipeline_emitter.py`: replaced `kw in desc` substring check with `re.split(r'\W+', desc)` word-set intersection — `{"SIS"} & {"ANALYSIS", "ELEMENT"}` correctly returns empty
- `entities.py get_entities()`: for `deliverable_type == "io_list"`, re-classifies any `system` value that is blank or `"FIELD"` using `_classify_system(tag_type_code, instrument_type)` from `pipeline_emitter`; done at read-time, canonical.json untouched

**Notes:** Verified job 17: `62-AE-151008` (ANALYSIS ELEMENT) → BPCS; `62-AIT-151008` (ANALYSIS INDICATING TRANSMITTER) → BPCS; 0 FIELD values remain in IO List.

---

## [2026-06-25] #104 — Bulk Review Line List: OCR data injection at entities API read time

**Type:** feature
**Stage:** deliverables, bulk-review
**Status:** shipped

**Why:** The Bulk Review Line List (engineering columns: pressure, temp, material, insulation, fluid, pipe size) was completely blank. Root cause: `BulkReviewScreen` fetches `/api/v1/jobs/{id}/entities?deliverable_type=line_list`; the `generate_line_list()` function (which merges `line_list_data.json`) is only called by the legacy `/api/v1/jobs/{id}/line-list` endpoint, which is never rendered in Bulk Review.

**What:**
- `entities.py get_entities()`: for `deliverable_type == "line_list"`, loads `line_list_data.json` from the job directory at request time; injects Pass 4 OCR values into `FieldValue` for 10 columns via `_OCR_FIELD_MAP`
- Injection happens BEFORE `rows.append(EntityRow(..., values=values))` — Pydantic copies the `values` dict on `__init__`; mutations after append have no effect (hard-won lesson)
- `_OCR_FIELD_MAP`: `{"fluid": "fields.fluid_type", "op_pressure": "fields.working_pressure", "op_temp": "fields.working_temp", "design_pressure": "fields.design_press", "design_temp": "fields.design_temp", "pipe_size": "fields.size", "piping_class": "fields.piping_class", "insulation": "fields.insulation_type", "material": "fields.material"}`

**Notes:** Verified job 17: `2"-W-62151019-BGA-H` shows `FEED WATER`, `3"-W-62151009-BGAK` shows `RECYCLE LINE` in the Bulk Review Line List.

---

## [2026-06-25] #103 — Pass 4 Vision OCR: engineering data from P&ID tiles → line_list_data.json

**Type:** feature
**Stage:** extraction
**Status:** shipped

**Why:** Line List engineering columns (pressure, temperature, fluid, material, insulation, pipe schedule) are never present in the canonical tag text — they appear as annotations next to pipe lines on the drawing. A separate Vision OCR pass per tile is the only way to populate them without manual entry.

**What:**
- `prompts.py`: added `FOURTH_PASS_SYSTEM` (instructs model to read engineering data from pipe lines in P&ID tiles) and `FOURTH_PASS_USER_TEMPLATE` (passes tile coordinates + list of line numbers; model returns JSON keyed by line number with fields: fluid, phase, op_pressure, op_temp, design_pressure, design_temp, pipe_size, schedule, piping_class, insulation, material)
- `extractor.py`: `apply_fourth_pass(job_dir, model)` — loads `canonical.json` for entity_id → line_number map; loads `detections_ocr.json` for entity_id → tile; Counter-votes best tile per line number; groups lines by tile; one Vision API call per tile (base64-encoded PNG); writes `line_list_data.json`
- `pipeline_runner.py`: calls `apply_fourth_pass()` in a non-fatal try/except after `apply_third_pass()`
- `line_list.py generate_line_list()`: loads `line_list_data.json` and merges into rows — OCR always fills pressure/temp/material/insulation; fills fluid/size/piping_class only when blank (line-number parsing takes priority)

**Notes:** `detections_ocr.json` (entity_id → tile filename) is the bridge between canonical entity IDs and tile images. Jobs that lack `detections_ocr.json` skip Pass 4 gracefully.

---

## [2026-06-25] #102 — Bulk Review: DatasheetPanel wired into instrument datasheet sidebar

**Type:** feature
**Stage:** bulk-review, frontend
**Status:** shipped

**Why:** The Bulk Review instrument row sidebar showed a flat key-value field list for the "datasheet" tab — same as all other document types. The full sectioned DatasheetPanel (numbered sections, MANUAL badges, inline Save) already existed for Studio's DatasheetDrawer but was not wired into BulkReview.

**What:**
- `BulkReviewScreen.tsx`: when `activeKey === "datasheet"`, renders `<DatasheetPanel instrumentTag={...} jobId={...} deliverableType="instrument_index" />` (full sectioned view with numbered sections, MANUAL badges, inline Save); all other tabs keep the existing flat `FieldList`
- "Open in Studio" button hidden when in datasheet mode (redundant with the full panel)

---

## [2026-06-25] #101 — Studio: OCR-based instrument tag display for unmatched YOLO detections

**Type:** feature
**Stage:** studio, frontend
**Status:** shipped

**Why:** After per-bbox Vision OCR tagging (#100), some detections now have an `entity_tag` (OCR-extracted engineering tag) but no `entity_id` (no canonical match). These unmatched detections were invisible — no label, indistinguishable from empty space. Engineers need to see unmatched tags to decide whether to add them to canonical.

**What:**
- `bbox_ocr.py`: improved to tight-crop OCR specifically on inst_field/inst_bpcs/inst_sis circles for higher accuracy
- `PidCanvas.tsx`: unmatched detections (entity_id null, entity_tag present) always show their tag label, render with a colored bbox + dashed border, and are hoverable; canonical bboxes (entity_id non-null) are unchanged (label on hover/select, clickable to sidebar)
- `Studio.tsx`: calls `getDetectionsTagged()` in the background after initial page load and replaces detections state — no blocking spinner
- `api.ts`: `DetectionsTaggedResp` type + `getDetectionsTagged()` helper; `entity_tag` field added to `DetectionItem`

---

## [2026-06-25] #100 — Studio: per-bbox Vision OCR tagging to fix FIFO entity mismatch

**Type:** feature, bugfix
**Stage:** studio, extraction
**Status:** shipped

**Why:** YOLO detections were matched to canonical entities in FIFO order (first detection on page → first entity in canonical list). This broke when multiple instruments of the same class appeared on the same tile — labels would swap. Vision OCR per bbox is the correct fix: read the engineering tag printed inside each detection circle directly.

**What:**
- `webapp/routers/bbox_ocr.py`: new router with `GET /api/v1/jobs/{job_id}/detections-tagged` — crops each YOLO bbox from tile PNG, sends to OpenRouter Vision API (Gemini), extracts the engineering tag string, matches to canonical entities by tag string, caches results to `detections_ocr.json` for instant subsequent loads
- `webapp/main.py`: registers `bbox_ocr` router
- `api_v1.py`: exposes `entity_tag` on detection items
- `Studio.tsx` + `api.ts`: client calls `getDetectionsTagged()` after initial load and replaces detections with OCR-accurate matches

**Notes:** `detections_ocr.json` format: `{ entity_id → { tile, bbox, tag } }`. Pass 4 (`apply_fourth_pass`) relies on this file existing to bridge entity_id → tile.

---

## [2026-06-24] #99 — Bulk Review: Remarks unconditionally blank for line_list deliverable

**Type:** bugfix
**Stage:** deliverables, bulk-review
**Status:** shipped

**Why:** Bulk Review sidebar and table were showing extracted `service_description` values ("process", "NOTE 1", "(HOLD-6,8)", etc.) in the Remarks column for line_list. Remarks is a manual-entry column — it must always start blank; operators fill it in themselves.

**What:** `webapp/routers/entities.py` — in the field-value building loop, unconditionally blank `fields.service_description` when `deliverable_type == "line_list"`:
```python
if deliverable_type == "line_list" and col.field == "fields.service_description":
    fv = FieldValue(value="", is_override=fv.is_override)
```
Preserves `is_override` so any user-typed override is still honoured. Both the main table and the side-panel detail view now show blank / `—` for Remarks on every line list row.

**Commit:** `51930a1`

---

## [2026-06-24] #98 — DatasheetDrawer: I/O List + Line List activated (removed COMING SOON)

**Type:** feature
**Stage:** studio, frontend
**Status:** shipped

**Why:** I/O List and Line List were wired to real backend deliverables but still showing the "COMING SOON" grey-out in the DatasheetDrawer dropdown, making them inaccessible from the document type picker.

**What:** `webapp/frontend/src/studio/datasheet/DatasheetDrawer.tsx` — added two entries to `DOC_TYPE_TO_DELIVERABLE`:
```typescript
io: "io_list",
lines: "line_list",
```
Equipment list was already mapped. All six document types (instrument index, datasheet, valve list, equipment list, I/O list, line list) are now active and route through the same deliverable fetch/render path.

**Commit:** `51930a1`

---

## [2026-06-24] #97 — Line List view: end-to-end 24-column table (generator + endpoint + frontend)

**Type:** feature
**Stage:** deliverables, api, frontend
**Status:** shipped

**Why:** Line List tab in Studio was showing the old graph-edge draw-line flow (irrelevant to P&ID line list). Needed a real deliverable view populated from canonical.json — 24 engineering columns matching the EPC Line List spec.

**What (3 layers):**

1. **`webapp/deliverables/line_list.py`** — `generate_line_list(job_dir, job_id, db)`:
   - Reads `canonical.json` directly (no DB); collects from ALL entity classes (valve, instrument, equipment) that have `fields.line` containing `-`
   - Deduplicates on line number string
   - `_parse_line_no()`: extracts size / fluid_code / piping_class from line number segments; rejoins last two segments when second-to-last is all-alpha ≥2 chars (e.g. BGA-ET, BGA-HD)
   - `_infer_phase()`: W/WAP/FW/CW/SW/O/LO/HO/P/GO → Liquid; G/GAS/NG/FG → Gas; else blank
   - All manual-entry columns (Pressure, Temp, Density, etc.) return empty string
   - Rows sorted by Line No

2. **`webapp/routers/jobs.py`** — `GET /api/v1/jobs/{job_id}/line-list`:
   - Standard auth + job-access check
   - Returns `{"rows": [...], "count": N}`

3. **`webapp/frontend/src/studio/edges/LineListView.tsx`** — complete replacement:
   - Removed all graph-edge / listEdges logic
   - Fetches `/api/v1/jobs/{jobId}/line-list` with `credentials: "include"`, `cache: "no-cache"`
   - `COLUMNS` array: 24 columns in spec order
   - Yellow `#FFD700` header background, `#1a1a1a` text
   - Reuses existing `.bulk-review.alldata`, `.alldata-table`, `.br-empty`, `.br-btn` CSS

**From/To note:** These fields only populate if the P&ID drawing has explicit FROM/TO banner annotations at pipe endpoints and the job has been re-run with the EPC-grade extraction prompts (merged from `line_list` branch in #95). Fluid/Phase always populate from line-number parsing for any job.

**Commit:** `51930a1`

---

## [2026-06-24] #96 — instrument unit_number: isdigit() guard (tags without area-code prefix)

**Type:** bugfix
**Stage:** pipeline, deliverables
**Status:** shipped

**Why:** Equipment emitter already used `isdigit()` to guard unit_number extraction (FEATURES #86). Instrument emitter did not — so tags like `FE-1001` (no area-code prefix) were storing `"FE"` as `unit_number`, polluting the instrument index and datasheets.

**What:** `webapp/deliverables/pipeline_emitter.py` — changed instrument `unit_number` extraction from:
```python
fields["unit_number"] = tag_parts[0] if tag_parts else ""
```
to:
```python
first_part = tag_parts[0] if tag_parts else ""
fields["unit_number"] = first_part if first_part.isdigit() else ""
```
Tag `62-FE-1001` → unit_number `"62"` ✓. Tag `FE-1001` → unit_number `""` ✓.

**Commit:** `eb3e1b2`

---

## [2026-06-24] #95 — Merged line_list branch (3 commits): equipment tag restore, Remarks fix, fluid/phase propagation, restructured headers

**Type:** merge
**Branch:** feature/graph ← origin/line_list
**Status:** shipped

**Why:** Friend's branch had 3 new commits improving line list extraction and column structure that weren't in local feature/graph.

**What:** Restored equipment tag in line list, fixed Remarks column, propagated fluid/phase fields, restructured headers into grouped hierarchy, removed test columns. Merged cleanly (no conflicts) into feature/graph.

---

## [2026-06-24] #94 — Merged dev branch (5 commits): stale-detection fix + memory-safe graph tracer + CONTRIBUTING.md

**Type:** merge
**Branch:** feature/graph ← origin/dev
**Status:** shipped

**Why:** Sir's dev branch had fixes for stale gpu_detections causing wrong graph nodes and OOM crash in graph tracer on large P&IDs.

**What:**
- `webapp/routers/jobs.py rerun_job`: clears `job.gpu_detections = None` on rerun so fresh inference always runs
- `webapp/pipeline_runner.py`: `_detections_are_stale()` — re-infers when stored YOLO labels are outside current `taxonomy.class_names()`
- `webapp/graph/tracer.py`: downscales pages >4000px before tracing, windowed per-component scan, frees intermediates — fixes OOM on dense pages
- `CONTRIBUTING.md`: branch/PR/2-approval workflow docs added
- Bruno API test collection added (`bruno/` folder)

**Result:** 1 conflict in SESSION_STATE.md (docs only) — resolved by taking dev's version.

---

## [2026-06-24] #93 — I/O List XLSX export crash fix: invalid `/` in sheet name

**Type:** bugfix
**Stage:** export
**Status:** shipped

**Why:** openpyxl raises `ValueError: Invalid character / found in sheet title` when sheet_name contains `/`. Customer templates had `"I/O List"` as the sheet name.

**What:** Changed `"I/O List"` → `"IO List"` in `default.json` and `muk.json`. Added defensive sanitizer in `io_list.py` (`raw_title.replace("/", "-")`) so any future template value with `/` is auto-fixed.

---

## [2026-06-24] #92 — Editable instrument tag in DatasheetDrawer header

**Type:** feature
**Stage:** review (UI)
**Status:** shipped

**Why:** Engineers need to correct extracted tags directly from the DatasheetDrawer panel without opening a separate edit flow. Previously only fields inside the datasheet body were editable.

**What:** Added pencil icon (Lucide `Pencil`, 16px) next to the tag `<h2>` in the DatasheetDrawer header. Click enters edit mode: large cyan input, Enter/✓ saves via existing `patchEntity()` endpoint, Esc/✗ cancels. On successful save, both `dsSections` and `originalEntity` local state are updated immediately so the display reflects the new value without a re-fetch. Save failure stays in edit mode with inline error. RE-READ TAG (AI) button behaviour unchanged.

**Files:** `webapp/frontend/src/studio/datasheet/DatasheetDrawer.tsx`

---

## [2026-06-24] #91 — PropertiesPanel: sticky Selected Element + scrollable elements list + remove vendor dropdown

**Type:** feature / bugfix
**Stage:** review (UI)
**Status:** shipped

**Why:** The CONFIRM/EDIT/OPEN DOCUMENT section was scrolling off-screen when the elements list was long, forcing users to scroll back up to interact with the selected element. Vendor dropdown was always empty ("No vendors found") and added noise.

**What:**
- Removed vendor dropdown, `vendorList`/`vendorLoading` state, vendor fetch `useEffect`, and `VENDOR_SUPPORTED`/`extractInstType` helpers from `PropertiesPanel.tsx`.
- Restructured `props-col` CSS: `overflow: hidden` on the panel, Selected Element section `flex: 0 0 auto` (always visible), Elements list section `flex: 1 1 0; overflow-y: auto` (scrolls independently). Scrollbar hidden via `scrollbar-width: none` + `::-webkit-scrollbar { display: none }`.

**Files:** `webapp/frontend/src/studio/PropertiesPanel.tsx`, `webapp/frontend/src/design/studio.css`

---

## [2026-06-24] #90 — Graph toggle button restored in Studio canvas toolbar

**Type:** bugfix
**Stage:** review (UI)
**Status:** shipped

**Why:** `setShowGraph` setter was dropped from `useState` destructuring in a previous session, permanently locking `showGraph = false` with no way to toggle it on.

**What:** Restored `const [showGraph, setShowGraph] = useState(false)`. Added `<Network>` icon button before Labels in the canvas toolbar, visible only when `graph` data exists for the job. Clicking toggles the graph node/edge overlay on/off.

**Files:** `webapp/frontend/src/studio/Studio.tsx`

---

## [2026-06-24] #89 — Canvas YOLO detection ↔ sidebar bidirectional click fix

**Type:** bugfix, frontend, backend
**Stage:** api_v1.py `_attach_entity_ids`, taxonomy.json, PidCanvas.tsx
**Status:** shipped (feature/graph branch)

**Why:** Three separate root causes broke bidirectional click (canvas→sidebar and sidebar→canvas) for valves, pumps, and motors.

1. **Pump/motor FIFO cross-assignment** (`taxonomy.json`): Both `Motor` and `Pump/Dwg Pump` had `sub_class: null` in `yolo_routing`, so step 3a (exact sub_class match) never fired. Both classes competed in step 3b (class-only fallback), with FIFO order causing pumps to be assigned motor entities and vice versa. Fix: set `sub_class: "PUMP"` / `sub_class: "MOTOR"` in `yolo_routing` — step 3a now matches each type to its own canonical entities exactly.

2. **Labels always visible after detKey fix** (`PidCanvas.tsx`): After `detKey = d.entity_id ?? null`, unmatched detections had `detKey=null`. Both `isSelected = (null === null)` and `isHovered = (null === null)` evaluated as `true`, making all detection labels render permanently. Fix: added `detKey !== null &&` guard to both comparisons.

3. **Valve bidirectional click broken** (`api_v1.py` step 3b): Canonical valve entities use customer notation codes (`VB`, `VCS`) while YOLO taxonomy uses different codes (`BV`, `CK`). Step 3a (exact sub_class match) found 0 valve matches. The old step 3b guard `if e.sub_class and e.sub_class.upper() != sub: continue` blocked the fallback — 0 of 329 valve detections got `entity_id`. Initial naive fix (remove guard entirely) worked for valves but broke pump/motor: excess pump detections started consuming motor entities. Final fix: `same_system = any(e.entity_class == cls and (e.sub_class or '').upper() == sub for e in entities)` — only apply class-only fallback when no canonical entity in the list uses the YOLO sub_class code. Different code systems → fallback allowed. Same code system (all entities consumed) → no fallback.

**Result (verified):**
- Valve canvas click → sidebar row shows real P&ID tag `8-VB-001 Block Valve 0.84` ✅
- Sidebar row click → Selected Element panel updates to `8-VB-002` ✅
- Pump canvas click → sidebar row shows `P-801-3A pump 0.88` (real tag, not YOLO label) ✅
- Matching rates: Valves 26/329 matched (was 0), Pumps 26/66 (unchanged), Motors 24/63 (unchanged)

---

## [2026-06-24] #88 — Equipment list: remove Equipment Tag column from Bulk Review

**Type:** bugfix, template
**Stage:** customer_templates (default.json, ronesans.json)
**Status:** shipped (feature/graph branch)

**Why:** The equipment list Bulk Review table showed a redundant "Equipment Tag" column that duplicated the tag/identity column already present. Removed `tag` field from `equipment_list.columns` in both `default.json` and `ronesans.json` customer templates.

---

## [2026-06-23] #86 — Unit number extraction for all equipment types (strainer, vessel, etc.)

**Type:** enrichment, bugfix
**Stage:** apply_enrichment_to_canonical (enrichment.py)
**Status:** shipped

**Why:** Strainers (62-S-151000) had no unit_number in the equipment list because `parse_equipment_tag()` only handles `P`/`M` class letters. Added a general `_EQUIP_TAG_RE` in enrichment that runs for any equipment entity missing `unit_number` — extracts the numeric portion from any tag format (`AA-X-NNNNNN` or `X-NNNNNN`). Covers strainers, heat exchangers, vessels, compressors, etc. automatically.

---

## [2026-06-23] #85 — Fix duplicate P&ID No. column in instrument index + equipment list

**Type:** bugfix, frontend, backend
**Stage:** BulkReviewScreen, overrides.py
**Status:** shipped

**Why:** `pid_number` appeared twice in the bulk review table for both instrument index and equipment list — once as the sticky identity column ("P&ID") and again as a template schema column ("P&ID No."). Root cause: the comment in BulkReviewScreen said `pid_number + sheet_number are in READ_ONLY_FIELDS` but they were never actually added. Backend fix: added `pid_number` and `sheet_number` to `READ_ONLY_FIELDS` in `overrides.py` — schema now returns `editable: false` for these fields, so `editableColumns` naturally excludes them. Also reverted a frontend workaround from the previous attempt.

---

## [2026-06-23] #84 — Equipment list: backfill pid_number for graph-extracted equipment

**Type:** enrichment, bugfix
**Stage:** apply_enrichment_to_canonical (enrichment.py)
**Status:** shipped

**Why:** Pump/motor entities added by graph extraction had empty `pid_number` while strainers (from Pass 1) had `MUK-62-1-15-1003-001-24C7`. Equipment list showed different P&ID references per row. Fix: after enrichment, find the most common `pid_number` among equipment entities and backfill it to any equipment row with an empty value. Uses equipment-scoped count (not all entities) to avoid picking up instrument/valve P&ID variants.

---

## [2026-06-23] #83 — Motor tag inference from adjacent pump + cross-unit service_description propagation

**Type:** pipeline, enrichment, bugfix
**Stage:** Pass 3 (extractor.py), graph enrichment (enrichment.py)
**Status:** shipped

**Why:** Job 15 showed pumps 62-P-151003/151004 missing from equipment list. Root cause: these pumps had tags in the P&ID but Pass 3 Vision API returned null. After investigation, Pass 3 was running but the motor symbol (n_067) is positioned directly above the pump symbol on the same tile — Vision API read the pump tag for both the pump AND the motor, so the motor tag was rejected (P- not valid for Motor class). Fix was two-part.

**Fix 1 — Motor tag inference from adjacent pump (extractor.py `apply_third_pass`):**
After the Vision API loop, for each Motor node that still has no tag, find the nearest Pump/Dwg Pump node by bbox-center euclidean distance. If within 600px (full-page coordinates), derive motor tag by substituting `-P-` → `-M-` in the pump tag. Validate with `_MOTOR_TAG_RE` before accepting. Rationale: pump+motor pairs in oil & gas are always co-located; the motor tag is the same unit number with M prefix.

**Fix 2 — Cross-unit service_description propagation (enrichment.py `apply_enrichment_to_canonical`):**
After the per-entity post-processing loop, group equipment entities by `unit_number`. If any entity in the group has a non-generic description (not "PROCESS PUMP"/"STANDBY MOTOR"/etc.) and others only have generic fallbacks, copy the real description to all. This lets "PW TRANSFER PUMPS" (found on the motor node tile) propagate to the matching pump entity.

**Result:** 62-P-151003/151004 and 62-M-151003/151004 all appear in equipment list; 62-P-151003 gets "PW TRANSFER PUMPS" propagated from motor node.

---

## [2026-06-23] #82 — Pump/motor template: instrument service_description + equipment duty/standby descriptions + location FIELD default

**Type:** pipeline, enrichment, deliverable
**Stage:** graph enrichment (apply_enrichment_to_canonical)
**Status:** shipped

**Why:** Equipment list showed "PUMP"/"MOTOR" only (no duty/standby context, no location). Instrument index/I/O list showed "Pressure Gauge/Glass on NA" for instruments not linked to a specific pump. Location column was empty ("-") for all equipment without an area code tag.

**What:**

Added `_INST_SERVICE_DESC` and `_INST_LOCATION` lookup tables in `enrichment.py` covering the oil & gas Motor & Pump Instrumentation template:
- PG/PI/PT/PIT → "PUMP PRESS" | LOCAL for gauges, FIELD for transmitters
- PDI/PDT → "STRAINER DIFF PRESS" | LOCAL/FIELD
- FT/FIT → "FLOW" | FIELD
- LT/LIT → "LEVEL" | FIELD
- LG → "SEAL FLUID LEVEL" | LOCAL
- LS/LSH/LSL → "LEVEL SWITCH [HIGH/LOW]" | FIELD
- TI/TE/TIT → "BEARING TEMP" | FIELD
- XT → "VIBRATION" | FIELD
- ZI → "CHECK VALVE STATUS" | LOCAL
- ZT → "VALVE POSITION" | FIELD
- II → "MOTOR CURRENT" | PANEL

Logic in `apply_enrichment_to_canonical()`:
- Instruments: only overwrites if `service_description` is empty or contains " on NA" (pipeline placeholder). Keeps existing good descriptions like "P-805A SUCTION PRESS".
- Instruments: sets `location` from lookup (LOCAL/FIELD/PANEL) if not already set.
- Equipment: replaces generic "PUMP"/"MOTOR" with duty/standby-aware description:
  - `is_duty=True` → "DUTY PUMP" / "DUTY MOTOR"
  - `is_standby=True` → "STANDBY PUMP" / "STANDBY MOTOR"
  - Neither → "PROCESS PUMP" / "PROCESS MOTOR"
  - Pass 3 Vision API found real text (e.g. "ACID AREA LOADING PUMP") → kept as-is
- Equipment: `location` defaults to "FIELD" when area_code is not available.

**Result (job 13):**
- All 22 instruments: "on NA" descriptions replaced (PG-8094A/B → "PUMP PRESS", PIT-8095A/B → "PUMP PRESS", LS-8057B → "LEVEL SWITCH"), all locations set (LOCAL for gauges, FIELD for transmitters)
- All 50 equipment: duty/standby labels (e.g. "DUTY PUMP", "STANDBY MOTOR"), location = "FIELD"
- P-821B kept "ACID AREA LOADING PUMP" (Pass 3 Vision API found actual text)

**Works for new PDF uploads:** enrichment runs as part of every job pipeline — new uploads automatically get these descriptions.

**Image rebuilt:** `docker compose build web` 2026-06-23.

**Files changed:** `webapp/graph/enrichment.py` — `_INST_SERVICE_DESC`, `_INST_LOCATION` tables + instrument loop + equipment post-process block.

---

## [2026-06-23] #81 — wet/dry + state 0/1 fix for no-area-code tags; generic service description fallback

**Type:** pipeline, enrichment
**Stage:** graph enrichment
**Status:** shipped

**Why two bugs in one entry — they share a root cause:**

1. **`_type_code()` regex only matched tags with an area code prefix** (`^\d+[-_]([A-Z]+)[-_]\d+`). Tags without an area code like `FIT-8025`, `LS-8050`, `PG-8078A` all returned `""` → `_wet_dry()` and `_states()` both returned `""` → all 22 job 13 instrument entities had empty wet/dry and state 0/1 in the I/O list.

2. **Equipment service_description was blank for 49/50 entities in job 13** — the P&ID has no printed description labels near most symbols, so Pass 3 can only find descriptions for the rare symbols that do have text nearby. A generic fallback ("PUMP"/"MOTOR" from `sub_class`) was missing.

**Fixes:**
- `_type_code()` now tries two patterns: `^\d+[-_]([A-Z]+)[-_]\d+` (with area code) then `^([A-Z]+)[-_]\d+` (without area code). Both formats are now handled.
- Generic fallback added in `apply_enrichment_to_canonical()`: if `service_description` is still empty after Pass 3 lookup and legacy promotion, use `sub_class.upper()` ("pump" → "PUMP", "motor" → "MOTOR").

**Result (job 13):**
- FIT/LIT/PG/PT/PIT → `wet='Wet'`, no state (analog transmitters — correct)
- LS → `wet='Dry'`, state_0='OFF / Open', state_1='ON / Closed'
- All 50 equipment entities have `service_description` (specific where P&ID has text, generic otherwise)

**Files changed:** `webapp/graph/enrichment.py` — `_type_code()`, `apply_enrichment_to_canonical()` post-process block.
**Image rebuilt:** yes — `docker compose build web` run 2026-06-23.

---

## [2026-06-23] #80 — Equipment list: service description + location fields

**Type:** pipeline, deliverable, template
**Stage:** graph enrichment, equipment list output
**Status:** shipped

**Why:** Equipment list CSV/XLSX had "Service Duty" column showing generic "Pump"/"Motor" YOLO class names — useless for engineers. Needed two real fields: (1) the service description text printed near the symbol on the P&ID (e.g. "SKIM OIL PUMPS", "ACID AREA LOADING PUMP"), and (2) the plant area/location the equipment belongs to.

**What:**

1. **Pass 3 prompt extended** (`prompts.py`): `THIRD_PASS_SYSTEM` now asks for two things per symbol — the tag AND the service description text. Response format changed from `{"node_id": "tag"}` to `{"node_id": {"tag": "...", "description": "..."}}`. Backward compat: string responses still handled.

2. **Pass 3 orchestrator extended** (`extractor.py`): Criteria changed from "nodes with no tag" to "nodes missing tag OR service_description" — so already-tagged nodes (existing jobs) get queried for descriptions in a re-run. Descriptions stored as `service_description` on graph nodes (uppercased, whitespace-normalised).

3. **Enrichment extended** (`webapp/graph/enrichment.py`):
   - `service_description` added to `_GRAPH_TO_FIELDS` — propagated from graph node to `entity.fields`
   - `_normalise_graph_field()` helper: normalises service_description (collapses newlines/whitespace) on every copy
   - Location auto-derived from `area_code` if not explicitly set (oil & gas convention: area code = location)
   - Legacy `service_duty` text promoted to `service_description` if it contains real content (not generic "Pump"/"Motor")

4. **Template updated** (`webapp/deliverables/customer_templates/default.json`): `fields.service_duty` → `fields.service_description` with header "Service Description".

**Result (jobs 13 and 14):**
- Job 13: `P-821B` → desc="ACID AREA LOADING PUMP", all others empty (P&ID has no description text near those symbols)
- Job 14: `62-P-151006` → desc="SKIM OIL PUMPS", loc="62" (area code from tag)
- Equipment list columns: Unit Number | Equipment Tag | Equipment Type | **Service Description** | Capacity | P&ID No. | **Location** | Manufacturer | Model No | Remark

**New PDF behaviour:** On a fresh upload, Pass 3 queries all pump/motor nodes for both tag and description in one API call — no extra pass needed.

**Files changed:** `prompts.py`, `extractor.py`, `webapp/graph/enrichment.py`, `webapp/deliverables/customer_templates/default.json`.

---

## [2026-06-23] #79 — Pass 3 prompt upgrade: full oil & gas tag structure knowledge

**Type:** pipeline, prompt
**Stage:** graph enrichment (Pass 3)
**Status:** shipped

**Why:** The original `THIRD_PASS_SYSTEM` prompt gave minimal guidance — just "pump tags start with P-". The Vision API was returning partial reads (`"M"`, `"P"`, `"P-8"`) that the stricter regex (Improvement 1 of #78) then had to reject. Better to prevent partial reads at the source by teaching the model the full tag structure upfront.

**What:** Rewrote `THIRD_PASS_SYSTEM` and `THIRD_PASS_USER_TEMPLATE` in `prompts.py`:
- Explains all three tag formats: with area code (`10-P-102A`), without area code (`P-801-1A`), and with sub-unit (`P-801-1A`)
- Documents each component: area code (AA), class letter (P/M), unit number (NNN), sub-unit (-SS), train suffix (X = A/C/E duty, B/D/F standby)
- Explicit rule: if you can see a prefix but not the full number, return null — no partial reads
- User template adds a one-line format reminder so the model sees the constraint on every tile call

**Files changed:** `prompts.py` — `THIRD_PASS_SYSTEM`, `THIRD_PASS_USER_TEMPLATE`.

---

## [2026-06-23] #78 — Oil & gas tag naming: stricter regex + component parser + duty/standby pairing

**Type:** pipeline, graph
**Stage:** graph enrichment (Pass 3)
**Status:** shipped (all 5 improvements complete)

**Why:** Pass 3 was accepting garbage like `"M"`, `"P"`, `"P-abc"` and had no understanding of tag structure (area code, unit number, train suffix, duty/standby roles). Equipment list showed tags but no semantic context. Needed oil & gas naming conventions baked into the pipeline.

**What (Improvement 1 — stricter regex):**
Replaced loose `^P-[\d\w-]+$` / `^M-[\d\w-]+$` with structured patterns:
```
_PUMP_TAG_RE  = re.compile(r'^(\d{2,4}-)?P-\d{3,6}(-\d{1,2})?[A-Z]?$')
_MOTOR_TAG_RE = re.compile(r'^(\d{2,4}-)?M-\d{3,6}(-\d{1,2})?[A-Z]?$')
```
Accepts: `P-801-1A`, `P-802A`, `10-P-102A`, `62-P-15100`. Rejects: `P`, `P-`, `P-1`, `P-12`, `P-abc`. Job 13: no previously-accepted tags rejected; 4 new tags found by Vision API now also pass.

**What (Improvement 2 — tag component parser):**
New `parse_equipment_tag(tag)` pure function in `extractor.py`. Single regex `_TAG_PARSE_RE` extracts: `area_code`, `equipment_class` (P/M), `unit_number`, `train_suffix`, `is_duty`, `is_standby`, `parallel_tag`. Duty/standby rule: A/C/E = duty, B/D/F = standby. Parallel tag reconstructed by flipping train letter (A↔B, C↔D, E↔F).

Called inside `apply_third_pass()` at tag-write time + backfill loop for already-tagged nodes. Job 13: 52 equipment nodes now carry all 7 parsed fields.

**What (Improvement 3 — duty/standby pairing):**
New `link_parallel_pairs(nodes)` pure function. Builds `tag→node_id` index, then for each node with a `parallel_tag` sets `parallel_node_id` to the matching partner node's id. Partners with no matching node: `parallel_node_id` left null (no error). Called after backfill, before `json.dump`.

Job 13 result: 33 nodes paired (duty↔standby), 17 unpaired duty (standby not detected by YOLO), 4 unpaired standby (duty not detected). 5 technically one-directional pairs — all are tile-overlap duplicate graph nodes (same physical pump in 2 tiles); canonical.json dedup already handles this at the entity layer.

**What (Improvement 4 — related instruments):**
New `link_related_instruments(nodes, canonical_entities)` pure function in `extractor.py`. For each pump/motor node with a `unit_number`, searches canonical.json instrument entities for any whose tag contains that unit number as a substring. Train-suffix filtering: if equipment has train suffix A, instruments ending with B are excluded; instruments with no train suffix (shared/common) match all trains. Writes `related_instruments: [tag, ...]` to each equipment node. Called after `link_parallel_pairs()`, reads canonical.json from job dir.

Job 13 result: 12 nodes with ≥1 related instrument (e.g. M-8078A→PG-8078A, P-805A→LS-8050+LS-8057A, P-804A→LIT-8049). 50 nodes empty — their 3-digit unit numbers (801, 802…) don't appear in this job's 4-digit instrument loop numbers, which is correct for this P&ID.

**Files changed:** `extractor.py` (3 new constants `_TAG_PARSE_RE`, `_DUTY_TRAINS`, `_STANDBY_TRAINS`, `_TRAIN_FLIP`; 4 new functions `parse_equipment_tag`, `link_parallel_pairs`, `link_related_instruments`; backfill + pairing + instrument linking wired into `apply_third_pass()`).

---

## [2026-06-23] #77 — Pass 3 Vision API pump/motor tag lookup + graph_status field + dedup

**What:** Three related improvements to the equipment pipeline shipped together.

1. **Pass 3 (extractor.py)** — after graph enrichment, queries the Vision API per tile for untagged Pump/Motor nodes. Sends each node's tile-relative bbox and asks for the nearby P- or M- prefixed tag. Validates with regex before writing to `canonical_graph.json`. Job 13: 62 untagged nodes → 41 tagged.

2. **Equipment tag propagation (enrichment.py)** — `apply_enrichment_to_canonical()` now copies `tag` from graph nodes into canonical.json equipment entities (new `equip_tags_applied` stat). Deduplication step removes tile-overlap duplicates by keeping the highest YOLO confidence node per tag (new `equip_deduped` stat). Job 13: 62 entities → 54 after dedup (8 duplicates removed).

3. **`graph_status` field (models + pipeline)** — new `graph_status` column on Job (`pending/running/done/failed`). The overall job `status` now only flips to `done` once BOTH the CSV pipeline AND graph enrichment complete. Graph failure → `graph_status = failed`, `status = failed`. Pass 3 Vision API failure is non-fatal within the graph stage (logs but continues). Dashboard shows a second status pill for graph enrichment; `failed` jobs remain openable and all CSV deliverables stay accessible.

**Files:** `extractor.py`, `prompts.py`, `webapp/graph/enrichment.py`, `webapp/pipeline_runner.py`, `webapp/models.py`, `webapp/database.py`, `webapp/routers/api_v1.py`, `webapp/routers/jobs.py`, `webapp/frontend/src/dashboard/types.ts`, `webapp/frontend/src/dashboard/ProjectCard.tsx`

**Why:** Pumps/motors had no tag numbers in the equipment list (not in valve_list.csv/instrument_index.csv); tile-overlap caused duplicate YOLO detections; job showed "Done" before graph enrichment finished leaving wet/dry and state 0/1 invisible to users.

---

## [2026-06-23] #76 — State 0/1 labels standardized + YOLO equipment without tags in equipment list

**Type:** feature, enrichment
**Stage:** graph enrichment, equipment list
**Status:** shipped

**Why (state labels):** State 0/1 values were showing inconsistent labels ("Normal"/"Alarm" for switches, "Closed"/"Open" for valves, "Stop"/"Run" for motors). Customer wants a uniform ISA-style format: **"0 = OFF / Open"** for state_0 and **"1 = ON / Closed"** for state_1 across all binary-state devices.

**What (state labels):** Updated `_states()` in `webapp/graph/enrichment.py`. All non-analog binary device state pairs now return `("0 = OFF / Open", "1 = ON / Closed")`. Transmitters/analog remain `("", "")`.

**Why (YOLO equipment):** Motors and pumps are detected by YOLO but often have no tag number in the P&ID, so they are never extracted into `equipment_list.csv` by the Vision API, and never appear in the Equipment List deliverable.

**What (YOLO equipment):** In `apply_enrichment_to_canonical()` (called after YOLO runs), read `canonical_graph.json` for nodes with class "Motor" or "Pump/Dwg Pump" where `entity_id` is None (no tag match). Append each as a new `entity_class="equipment"` entity to `canonical.json` with `tag=None`, deterministic UUID5, de-duplicated by bbox. These then appear in the Equipment List deliverable with type "motor"/"pump" and blank service_duty. Re-run-safe: bbox-keyed de-duplication prevents doubles.

---

## [2026-06-22] #74 — io_output fallback: 4-20mA for all transmitters

**Type:** Feature
**Stage:** deliverables, pipeline
**Branch:** feature/graph

Added a 3-line fallback in `pipeline_emitter.py:_build_instrument_entities`: after the vendor API enrichment block, if `fields["io_output"]` is still empty and `fields["io_type"] == "AI"`, default to `"4-20mA"`. `io_type="AI"` covers all transmitter and primary-element codes (T-suffix and E-suffix in `_LAST_LETTER_IO`): FT, PT, TT, LT, FE, TE, PE, LE, FIT, PDIT, PZIT, etc.

**Why:** Vendor API returns 404/422 for some instrument type codes (FE, PDI, PZIT not in catalog). Without the fallback, those instruments show blank io_output even though 4-20mA is the universal standard signal for all analog transmitters in the field.

---

## [2026-06-22] #73 — vendor_match_client crash fix: new API response format

**Type:** Bugfix
**Stage:** deliverables, pipeline
**Branch:** feature/graph

Two bugs fixed in `webapp/deliverables/vendor_match_client.py`:

1. **List-typed match guard:** API was returning `matches[0]` as a list (not a dict) for some instrument types. `match.get("piping_class")` → `AttributeError: 'list' object has no attribute 'get'`. This crashed `write_canonical_for_job` entirely — all equipment entities were silently dropped from canonical.json (equipment_list.csv had 2 pumps; canonical.json had 0). Fix: `if not match or not isinstance(match, dict)` guard returns None instead of crashing.

2. **New API response schema:** Vendor API switched from `{ "matches": [...] }` to `{ "data": [...] }` (list for all-products) and `{ "data": {...} }` (dict for single-product). Updated parsing: `raw = data.get("data") or data.get("matches") or []`; if raw is list → `raw[0]`; if dict → use directly. Both old and new schema now handled.

**Why:** Silent crash in write_canonical_for_job was the root cause of equipment entities never appearing in canonical.json for jobs processed after the API format change. Also the root cause of wet_dry/state_0/state_1 being None after reruns (canonical.json was overwritten by write_canonical_for_job mid-pipeline but enrichment couldn't apply because the crash stopped canonical.json from being written at all).

---

## [2026-06-22] #72 — Auto-push enriched graph fields to entity_overrides (XLSX/CSV export fix)

**Type:** Feature
**Stage:** graph, pipeline, deliverables
**Branch:** feature/graph

Added `push_enrichment_to_overrides(job_id, job_dir, user_id, db)` to `webapp/graph/enrichment.py`. Called in `pipeline_runner.py` right after `enrich_graph()` succeeds. Upserts entity_overrides for the 8 enriched fields so the XLSX/CSV export endpoint (`/api/v1/jobs/{id}/export/io_list/xlsx`) picks them up via `load_canonical_with_overrides()` without any code change to the export layer.

Field mapping: `wet_dry → fields.wet_dry`, `state_0 → fields.state_0`, `state_1 → fields.state_1`, `interlock → fields.interlock`, `alarm_hh → fields.alarm_high_high`, `alarm_h → fields.alarm_high`, `alarm_l → fields.alarm_low`, `alarm_ll → fields.alarm_low_low`. Skips empty values. Idempotent — updates existing override only when value changes.

**Why:** Export endpoint reads canonical.json + entity_overrides (not canonical_graph.json). Without this push step, enriched fields appeared in Bulk Review UI (which reads graph directly) but were blank in XLSX/CSV downloads.

---

## [2026-06-22] #71 — Graph node enrichment wired into pipeline (Wet/Dry, State 0/1, Interlock, Alarms)

**Type:** Feature
**Stage:** graph, pipeline
**Branch:** feature/graph

Added `webapp/graph/enrichment.py` — called automatically after `extract_graph()` in `pipeline_runner.py`. Populates 8 fields on every canonical_graph.json node:
- **Wet/Dry**: from ISA instrument type code extracted from tag (FT/PT/TT/LT → Wet; BV/DB/CK/switch codes → Dry; sight glass GL → blank)
- **State 0/State 1**: from device category (valve → Closed/Open; switch/alarm → Normal/Alarm; motor/pump → Stop/Run; transmitter → blank)
- **Interlock**: inst_sis nodes → Yes; nodes whose connected_to includes an inst_sis tag → Yes
- **Alarm HH/H/L/LL**: OCR on expanded bbox (80px pad, 2× scale, sharpen) from page_0_full.png; canonical.json alarm fields used as fallback/override; instrument nodes only (valves excluded)

Non-fatal: enrichment failure logs but never blocks job completion. OCR gracefully degrades if RapidOCR unavailable. All 8 fields are empty string (not null) on nodes where the rule doesn't apply.

**Why:** I/O List Bulk Review needs these fields pre-populated from the graph. Previously required a one-off script per job; now runs automatically on every pipeline execution.

---

## [2026-06-22] #70 — I/O List 31-column spec + template_loader cache fix

**Type:** Feature + Bugfix
**Stage:** deliverables, frontend
**Branch:** feature/graph

All 3 customer templates (default, muk, ronesans) io_list section replaced with the canonical 31-column spec in the user-defined order: P&ID No. → Tag No. → Loop No. → Instrument Type → Service Description → Line No. → Equipment No. → Location → IO Type → IO Output → Signal Type → External Power Supply → System → Sub System → Wet/Dry → State 0 → State 1 → Multi-Cable Type → Junction Box/Panel → Junction TB-1/2 → Marshalling Cabinet TB Strip/TB-1/2 → Alarm HH/H/L/LL → Explosion Certificate → Interlock → Remark.

Removed: Pair No., Control Action. Added: Signal Type, State 0, State 1, Explosion Certificate.

**Bug fixed:** `TemplateLoader.load()` checked `_cache` before calling `_load_raw()`, so the mtime-based invalidation never fired after the first load — template edits were invisible until server restart. Fix: always call `_load_raw()` first (which handles the mtime check and pops `_cache` when the file changes), then check `_cache`.

---

## [2026-06-22] #69 — Equipment list pipeline wired end-to-end

**Type:** Feature
**Stage:** pipeline, deliverables
**Branch:** feature/graph
**Status:** shipped

**Why:** The equipment context pre-pass (`extract_equipment_context`) was already extracting equipment tags and names from every P&ID page, but the data was discarded after the instrument extraction pass completed. The Equipment List tab in bulk review and Studio was always empty.

**What:**
- `instrument_prompts.py` — `EQUIPMENT_CONTEXT_PROMPT` now requests an `equipment_type` field alongside `equipment_tag`/`equipment_name`. Eleven known types: pump, motor, compressor, heat_exchanger, reducer, expander, eccentric, flange, vessel, strainer, other.
- `extractor.py` — `extract_equipment_context` passes through `equipment_type`. `extract_instruments` now returns a `(instruments, equipment_items)` tuple instead of just instruments. Equipment items are deduplicated by tag across pages before return.
- `equipment_writer.py` (new) — writes extracted equipment to `equipment_list.csv` (columns: Tag, Equipment Name, Equipment Type, P&ID No).
- `pipeline.py` — unpacks the new tuple, saves `equipment_list.csv` as Stage 5d (after instrument datasheets).
- `pipeline_emitter.py` — added `_KNOWN_EQUIPMENT_TYPES` constant, `_build_equipment_entities` reader (maps CSV → `entity_class="equipment"` CanonicalEntity with `sub_class=equipment_type`, `fields.equipment_type`, `fields.service_duty`). `write_canonical_for_job` now reads all three CSVs. `EmitResult` gains `equipment_count`.

**Limitation:** Existing jobs don't have `equipment_list.csv` on disk — they show empty Equipment List until re-run.

---

## [2026-06-22] #68 — Template loader: mtime-based cache invalidation

**Type:** Bugfix
**Stage:** deliverables, webapp
**Branch:** feature/graph
**Status:** shipped

**Why:** `TemplateLoader` was a module-level singleton with a process-lifetime cache. Editing any `customer_templates/*.json` file had zero effect on the running server — old columns were served until the web container was restarted. This caused the I/O List new columns (and any future template edits) to be invisible in bulk review and admin custom columns.

**What:** `TemplateLoader._load_raw` now calls `path.stat().st_mtime` on every invocation. If the mtime has changed since the last read, it reloads the JSON and invalidates the parsed `TemplateConfig` cache entry. Both `_raw_cache` and `_cache` stay coherent. Template edits on disk now take effect within one request, no restart needed.

**Note:** `_raw_cache` values are now `(mtime, raw_dict)` tuples instead of plain dicts — don't compare them directly as dicts.

---

## [2026-06-22] #67 — I/O List: 10 new columns added to all customer templates

**Type:** Enhancement
**Stage:** deliverables, templates
**Branch:** feature/graph
**Status:** shipped

**Why:** User requested additional field capture on the I/O List for Wet/Dry classification, system/sub-system grouping, junction terminal block numbers, marshalling cabinet terminal block numbers, interlock, and control action.

**What:** Added 10 new columns to `io_list` in all three customer templates (default.json, muk.json, ronesans.json), inserted before Remark:

| Field | Header |
|---|---|
| `fields.wet_dry` | Wet / Dry |
| `fields.system` | System |
| `fields.sub_system` | Sub System |
| `fields.junction_tb_1` | Junction TB-1 |
| `fields.junction_tb_2` | Junction TB-2 |
| `fields.marshalling_tb_strip` | Marshalling Cabinet TB Strip |
| `fields.marshalling_tb_1` | Marshalling Cabinet TB-1 |
| `fields.marshalling_tb_2` | Marshalling Cabinet TB-2 |
| `fields.interlock` | Interlock |
| `fields.control_action` | Control Action |

Fields are visible immediately in Bulk Review (I/O List tab) and Admin → Custom Columns (I/O List section). Values are empty until instruments are edited or re-extracted with these fields populated.

---

## [2026-06-18] #66 — Graph overlay: node labels + click-to-see-connections in Studio

**Type:** Enhancement
**Stage:** shipped
**Branch:** feature/graph
**Status:** done

**Why:** User wanted the digital-twin graph view (labeled nodes + connection inspection) directly on the P&ID canvas without visiting a separate /graph/twin URL.

**What:**
- `GraphLayer.tsx`: added `showLabels`, `onNodeClick`, `selectedNodeId` props. Each node is now a `<g onClick>` wrapping the circle + optional label `<text>` + selection ring. Clicking ANY node (even unmatched) fires `onNodeClick`.
- `PidCanvas.tsx`: passed `showLabels={showAllLabels}`, `onGraphNodeClick`, `selectedGraphNodeId` through to GraphLayer.
- `Studio.tsx`: added `selectedGraphNodeId` state, `handleGraphNodeClick` handler, `selectedNodeConnections` useMemo (computes connected edges for selected node from `graph.edges`). Floating connection panel rendered inside the canvas `<section>` at `position:absolute; bottom:52px; left:16px` — shows tag, class, all connected node tags with method color indicators. Panel dismisses on close button or second click of same node.
- Labels toggle (existing "Labels" button) now also shows graph node tag text on the P&ID.
- Frontend built locally (`npm run build` in webapp/frontend/) then copied into running container with `docker cp` (bypassing Docker layer cache).

**Result:** Graph button → P&ID with colored dots + edges. Labels button → tag text on every symbol. Click dot → connection panel. No separate /twin page needed.

---

## [2026-06-18] #65 — Spatial digital twin visualization: GET /jobs/{id}/graph/twin

**Type:** feature, security
**Stage:** graph, webapp
**Branch:** feature/graph
**Status:** shipped (commits 3e41285 + 4eb73d9)

**Why:** Neo4j Browser's force-directed layout scattered nodes randomly — no spatial relationship to the original P&ID drawing. User needed a view where instruments appear at their actual page coordinates, matching the physical drawing layout (a true "digital twin" view).

**What:**
1. **`/graph/twin` endpoint** — `webapp/routers/graph.py`: `GET /{job_id}/graph/twin` returns a standalone HTML page with an SVG viewport (1400px wide). Reads Neo4j Metadata (page_w, page_h) to compute scale; reads auto Nodes (x/y from bbox center), auto PIPE edges, user PIPE edges. Nodes positioned at `raw_x / page_w * 1400`. Colour-coded by class family: valve=#ef4444, instrument=#8b5cf6, equipment=#10b981. Blue lines for auto pipes, orange dashed arrows for user pipes. Hover tooltip shows id/tag/class/confidence. Falls back to an error HTML page if Neo4j has no data (schema_version mismatch).
2. **Node coordinates in Neo4j** — `_write_nodes` in `webapp/graph/neo4j_writer.py` now stores `x` (cx of bbox), `y` (cy of bbox), and `label` (tag or class or id) on every auto Node. Required for the spatial layout to work.
3. **XSS fix** — `from html import escape as _he`; all Neo4j string values (label, id, class, confidence, exception message) escaped before SVG/HTML interpolation. Automated security review found raw interpolation in initial commit.

**Result:** Job 11 → 154 nodes rendered at real P&ID coordinates, 127 auto pipes, 1 user pipe. Visual layout matches the drawing topology.

**Notes:** The `/graph/twin` endpoint is read-only and stateless — no writes, no auth token needed (same auth as other graph routes). SVG_W constant (1400) in graph.py could become a query param if multi-zoom is needed later.

---

## [2026-06-18] #64 — Neo4j graph migration: all graph data (auto + user) now in Neo4j

**Type:** architecture, feature
**Stage:** webapp, graph
**Branch:** feature/graph

**Why:** `canonical_graph.json` + `graph_corrections` PG table are two separate sources; delivering a unified graph required merging at read time in Python. With Neo4j, a single Cypher query can reconstruct any P&ID's full graph (auto-detected + user-drawn edges in one store), enabling future Cypher-native queries (path finding, loop tracing, isomorphism checks).

**What (6 steps, all completed this session):**
1. Neo4j connection verified (`neo4j:5.18-community` in docker-compose.yml).
2. **Auto graph → Neo4j:** `webapp/graph/neo4j_writer.py` — `write_graph_to_neo4j()` called from `graph/pipeline.py` after every `canonical_graph.json` write. Stores Metadata (schema_version='2'), Nodes (source='auto'), PIPE relationships (source='auto').
3. **User edges → Neo4j:** `write_user_edge_to_neo4j()` called from `webapp/routers/edges.py` after every PG commit. Source='user_added'; freepoint endpoints get :FreePoint label.
4. **GET /graph reads from Neo4j:** `read_graph_from_neo4j()` called first; returns None on any failure → router falls back to JSON+PG merge silently. Response shape is identical to the fallback path (no frontend change).
5. **Full round-trip verified:** job 11 pipeline rerun → Neo4j populated → GET /graph serves from Neo4j → draw edge → fresh GET returns user edge with correct shape.
6. **Playwright-equivalent test:** `tests/e2e/test_neo4j_round_trip.py` (2 tests pass).

**Key design decisions:**
- **Delete-before-write for auto data:** `_delete_auto_data` removes source='auto' Nodes/PIPEs/Metadata before writing fresh auto data. Prevents duplicate edges when pipeline runs produce different edge IDs for the same endpoints (graph structure is non-deterministic across runs). NEVER touches source='user_added'/'placeholder'.
- **schema_version='2' sentinel:** written to Metadata on every write; `read_graph_from_neo4j` returns None if absent or != '2'. Old data (pre-migration) auto-falls back to JSON+PG.
- **`fallback_used` in stats is graph-extraction LLM fallback** (not Neo4j path indicator). Both code paths inherit it from `canonical_graph.json`.
- **Known gap:** DELETE /edges removes from PG but not Neo4j; stale deleted edges persist until next pipeline run's `_delete_auto_data`. Tracked for a future cleanup step.

**Files changed:**
- `webapp/graph/neo4j_writer.py` — new file (writer + reader)
- `webapp/graph/pipeline.py` — `write_graph_to_neo4j(graph)` call inside `if write_file:`
- `webapp/routers/graph.py` — 4-line Neo4j-first block before JSON+PG fallback
- `webapp/routers/edges.py` — `write_user_edge_to_neo4j` call after PG commit (status + group_id params)
- `tests/e2e/test_neo4j_round_trip.py` — new integration test

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

## [2026-06-26] #67 — Graph ground-truth anchor + is_isomorphic scoring harness

**Type:** feature, architecture
**Stage:** graph, validate
**Status:** shipped (code on branch `feat/graph-ground-truth-scoring`; PR pending). Job-43 GT seeded but **NOT yet human-verified**.

**Why:** After #66 the graph looked reasonable (job 43: 128 nodes / 155 edges) but topology was **spot-checked, not measured** — no ground-truth graph existed, so we couldn't answer "did a change make topology more or less correct?" objectively. CLAUDE.md's long-term headline metric is graph isomorphism vs human truth, and the Self-Learning **Phase 2** eval gate is blocked on it (must refuse to promote a model if topology regresses). Decision (brainstorm): build the **metric first**, defer cross-tile stitching until the metric shows the seam gap is lossy.

**What:**
- `webapp/graph/scoring.py` (pure, DB-free, importable by the Phase 2 gate): `align_nodes()` — entity_id → tag → spatial (two sub-passes: IoU≥0.5 then nearest-centroid≤px) node alignment; `score_graph()` → `GraphScore` with node + **undirected edge** precision/recall/F1, **directed-agreement** (secondary, over GT directed edges only — never affects undirected F1), strict `networkx.is_isomorphic` gate (wrapped, never raises), connectivity stats, explicit missing/extra edge lists, `to_dict()`.
- `webapp/scripts/score_graph.py` — thin CLI: `--job-id` (DB-free glob of `job_outputs`, flat ≤39 + org-scoped ≥40), `--graph`/`--gt`, `--json`, `--seed`.
- `tests/graph_ground_truth/job_43.json` — seeded from the dev #66 extraction (`meta.status=seeded-uncorrected`).
- Tests: `tests/unit/test_graph_scoring.py` (19). Host run: 108 graph-suite pass (5 `test_graph_tracer` fail only because `skimage` isn't installed locally — env, not a regression; passes in container).

**Result:** Harness self-check on the real 128-node graph: node/edge **F1 = 1.000, is_isomorphic = True, 0.3s** (confirms `is_isomorphic` scales to 128 nodes). Early measurement: job 43 is **36 connected components / largest 0.11** — heavily fragmented despite "92% of nodes have an edge" (#66's metric counted non-floating nodes, not components). That fragmentation is the first quantitative signal that the **deferred cross-tile stitch pass** is likely warranted.

**Notes:** (1) The seeded GT is a verbatim copy of the extraction — **a human must hand-correct it against the source P&ID** (add cross-seam edges, fix tags) and set `status=verified` before it is real ground truth; self-score of the un-corrected seed is trivially perfect by construction. (2) `align_nodes` matched-once + IoU-then-centroid sub-passes have a discriminating regression test. (3) Minor/deferred: CLI `--root` not wired; `_connectivity`/`_mapped_undirected` use falsy-string guards (real ids non-empty); no cross-id end-to-end score test yet (Task 1 covers the cascade). (4) Next: hand-correct job-43 GT → measure the seam gap → decide on the stitch pass; then wire `score_graph` into the Phase 2 eval gate. (5) Spec `docs/superpowers/specs/2026-06-26-graph-ground-truth-scoring-design.md`, plan `docs/superpowers/plans/2026-06-26-graph-ground-truth-scoring.md`.

---

## [2026-06-24] #66 — Graph edges: chunked structured LLM fallback + entity node-dedup

**Type:** bugfix, threshold-tune
**Stage:** graph
**Status:** shipped (code on branch `fix/graph-edge-quality`; job 43 graph re-persisted on dev; deploy pending)

**Why:** After #65 fixed detections, job 43's graph had 207 nodes but only **5 edges / 4 wrong** — the topology (our headline graph-isomorphism metric) was essentially empty. Root causes: (1) the LLM fallback fired correctly (`5 < 0.3·207`) but a single 207-node prompt returned output `_parse_pairs` couldn't read → *"no usable connections"* → 0 edges; (2) tile-overlap produced ~79 duplicate nodes for the same entity (e.g. `61-HS-00471` ×8), so even good edges would wire an instrument to its own duplicate boxes. User goal confirmed: **topological correctness** (which node connects to which), API calls acceptable.

**What:**
- `webapp/graph/fallback.py` — `run_fallback` now does a **chunked, structured** pass when `job_dir`+`page_width`+`page_height` are given: one call per 3×3 tile holding ≥2 nodes, using the existing per-tile PNG + that tile's node subset (bboxes localized to the crop), with OpenRouter `response_format: json_schema` (`_CONNECTIONS_SCHEMA`) so output is always parseable. Pairs merged + deduped by unordered node-pair across tiles; per-tile failure is non-fatal. Legacy single-shot path preserved when those args are absent (existing tests untouched). `_parse_pairs` extended to read `{"connections":[…]}`/`{"edges":[…]}` objects. New helpers: `_select_nodes_in_tile`, `_build_region_prompt`, `_connections_for_region`, `_collect_pairs_{single,chunked}`.
- `webapp/graph/pipeline.py` — new `dedupe_nodes_by_entity()` (Step C.5, before resolve/fallback): collapse nodes sharing `entity_id` to the highest-confidence box (tiebreak largest bbox); untagged nodes kept. Wired the chunked fallback by passing `job_dir`+page dims.
- Tests: `test_graph_node_dedup.py` (5) + chunked fallback tests in `test_graph_fallback.py` (5). Full suite **401 pass** (1 pre-existing unrelated failure).

**Result (job 43, live on dev):** nodes **207→128** (44 entities + 84 untagged), edges **5→155**, `fallback_used=True`, **118/128 nodes connected (92%)**, ~163s, no warnings beyond the dedup note. Sample connections are real loops (`FY→FV→FIC`). Re-persisted (`canonical_graph.json` + graph DB).

**Notes:** (1) ~9 vision-API calls/job on dense pages (skips <2-node tiles) — fine per the "API ok" decision; revisit if cost matters. (2) **v1 relies on the 20% tile overlap for cross-tile pipes** — no separate boundary-stitch pass yet; add if cross-region connectivity looks lossy. (3) 84 untagged nodes are NOT deduped (no entity_id to group on) — optional future IoU dedup. (4) No human ground-truth graph yet, so topology is spot-checked not measured — anchor one when Phase 2's eval gate lands. (5) Other healed jobs (1/38/39/41/42) still have pre-#66 graphs; refresh via re-process or a backfill after deploy.

---

## [2026-06-24] #65 — Stale gpu_detections never refreshed → sparse/wrong graphs; + graph-tracer OOM fix

**Type:** bugfix
**Stage:** graph, webapp
**Status:** shipped (code on branch `fix/stale-gpu-detections-reinfer`; dev DATA healed live; recurrence fix pending deploy)

**Why:** User report: job 43 (a heavily-trained P&ID) showed only **7 graph nodes + 4 wrong edges**, and re-processing didn't help. Read-only investigation: deliverables were fine — `canonical.json` had **44 entities** (API/`extractor.py`) — but the *graph* is built from `Job.gpu_detections` (YOLO), and job 43's stored detections were **7 stale boxes from a dead old model** (obsolete classes `valve_gen`/`valve_gl`, legacy GPU-worker schema). Live v1-11 finds **268** on the same page. Root causes: (1) `rerun_job` cleared outputs but **not `gpu_detections`**, so re-run's `_run_inplace_inference` skip-guard saw old rows and skipped; (2) the `#63` backfill skipped any job that already had detections. Audit: **6/56 jobs stale** (1, 38, 39, 41, 42, 43).

**The masked bug:** healing job 43 to the real 268 detections then **OOM-killed** graph extraction on the 3.8 GB dev box (dmesg confirmed, ~1.7 GB RSS). The 7-node graph had "worked" only because 7 boxes were cheap. The OpenCV tracer allocated full-res arrays incl. an int32 `connectedComponents` label map (~350 MB on an 8000px page) and rescanned it once **per component** via `np.where(_labels==label)` — memory + O(components×pixels) time blowup (>10 min hang).

**What:**
- `webapp/graph/tracer.py` — `OpenCVLineTracer` downscales pages whose longest side > `max_trace_dim` (default 4000) before tracing and scales segment coords back to page-pixel; per-component pixel scan is **windowed** to each component's stat-bbox (O(component) not O(page)); dropped the defensive `binary.copy()` and frees intermediates. Behavior-preserving on small (<max_trace_dim) fixtures.
- `webapp/pipeline_runner.py` — new `_detections_are_stale()` (any label outside current `taxonomy.class_names()` ⇒ stale; legacy *schema* with current names is NOT stale, since the live GPU worker still writes that shape). The skip-guard re-infers stale rows instead of trusting them.
- `webapp/routers/jobs.py` — `rerun_job` now clears `job.gpu_detections = None` so re-process forces fresh inference.
- Tests: `tests/unit/test_stale_detections.py` (6), `test_graph_tracer.py` (+2 large-image/downscale). Full suite 391 passed (1 pre-existing `test_sheets_empty_when_no_tiles` failure, unrelated).

**Result:** All 6 stale jobs healed on dev (re-infer + rebuilt graph, no OOM): **job 43 nodes 7→207** (61 ball valves, 52 field inst, 43 BPCS, 19 SIS…), 38→202, 1→135, 41→93, 42→98, 39→76. Detection overlays now correct everywhere. Heal ran with the fixed tracer hot-copied into the dev container; **healed data is durable** (EBS + graph DB); the recurrence fix lands on deploy.

**Notes:** (1) **Edge tracing is still weak on dense pages** — job 43 got only 5 CV-traced edges for 207 nodes and the LLM-fallback gate did NOT fire (it fires for the lower-node jobs). Downscaling may also thin 1–2px pipe lines. Follow-up: tune `fallback.should_use_fallback` for high node counts + revisit edge recall. (2) Model is NOT the deliverables bottleneck — `extractor.py` (API) already finds all entities; YOLO only feeds overlay+graph. Relevant to Self-Learning Phase 2 sequencing. (3) Heal/audit scripts in scratchpad `heal2.py` / `audit_dets.py`.

---

## [2026-06-22] #64 — Bulk-review side panel shows the FULL per-instrument datasheet

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** User report: in the datasheet Bulk Review, the right side panel showed only ~6 fields (the customer-template list columns: Tag/Service/P&ID/Manufacturer/Model/Part No.), even though #59/#60 added the complete per-type IDS field set. Each row is an individual instrument datasheet — clicking a row should surface that one instrument's full fields, chosen automatically by its type, and edits must persist. (Download was already comprehensive — `datasheet.py` emits one XLSX sheet per instrument via `get_ids_sections_for_type`; verified one sheet/instrument, 57 Common fields for generic types, 171 for CV.)

**What:** Frontend reuses the existing `GET /jobs/{id}/entities/{eid}/datasheet` (field set auto-selected from `sub_class`). Extracted the drawer's `SectionedDatasheet` + cells + `valueToString`/`stringToValue`/`isPidSourced` + new `seedDatasheetEditValues`/`computeDatasheetDirty` into shared `studio/datasheet/sectioned.tsx`; `DatasheetDrawer.tsx` now imports them (no logic dup). New `studio/datasheet/DatasheetPanel.tsx` (self-contained fetch+edit+save via `patchEntity`) renders in `BulkReviewScreen` `br-detail` for the datasheet deliverable only (others keep the field-list `<dl>`); keyed by entity_id so state resets per row. Grid responsive (`auto-fill minmax(180px)`); `.br-body.ds-wide` (560px panel) when datasheet active.

**Crux found during dev verification:** real canonical `sub_class` is the **descriptive name** ("FLOW TRANSMITTER", "PRESSURE GAUGE", "DIFFERENTIAL PRESSURE INDICATING TRANSMITTER"), NOT the ISA codes (`ft`/`pt`/`pg`) the alias table keyed on — so EVERY real instrument resolved to Common-only (57 fields); the #59/#60 per-type datasheets had only ever been exercised with code-form sub_classes in tests. Fix: `normalize_subclass` does exact-alias first (added `pdit/pdt/fdit→PT`, `pdi→PG`), then keyword classifier `_match_descriptive` (transmitter+temperature→TT; transmitter+pressure/flow/diff→PT; gauge/indicator +pressure→PG / +temperature→TG / +flow→FE; thermowell→TW; safety|relief valve→PSV; restriction orifice→RO; flow element/orifice→FE; control valve→CV; thermocouple/rtd→TE). Ambiguous (analyzer, alarm, hand switch, level transmitter, generic flow controller/valve) → None → Common, never wrong fields.

**Also fixed (found in live dev verify):** `BulkReviewScreen.fetchRows()` reset the selected row to entity[0] on every refresh, so saving in the side panel (and grid cell edits) jumped the user back to row 0 — now preserves `selectedId` when it still exists.

**Result:** Real dev instruments now resolve to full type sets — FLOW/PRESSURE/DP TRANSMITTER→PT (129), TEMP TRANSMITTER→TT (101), PRESSURE GAUGE/INDICATOR→PG (112), FLOW ELEMENT/ORIFICE→FE (85), PSV→133, RESTRICTION ORIFICE→RO (86). Bulk side panel shows all sections/fields, editable + persisted. 123 vitest (2 new) + 11 ids_schema (2 new) + datasheet deliverable tests pass; tsc + vite build clean. **Live-verified on dev** (jobs 49/55): FE→85, PT→129, PSV→133 sectioned fields render; edit→Save persists (EDITED badge survives re-fetch); no row-jump. **Deploy note:** dev deploy had been failing since the `github-pat-model-release` SSM PAT expired (401 Bad credentials at the model-bake build step); rotated the PAT (SSM v3) and redeployed. Shipped on `dev` (`3a3d8f2`).

---

## [2026-06-18] #63 — Backfill gpu_detections for 37 legacy jobs (canvas overlays)

**Type:** feature / data-backfill
**Stage:** webapp
**Status:** shipped (script on dev; data backfilled + verified)

**Why:** User opened job 5, saw no detection boxes. Root cause: 37 of 56 done jobs
(ids 2–37, 40) predate in-process YOLO (#28) → `gpu_detections` empty → no canvas
overlay (their CSVs/entities/datasheets were always fine). User asked for the backfill.

**What:** `webapp/scripts/backfill_gpu_detections.py` (NEW) — selects done jobs with
empty `gpu_detections` and re-runs YOLO over their existing tiles via the SAME path a
fresh job uses (`pipeline_runner._run_inplace_inference`), so the stored shape +
coordinate space match exactly (no #56 scatter). Purely additive (only writes
`gpu_detections`); idempotent (skips populated jobs). `jobs_needing_backfill` /
`_is_empty_detections` unit-tested (3 tests).

**Result:** All 37 backfilled → **56/56 done jobs now have detections, 0 remaining.**
Job 5 = 243, job 40 = 1673, job 36 (222-page doc, 1998 tiles) = 246. Verified job 5
coords are tile-local with `tiling_dims (7152,5052)` resolving → render correctly.

**Notes:** Job 36 (1998 tiles) stalled the initial detached single-pass run (lost its
buffered stdout on exit, but per-job DB commits persisted 34 jobs); re-running the
remainder individually finished it. For future bulk backfills, run per-job or in
batches — a 2000-tile job is ~10 min of CPU ONNX and dominates a single-process sweep.
The detached process redirected stdout to a file → buffered; use `PYTHONUNBUFFERED=1`
or per-job SSM calls to see live progress.

---

## [2026-06-18] #62 — Self-learning loop: label-in-Studio → trainable dataset (close gaps 1 & 2)

**Type:** feature
**Stage:** training
**Status:** shipped (deployed to dev)

**Why:** User asked whether Studio can replace Label Studio for labeling → train. The
Studio→GPU path existed (`UserAnnotation` → exporter → `build_training_set`) but two
gaps blocked it: (1) the biggest correction source (`ModelCorrection` detection-review
add/reclassify) was NOT exported — on dev that's 84 corrections invisible to training;
(2) `build_training_set` emitted label files only, no images/data.yaml/split, so the
output wasn't directly trainable.

**What:**
- **Gap 1** (`export_annotations_for_yolo.py`): also export `ModelCorrection`
  action in (add, reclassify) with a stored `new_bbox` as positive YOLO labels.
  `new_bbox` is the SAME page-pixel space as `UserAnnotation.bbox` (verified in
  `annotations.py` — both from `payload.bbox`), so it reuses the existing tile
  geometry. Class id: try `new_label` as a literal YOLO class, else parse
  `<entity_class>_<sub>` and route through `map_to_class_id` — folding instrument
  sub-types (`instrument_pt/ft/tt/lt`) into the generic `inst_field` the detector
  predicts. `delete` not exported (documented; needs future reconciled-tile work).
  add/twin dedup handled by the existing idempotent writer.
- **Gap 2** (`build_training_set.py`): `<out>/<date>/detection/` is now a trainable
  YOLO tree — crops tile images from `page_N_full.png`, flattens to
  `images|labels/{train,val}/<job>__<tile>` with a deterministic PER-JOB hash split
  (sha1(job_id)%10 → val), writes `data.yaml` (nc + names from `taxonomy.class_names()`).
  Manifest extended (images/train_tiles/val_tiles/train_jobs/val_jobs/classes).
- Lifted PIL `MAX_IMAGE_PIXELS` guard in both (P&ID pages >140M px would hard-error
  >178M and silently lose a page's tiles).
- Built by 2 parallel agents; a defect (29 instrument corrections dropped as
  "unmappable") was caught by running the REAL scripts against dev data, not just
  unit fixtures — fixed via the `map_to_class_id` fallback.

**Result:** Verified on dev (49 jobs): exporter now 70 labels / 14 jobs with **0
instrument skips** (was 67 / 29-skipped); `build_training_set` produced a real dataset
— 30 tiles (27 train / 3 val), `data.yaml` nc=23, paired images+labels, graph + tag
JSONL. 40 unit tests pass (export + builder + schema). **"Label in Studio → train on
GPU" is now real end-to-end** for incremental corrections.

**Notes:** LS still holds the ~32k base corpus; Studio path is for incremental
improvement on top (or a future one-time LS→UserAnnotation migration). 37/56 dev jobs
have 0 YOLO overlay detections (legacy jobs pre-#28 in-process inference — their CSVs
are fine; a `gpu_detections` backfill would add canvas boxes). This dataset feeds
Phase 2 (gated retrain), where the eval gate is the safety net for label completeness.

---

## [2026-06-17] #61 — Self-learning loop Phase 1: correction-rate surface + training-set builder

**Type:** feature
**Stage:** webapp / training
**Status:** shipped (deployed to dev)

**Why:** Close the human-in-the-loop → model-improvement loop. Per the design
(`docs/superpowers/specs/2026-06-17-self-learning-loop-design.md`), capture is ~80%
built; the missing links are MEASURE → AGGREGATE → RETRAIN → GATE → PROMOTE. Phase 1
ships measurement + aggregation (high value, low risk) and doubles as the quantified
answer to the recurring "how wrong are our tags/detections?" question. User: "we need
to achieve [self-learning] at the earliest."

**What:**
- **Version anchor** `webapp/model_version.py` (NEW) — `current_version()` reads
  `models/MODEL_VERSION.txt` (`current: v1-11`); `current_model_trained_at()` returns
  the structured train date (v1-11 → 2026-06-15). The "since current model" anchor for
  every metric. (Append a `_TRAINED_AT` row on each promotion.)
- **MEASURE** — `GET /api/v1/admin/learning/summary` (`api_v1_admin.py`,
  `require_super_admin`): all-time + since-model totals across `model_corrections`,
  `user_annotations`, `entity_overrides` (tag edits = `field_name=="tag"`),
  `graph_corrections`; `by_action`; per-class weakness table (`by_class`, the retrain
  targeting signal — `delete` rows bucketed via `Job.gpu_detections[detection_index]`,
  guarded → "unknown"); `by_job`. New `/admin/learning` SPA page (`AdminLearning.tsx`)
  + nav link, mirrors AdminEntities.
- **TRIGGER** — `retrain_readiness` block in the same response:
  `labeled_corrections_since_model` (labeled UserAnnotations + add/reclassify
  ModelCorrections since trained_at) vs `RETRAIN_READINESS_THRESHOLD=200` → `ready`.
- **AGGREGATE** — `webapp/scripts/build_training_set.py` (NEW): `python -m
  webapp.scripts.build_training_set [--since|--job-id|--dry-run]` → `datasets/learning/
  <date>/{detection,graph,tags}/` + `manifest.json` (class_counts, job ids, since).
  Reuses the two existing exporters' `run()` (no reimpl); `--since` defaults to the
  current model's train date. Built by 3 parallel agents + a self-built keystone.

**Result:** 26 backend tests (7 new builder + 19 exporter) pass; full suite 368 pass
(1 pre-existing env failure in `test_sheets_*`, unrelated); `tsc` + `vite build` clean.
Endpoint live-verified in-container (shape + v1-11 anchor); builder dry-run emits a
valid manifest.

**Notes:** Phase 2 (gated retrain: AWS burst → eval vs prod on frozen holdout, recall
≥90% + graph isomorphism → promote/rollback) is the next step — NEVER auto-promote
without the eval gate. Per-class tag-edit attribution is detection/annotation-based;
canonical-entity tag edits (entity_overrides on pipeline entities not in
user_annotations) count in totals but not per-class (class isn't in the DB for those —
on-disk canonical.json). Threshold 200 is a guess; tune from the first real numbers.

---

## [2026-06-17] #60 — Datasheet schema completed: remaining 7 instrument types added

**Type:** feature
**Stage:** webapp / export
**Status:** shipped (deployed to dev)

**Why:** #59 wired CV/PT/PSV; the other 7 manifest types returned common-only.
User: "if we have all fields for other types, add other as well." We do (manifest).

**What:** Added `_TT/_PG/_TG/_TW/_TE/_FE/_RO_SECTIONS` to `ids_schema.py` from
`docs/instrument-fields-manifest.md`, extended `TYPE_LABELS`, `_SUBCLASS_ALIASES`
(TT/TIT, PG/PI, TG/TI, TW, TE/RTD/TC, FE/FG, RO), and `_TYPE_SECTIONS`. No API,
frontend, or XLSX code changed — they already dispatch on `get_ids_sections_for_type`,
so all 11 types light up automatically. Extended `test_ids_schema.py` uniqueness +
editability invariants to run across ALL types (data-driven on `SUPPORTED_SUBCLASSES`).

**Result:** All 10 type keys, 0 duplicate paths each: CV 171 / PT 129 / TT 101 /
PG 112 / TG 85 / TW 92 / TE 88 / FE 85 / RO 86 / PSV 133 fields (incl. 56 common).
17 datasheet+schema tests pass in-container. FT still aliases to PT.

---

## [2026-06-17] #59 — Per-instrument-type datasheet: full field sets in the Studio drawer + vendor-portal manifest

**Type:** feature
**Stage:** webapp / export
**Status:** shipped (deployed to dev — CV/PT/PSV wired; 8 types pending)

**Why:** The datasheet drawer showed a thin flat 6-field grid for every instrument
(the columns "that went missing"). User wants the FULL datasheet field set per type
visible when an element is clicked, and a build-ready column reference to create the
vendor-portal DB. Origin: vendor-portal field-capture thread (datasheets provided:
ASV_IDS.xlsx, Main Skid IDS.pdf, TNB-2 PT_FT_TT.pdf, Block-5 PSV).

**What:** New single source of truth `webapp/deliverables/ids_schema.py`
(`get_ids_sections_for_type(sub_class)` → sectioned `IdsField`s; path rules:
process/user→`fields.ids_*` editable, vendor→`vendor_match.catalog_fields.*`
read-only; identity→existing canonical paths; `normalize_subclass` maps FT→PT,
RELIEF_SAFETY/RV/PRV→PSV). Consumed by BOTH the XLSX generator (`datasheet.py`,
now per-type + includes control/relief valves, not instruments-only) and a new
per-entity API `GET /api/v1/jobs/{id}/entities/{eid}/datasheet`
(`routers/entities.py`). Drawer (`DatasheetDrawer.tsx` + `api.ts`) renders sectioned
fields for the datasheet doc-type (vendor fields read-only, process/user editable via
existing `entity_overrides` PATCH); other doc-types unchanged. Built by 4 parallel
agents. New doc `docs/instrument-fields-manifest.md` — ~430 build-ready columns
(snake_case + source + SQL type) across 11 types; the matched machine-readable pair
to `instrument-datasheet-fields.md`.

**Result:** CV 170 / PT 128 / PSV 132 fields (incl. 56 common); 0 duplicate paths
(uniqueness test caught a PSV `molecular_weight` collision — fixed). 15 datasheet+schema
tests pass; full suite 359 pass (1 pre-existing env failure in `test_sheets_*`, tile
state, unrelated); `tsc --noEmit` + `vite build` clean; endpoint live-verified on a
real entity.

**Notes:** Only CV/PT/PSV have per-type schemas; the other 8 (TT, PG, TG, TW, TE, FE,
RO) return common-only until transcribed (TODO in `ids_schema.py`). Vendor fields are
read-only by design (filled by the vendor-match API); they show blank until the portal
exists. PSV/CV are `entity_class=valve`, so the datasheet view is now class-agnostic
(keyed on `entity_id`, not the instrument-only deliverable filter).

---

## [2026-06-17] #58 — Mark-time AI tag read (OCR the user-drawn box)

**Type:** feature
**Stage:** webapp
**Status:** shipped (deployed to dev, live-verified)

**Why:** #57's re-read is most accurate when the crop comes from a box the USER
draws AROUND the tag (the auto symbol-box misses the tag ~half the time, since the
tag sits outside the symbol). Wire OCR into the Mark-Symbol flow.

**What:** PidCanvas passes the normalized drawn box (computed at mark-time, where
the render viewBox is known) as a 4th `onDropMark` arg. `Studio.onDropMark` awaits
`createAnnotation` → `ocrBbox(drawnBox)` → `patchAnnotation(tag)`. The tag appears
on the canvas label and syncs to exports via #55. Best-effort + editable; OCR
failure never breaks the mark (try/catch, non-blocking).

**Result:** tsc clean; 121 vitest; `POST /ocr-bbox` live 200 (returned correct
`62-BV-151109`). Force-recreated web post-deploy (the recurring stale-container
gotcha) so the fresh SPA bundle serves.

---

## [2026-06-17] #57 — "Re-read tag (AI)" button (per-element vision re-OCR) + OCR/matching investigation

**Type:** feature, investigation
**Stage:** webapp, export
**Status:** shipped (deployed to dev, live-verified); framed as a best-effort assist

**Why:** User reports wrong tag NAMES in the bulk export. Diagnosis: export tags come
from the whole-tile **vision** pass (extractor.py) which misreads dense tags — not
classic OCR. Requested fix: a button to re-read a marked element's tag.

**What:**
- `POST /api/v1/jobs/{id}/ocr-bbox` (annotations.py): normalized bbox → crop the
  hi-res source page → send ONLY that crop to the vision model
  (`extractor.get_client`/`DEFAULT_MODEL`) → extract tag-shaped candidate
  (`_tag_candidates`). Source dir resolved via `output_csv_path` parent (org-scoped).
- Frontend "Re-read tag (AI)" button in DatasheetDrawer; Studio computes the
  selected detection's normalized bbox (tile-local→source via computeTileOffsets at
  tiling dims). Human-confirmed: fills the tag field; user reviews + Saves (flows to
  exports via the #55 annotation→canonical sync).

**Result / honest accuracy:** live end-to-end works (`POST ocr-bbox` → 200, returned
correct `62-BV-151109` on a well-placed crop). Batch on auto-DETECTION bboxes: ~4/8
return a tag, hard to score (the only baseline — stored tags — is unreliable). The
tag sits OUTSIDE the symbol bbox, so auto-symbol crops miss it ~half the time; a
USER-drawn box around the tag (the intended flow) frames it far better. **Tried
rapidocr first (user's pick): 1/10 — rejected** (can't read the small/thin tag text);
swapped to vision-on-crop.

**Notes:**
- **No matching/duplicate bug in the EXPORT** — job 56: 73 unique tags, job 1: 68
  unique. The "same tag ×3" seen earlier was job 1's legacy GPU-worker *canvas*
  detections (a separate, older source), NOT the export. So wrong export names are
  per-character vision misreads, not mis-assignment.
- **Canonical export entities have placeholder-zero bbox** — the real bbox lives in
  detections/annotations; that's why the re-read button reads from the detection bbox
  (or a user-marked box), not the canonical entity.
- **DEPLOY GOTCHA (recurring):** the web container is sometimes NOT recreated by a
  deploy (esp. after a manual force-recreate during a 502), leaving a STALE uvicorn
  process — a newly-added route then 405s (SPA catch-all GET matches the path) even
  though `docker exec python3` sees the route on disk. Fix: force-recreate web.
- Possible next improvements: asymmetric/larger pad (tags sit above/beside); let the
  re-read use a user-drawn box; confidence display.

---

## [2026-06-17] #56 — Fix detection scatter: rescale tile coords from tiling-source to render res

**Type:** bugfix
**Stage:** webapp
**Status:** shipped (deployed to dev; Playwright-verified job 56 + job 1)

**Why:** Job 56 (580 detections) showed badly scattered detection glyphs that drifted
further off the symbols the more you zoomed — the #55-diagnosed render-scale bug.
Detection bboxes are tile-local in the TILING SOURCE resolution (`page_0_full.png`,
the pdf_to_tiles zoom=6 render ~7146px), but the canvas computed tile offsets at the
RENDER width (`?w=8000` fit, `?w=12000` zoomed) and added the source-space bbox with
no rescale → each detection pulled toward its tile's top-left by `(1 − source/render)`
(~11% fit, ~40% at w=12000).

**What:**
- `api_v1.api_job_detections` returns `tiling_width/height` = `page_0_full.png` dims
  (`_tiling_source_dims`; resolves dir via `output_csv_path` parent — get_job_dir's
  user_id path misses org-scoped jobs ≥40; (None,None) when absent).
- `PidCanvas` computes tile offsets in the SOURCE resolution, then scales the page
  bbox by `natural/source` into the canvas viewBox (mirrors the #54 GraphLayer fix).
  `tilingWidth` absent → scale 1 (legacy fallback, no regression). ONLY the detection
  path changes — annotations/edges/graph untouched.

**Result (Playwright on dev):** job 56 glyph X-spread **6–78% → 9–91%** (Y 6–72 → 9–80)
— detections span the full drawing; at deep zoom (12000px re-render) glyphs sit ON the
symbols (screenshots). Job 1 (sparse) no regression (17–81% / 21–63%). tiling dims
verified live (job 56: 7146×5052, job 1: 7152×5052). tsc clean; 121 vitest pass.

**Notes:**
- **Post-deploy 502 recovered** mid-session via the documented force-recreate (web
  container stuck `Created` on `up -d` name collision; `/healthz` 200 but `/` 502).
- Latent, NOT fixed: user-ANNOTATION bboxes (Layer 2) are stored in the render space
  at create-time, so they can drift if created at one zoom and viewed at another.
  Out of scope (no reported issue, would need stored-data migration). Detections
  (Layer 1) are consistently in source space, which is why this fix is clean.

---

## [2026-06-17] #55 — Mark-Symbol → exports sync; label hover-toggle; Re-process button; job-56 scatter diagnosed

**Type:** feature, bugfix
**Stage:** webapp
**Status:** shipped (3 features deployed to dev); job-56 detection-scatter DIAGNOSED, fix not yet built

**Why:** Batch of user-reported gaps. (1) "Mark Symbol" canvas adds/deletes didn't
show in exports/drawer/bulk-review (two unsynced stores). (2) Element labels were
always on, overlapping the small symbols on dense drawings. (3) Old/empty jobs
(20/21) had no in-Studio way to re-detect with the new model. (4) Job 56's
detections look "scattered" / off the symbols.

**What (shipped):**
- **Annotation→canonical sync** (`annotations.py`): a TAGGED user_annotation is
  mirrored into canonical.json (so exports/DatasheetDrawer/BulkReview see it);
  untagged/rejected/deleted/cleared-tag removes it. Rule: reaches deliverables
  only once tagged. uuid4 (annotation) vs uuid5 (pipeline) ids don't collide.
  Tests: `test_annotation_canonical_sync.py` (5).
- **Label hover-toggle** (`PidCanvas.tsx`/`Studio.tsx`): labels render only for
  hovered/selected element by default; toolbar "Labels" toggle shows all (with
  collision filter). De-clutters dense canvases.
- **"Re-process" button** (`StudioTopBar.tsx`): POSTs the existing prefix-less
  `/jobs/{id}/rerun` (full pipeline: current-model YOLO + graph), confirm-gated,
  reloads to progress panel. User-initiated only; entity_overrides preserved.

**Result:** 15 backend annotation tests pass; frontend tsc clean + 121 vitest.

**Notes — JOB-56 SCATTER ROOT CAUSE (fix pending):** detections are stored
**tile-local in the tiling source resolution** (~7146px page render), but the
canvas renders the page UPSCALED (`?w=8000` at fit, **`?w=12000` when zoomed** —
hi-DPI re-render FEATURES #43) and adds the tile bbox WITHOUT rescaling. Net: each
detection is pulled toward its tile corner by `(1 − 7146/render_width)` — ~11% at
fit, **~40% at w=12000** (worse as you zoom; obvious on job 56's 580 dense dets).
Playwright: glyphs cover only 6–78% of page width. **Fix:** rescale tile bboxes by
`render_width / tiling_source_width` in the detection-render path (the graph layer
ALREADY does this via `natural/page_width` — mirror it; persist the tiling source
width). Detection coords themselves are fine — purely a render-scale bug.

---

## [2026-06-17] #54 — Fix graph canvas coords (top-left blob) + graph failure overlay

**Type:** bugfix, feature
**Stage:** graph, webapp
**Status:** shipped (deployed to dev; jobs 1, 44 re-extracted)

**Why:** User reported the "Graph" overlay drew all nodes/edges as a blob in the
top-left corner of the P&ID, not on the symbols. Two bugs: (1) the graph pipeline
got **raw** `gpu_detections` (legacy shape: `bbox_tile` + `tile_row/col/page`, no
`bbox`/`tile`), but `loader.to_page_pixel_detections` keyed on `bbox`/`tile` — so
NO tile→page translation happened and every node collapsed into tile-local coords;
(2) graph coords live in the traced page-image space (e.g. 7152×5052) while the
canvas renders the page at a different resolution (8000×5652) with no scaling.
Also: the resolver's `orphan_lines` (failed-to-connect pipe segments) were never
drawn, so users couldn't SEE where extraction failed.

**What:**
- `loader.to_page_pixel_detections`: normalize the legacy detection shape
  (`bbox_tile` + `tile_row/col/page` → `bbox` + `tile_p{p}_r{r}_c{c}.png`),
  mirroring `api_v1._normalize_detection_shape`. Core coord fix.
- `assembler.assemble` + `pipeline`: emit `page_width`/`page_height` (traced
  page-image dims) in `canonical_graph.json`.
- `GraphLayer.tsx`: wrap graph geometry in `<g transform="scale(natural/page)">`
  so nodes/edges/orphans land on the canvas; absent dims (legacy) → no scaling.
- **Failure overlay:** render `orphan_lines` as faint dashed-amber polylines +
  floating/unlinked nodes (in `floating_nodes` or `entity_id==null`) as amber
  rings; footer chip shows "N unconnected". Lets users see failures and draw the
  missing edges (human-in-the-loop training signal).

**Result (Playwright-verified on dev, job 1):** node-center span went from
top-left X 102–3135 to **X 1183–5762 / Y 1428–3165** (distributed across the
page); `scale(1.1186,1.1188)` applied; 96 nodes / 110 edges / 100 orphans render
on the symbols (screenshots confirm). graph/edge suite 121 pass; GraphLayer 14
vitest (added scale + no-scale); tsc clean.

**Notes:**
- **Graph extraction is still LLM-fallback-heavy and orphan-heavy** on real
  drawings (job 44: 32 nodes, ~27 edges, 150 orphans, fallback=True) — detected
  pipe geometry mostly doesn't link. The tracer/resolver TUNING explored this
  session (wider snap, node-segment arrow orientation) was **REJECTED**: it did
  NOT drop orphans (they're tracer noise, not near-misses) and regressed job 51
  (14→4 edges). Right next lever is this failure overlay + a real
  tracer-quality/eval pass, NOT blind threshold widening.
- **`extract_graph(write_file=True)` overwrites `canonical_graph.json` on disk** —
  measuring on real jobs mutates dev data; re-extract with deployed code to restore.

---

## [2026-06-17] #53 — Directed process graph (flow direction) — model arrows + user edges

**Type:** feature
**Stage:** graph, webapp
**Status:** shipped (merged to dev)

**Why:** The process graph existed (auto CV+LLM extraction → nodes/edges, render in
Studio, user draw-edge, training export — FEATURES #38/#40) but was **undirected**:
the assembler explicitly deferred flow direction and the pipeline *skipped* the
v1-11 detector's `arrow_*` / `connector_in/out` classes. User goal: a directed
graph (valves/instruments connected with flow direction) — try the model first,
else let users draw/correct direction as self-learning training data. Spec:
`docs/superpowers/specs/2026-06-17-graph-directions-design.md`. Built with 4
parallel agents (backend impl ∥ frontend impl, then test ∥ security-audit) + lead
integration; design/branch policy now plain `dev` feature branch (no `dt/*`).

**What:**
- **`webapp/graph/orient.py`** (new, Step E.5 in `pipeline.py`): orients each
  traced edge by the nearest `arrow_*` detection within `ARROW_PROXIMITY_PX`
  (30px) of its polyline (dot-product decides source→target swap);
  `connector_in/out` fallback; no arrow ⇒ stays undirected. **Edge-count
  invariant** — only flags/swaps, never adds/drops. Defensive `_safe_polyline`.
- **`directed` field everywhere:** `GraphCorrection.directed` (nullable bool,
  `run_migrations` new_columns — no Alembic), `edges.py` EdgeCreate/Patch/Row
  (user edges default true), `graph.py` merge (legacy/missing ⇒ false),
  `canonical_graph.json` edges, and the training export (`export_graph_for_training`).
- **Frontend `GraphLayer.tsx`:** per-method SVG `<marker>` arrowheads via
  `markerEnd`, drawn only when `directed===true`; `directed?: boolean` on the
  `GraphEdge` type. Undirected/legacy edges render exactly as before.
- **Security hardening** (from the audit): polyline `conlist(max_length=500)`
  (DoS cap), `relation_type`/`status` allowed-value validation (a typo'd status
  could silently flip graph-merge visibility), `orient.py` malformed-point guard.

**Result:** backend 338 pass / 1 pre-existing unrelated fail
(`test_sheets_empty_when_no_tiles`, stray-tile container artifact); graph/edge/
orient/export subset 123 pass (+~50 over baseline). Frontend tsc clean, GraphLayer
8 vitest. Security audit: **AuthZ/AuthN sound (no IDOR)** — `_load_job_or_404`
enforces owner-or-super_admin/404; findings were validation/DoS, now fixed.

**Notes:**
- **AuthZ is by `Job.user_id`** (owner-or-super_admin, 404-not-403) — the edge/
  graph routers follow `entities.py`'s pattern; there is no org-scoping (Job has
  no org_id).
- **Existing dev jobs' `canonical_graph.json` predate this** → auto-direction
  shows only on newly-processed / re-extracted jobs (the graph pipeline must
  re-run to orient by arrows). **User-drawn edges are directed immediately.**
- NetworkX container stays a `MultiGraph`; direction is a per-edge attribute, not
  a `DiGraph` switch (canonical_graph.json remains source of truth).
- Pipeline-test sharp edge: `extract_graph` only traces when a full-page PNG
  exists on disk; a detections-only synthetic job yields 0 edges + LLM fallback.

---

## [2026-06-17] #52 — Instrument loop_name/signal fixes + taxonomy loose-ends close-out

**Type:** bugfix, test
**Stage:** export, symbols, webapp
**Status:** shipped (deployed to dev; dev re-backfilled)

**Why:** Two follow-ups after #51. (1) The deliverables test suite had 4
long-standing failures; (2) taxonomy #49/#50 left two loose ends — a reported
`sync_taxonomy_to_db` counter bug and an unexercised Label Triage loop. Built via
two parallel agents, but both died at launch on transient API-529s, so done
inline (with systematic-debugging verification per item).

**What:**
- `pipeline_emitter.py`: **loop_name** kept the trailing instance letter
  ("422-11-PT-006A" → "...P-006A"); now stripped to "...P-006" (PT-006A/B share
  loop 006). Pure-digit segments unchanged. Also **captured the "Signal Type"
  CSV column** the emitter was silently dropping (added `signal_type` to the
  dual-schema alias map). The emitter test + canonical fixture already encoded
  the correct values — the code (and its comment) were wrong.
- Stale instrument-index tests: default template legitimately grew **32 → 35
  columns** (vendor-match enrichment) and is loop-centric (no raw tag column) —
  updated the count test, regenerated the expected CSV fixture, switched the
  filter test to loop-number + service assertions.
- Taxonomy: the "counter mis-reports inserts as updated" note (from #50) was a
  **non-issue** — fresh sync returns (43 inserted, 0 updated), re-run (0, 43),
  already asserted in `test_taxonomy_db.py`. No code change. Added an end-to-end
  `test_discover_then_classify_closes_the_loop` linking discovery → classify on
  one row (the halves were covered separately).

**Result:** deliverables suite 4 failing → 0 (78 pass); taxonomy/label suite 31
pass. Dev re-backfilled (`backfill_canonical --from-db --force` +
`index_canonical_to_db`) so loop_name/signal_type land in canonical.json.

**Notes:** Full-app tests (import `webapp.main`) need py3.10+ (PEP-604 `X|None`
in a transitive import) — run in the container, not host py3.9. The emitter's
deliverables modules are 3.9-safe and run on host. #49/#50 status corrected to
shipped below.

---

## [2026-06-17] #51 — Repair empty instrument indexes on dev (dual-schema emitter + backfill --force)

**Type:** bugfix, infra
**Stage:** export, webapp
**Status:** shipped (deployed to dev; dev data repaired)

**Why:** Audit of dev showed 17 jobs whose instrument-index entities existed but had
all data fields empty. Two compounding causes: (1) jobs 2 & 39–55 were emitted
before the ALL-CAPS instrument-field map fix landed; (2) **two CSV header schemas
exist in production** — ALL-CAPS (current) and Title-Case (older MUK/Oman jobs 1,
38) — and a prior session *swapped* the emitter map Title-Case→ALL-CAPS, fixing new
jobs while silently breaking re-emit of legacy ones. `backfill_canonical` also
*skipped* any job that already had a canonical.json, so it could not repair stale
files at all.

**What:**
- `pipeline_emitter.py`: replaced the single-spelling `_INSTRUMENT_FIELD_MAP` with
  `_INSTRUMENT_FIELD_ALIASES` (field → candidate columns) + `_first_col` helper;
  tag/sub_class/pid/manufacturer/model now read both schemas (ALL-CAPS first, so
  current jobs are byte-identical). Tests: `test_emitter_dual_schema.py`.
- `scripts/backfill_canonical.py`: added gated `--force` to re-emit over an existing
  canonical.json (override-safe — never touches `entity_overrides`; deterministic
  entity_ids keep edits attached). Tests: `test_backfill_canonical_force.py`.
- Ran `backfill_canonical --from-db --force` + `index_canonical_to_db` on dev.

**Result:** dev instrument jobs populated **3/20 → 20/20** (0 empty). Job 1 34/34,
job 38 37/37, job 40 286/286, etc. canonical_entities reindexed (55 synced, 0
errors). deliverables test suite 5 failing → 4 (fixed `test_realistic_job_dir`).

**Notes:** **The FS-walk mode of backfill mis-handles org-scoped jobs** — org_id dirs
are numeric so `iter_jobs_from_fs` treats `/job_outputs/{org}/` as a flat job and
never descends to `/{org}/{job}/`. Always use `--from-db` for jobs ≥40. A separate
pre-existing bug remains: instrument `loop_name` keeps the tag's trailing char
(`422-11-P-006A` vs expected `422-11-P-006`) — out of scope here.

---

## [2026-06-16] #50 — Taxonomy reconciliation: taxonomy.json is now the sole display/glyph source

**Type:** refactor
**Stage:** symbols, webapp
**Status:** shipped — merged to `dev` 2026-06-16 (was: experimental, branch `feat/taxonomy-foundation`). Loop exercised end-to-end in #52.

**Why:** #49 preserved behavior via frontend override maps where my Phase-1 seed
diverged from live values, and investigation found the codebase had **three**
drifting display-name maps (`valveLabels.ts` palette, `buildElements.ts` stage,
`labelMap.ts` canvas) — e.g. DB was "Double Block" in one and "Diaphragm Valve"
in two; NCBV "NC Ball Valve" vs "Non-Compliant Ball Valve". User chose **DB =
"Double Block"** as canonical (product decision; resolves spec open-question #3).

**What:**
- `taxonomy.json`: DB glyph `valve_gen→valve_db`, NCBV glyph `valve_bv→valve_ncbv`
  (the specific glyphs exist + were rendered via overrides), RELIEF_SAFETY display
  `"Relief/Safety Valve"→"Relief / Safety Valve"`, added `PNEUCTRL` row
  (valve / "Pneumatic Valve" / valve_pneuctrl). Now 43 classes.
- Regenerated `taxonomy.generated.ts`.
- Removed `FRONTEND_SUB_CLASS_OVERRIDES` (`labelMap.ts`) + `FRONTEND_GLYPH_OVERRIDES`
  (`PidSymbol.tsx`). Pointed `valveLabels.ts` + `buildElements.ts` at
  `DISPLAY_NAME_BY_SUB` (deleted their private hardcoded maps).

**Result:** DB now renders "Double Block" everywhere (palette/stage/canvas/exports);
NCBV "NC Ball Valve"; PNEUCTRL "Pneumatic Valve". Frontend `tsc` clean, vitest
112/112 (updated the one frozen parity snapshot: DB → "Double Block"); backend
taxonomy suite 30 pass; `label_taxonomy` synced to 43 rows (PNEUCTRL verified).

**Notes:** `sync_taxonomy_to_db` log counter mis-reports inserts as "updated"
(cosmetic; row data verified correct). taxonomy.json is now the single source of
truth for class display names + glyph kinds — no override maps remain.

---

## [2026-06-16] #49 — Unified symbol taxonomy + label triage (Phases 1–4)

**Type:** architecture, feature
**Stage:** symbols, webapp, infra
**Status:** shipped — merged to `dev` 2026-06-16 (was: experimental, NOT merged — PR review pending). Counter "bug" in notes was a non-issue; loop exercised end-to-end — see #52.

**Why:** The same symbol classes were defined in ~7 places (inference `CLASS_NAMES`,
`api_v1._yolo_class_to_canonical`, `paletteColors.ts`, `labelMap.ts`,
`PidSymbol.subClassToSymKind`, `ls_label_config.xml`, instrument codes) with no
single source of truth, and a newly-annotated LS label never flowed back into the
app. Spec: `docs/superpowers/specs/2026-06-16-unified-taxonomy-design.md`.

**What (7 commits, built via a 7-agent sequential workflow + parity gates):**
- **P1** `webapp/taxonomy.json` (source of truth) + `webapp/taxonomy.py`
  (`load_taxonomy`/`class_names`/`yolo_to_canonical`/`display_name`/`color`/`glyph_kind`).
- **P2** `inference.CLASS_NAMES = class_names()`; `_yolo_class_to_canonical` delegates
  to `taxonomy.yolo_to_canonical`. Parity test pins both consumers against frozen
  literals (non-tautological gate).
- **P3** `taxonomy.json` expanded with 19 palette-only canonical classes
  (yolo_label=null); `scripts/gen_taxonomy_ts.py` → `taxonomy.generated.ts`;
  `paletteColors`/`labelMap`/`PidSymbol` source from it. vitest parity snapshot.
- **P4a** `LabelTaxonomy` + `LabelTriage` tables + idempotent `taxonomy_db.sync_taxonomy_to_db`
  (startup, non-fatal). **P4b** admin API `/api/v1/admin/taxonomy` + `/label-triage` +
  `/label-triage/{id}/classify` (super_admin). **P4c** `/admin/label-triage` UI.
  **P4d** unknown-label discovery hook in `api_job_detections` + `scripts/gen_ls_label_config.py`.

**Result (verified independently):** backend 279 pass / 6 fail (all 6 PRE-EXISTING:
5 in `deliverables/` — untouched by this branch — + `test_sheets_empty_when_no_tiles`
stale-tile env artifact); frontend `tsc` clean, 112/112 vitest. `webapp/deliverables/`
untouched by the diff.

**Notes:** Behavior preserved via FRONTEND override maps where my Phase-1 seed
diverged from the live frontend values — **must reconcile** (pick canonical side,
remove overrides): `DB` display "Double Block"(json) vs "Diaphragm Valve"(FE);
`RELIEF_SAFETY` spacing; `PNEUCTRL` FE-only; `NCBV`/`DB` glyph kinds. `LabelTaxonomy.order`
mapped to DB column `display_order` (SQL reserved word). `classify` rewrites
`taxonomy.json` with `json.dump(indent=2)` (reformats the compact hand-format on append).

---

## [2026-06-16] #48 — Local Docker build no longer requires a model PAT (model-bake skip)

**Type:** infra, bugfix
**Stage:** infra
**Status:** shipped (deployed to dev)

**Why:** Local `docker compose build` was impossible without a GitHub PAT — the
Dockerfile baked `v1-11.onnx` from a **private** release and `exit 1`'d on any
failure, including the no-PAT local case. The local `.github_pat` placeholder is
a lone newline (size>0 but blank), so the old `[ -s ... ]` guard didn't catch it
and the build died trying to download with an empty token (`Bad credentials`).
This blocked all local testing of root-level pipeline modules (baked, not mounted).

**What:** Dockerfile model step now reads the secret, strips whitespace, and
`exit 0`s with a clear log when blank (`TOKEN=$(... | tr -d '[:space:]'); [ -z "$TOKEN" ]`).
Matches the step's long-documented intent. CI/deploys are unaffected — they inject
a real PAT from SSM, so the sha-verify fail-hard path still runs. Local images
build without the YOLO model; `webapp/inference.py` raises `InferenceError` only
if in-process inference is actually invoked (canvas overlay), which local feature
testing doesn't need.

**Notes:** Local FE iteration gotcha confirmed (FEATURES #18): `override.yml`
mounts `./webapp`, so the host SPA dist shadows the image — run `npx vite build`
on the host for frontend changes; `docker compose build` only matters for
repo-root `*.py` (extractor/parser/pdf_to_tiles).

---

## [2026-06-16] #47 — Studio: hotkey-hint collision fix + element-count tooltip

**Type:** bugfix
**Stage:** webapp/frontend
**Status:** shipped (deployed to dev)

**Why:** Palette rows advertised stale hardcoded digit hotkeys (Double Block→`3`,
Globe→`5`, Pressure→`Z`, NC Ball→dup `G`). Digits 1/2/3 are reserved for mode
switching (select/mark-symbol/draw-edge, `routers/shortcuts.py:DEFAULT_SHORTCUTS`),
so pressing the advertised `3` on Double Block triggered draw-edge instead of
selecting the class. Separately, users were confused that the stage element count
differs from Bulk Review.

**What:**
- `paletteColors.ts`: removed all static `key` hints. Badges now come solely from
  the live merged-with-defaults shortcut map (`PalettePanel.buildClassKeyIndex`);
  the 9 default-bound classes show their real letter, unbound classes show no
  badge until assigned at `/account/shortcuts`. The assignable-shortcuts UI itself
  already existed (FEATURES #38).
- `PropertiesPanel.tsx`: explanatory `title` on the count clarifying stage = every
  detection on the sheet (incl. arrows/connectors) vs Bulk Review = deliverable
  entities only across all sheets — they are *expected* to differ.

**Result:** Verified in-browser on local (job 2) — Double Block shows no badge,
only bound classes show letters. `tsc` clean; **101/101 vitest pass** (added a
paletteColors regression test asserting no entry uses a reserved mode key; updated
the PalettePanel fallback test to the corrected no-badge behavior).

---

## [2026-06-16] #46 — Multi-page P&ID: thread source page into per-sheet number

**Type:** bugfix
**Stage:** associate, export
**Status:** shipped (deployed to dev)

**Why:** Canonical entities hardcoded `sheet_number=1` regardless of which page a
detection came from, so multi-page jobs collapsed all entities onto sheet 1 (user
report: "sometimes the sheet has a mismatched number"). The per-sheet sidebar fix
(`detectionPage()`, FEATURES #43-adjacent) addressed the canvas; this fixes the
deliverable/canonical attribution.

**What:** `extractor.py` stamps `page` on valves + instruments → `parser.py` /
`instrument_parser.py` carry `ValveRow.page` / `InstrumentRow.page` and emit a
`"Sheet"` CSV column (`page+1`) → `webapp/deliverables/pipeline_emitter.py`
`_sheet_from_row()` reads it into `sheet_number` (defaults to 1 for legacy CSVs —
backward-compatible). Tests: new `tests/unit/test_parser_sheet.py` (3) + 4 emitter
sheet-column cases.

**Result:** Corrects **new** jobs only; existing multi-page jobs need a re-run to
backfill. 12/13 emitter+parser tests pass (the 1 failure,
`test_emit_instruments_with_synthetic_vendor_match`, is a **pre-existing** PR-merge
vendor-match fixture bug — fails identically on clean HEAD, flagged for swaraj).

---

## [2026-06-15] #45 — Studio canvas: P&ID symbol glyphs replace detection rectangles (LS-style per-class colors)

**Type:** feature
**Stage:** webapp/frontend
**Status:** shipped (deployed to dev)

**Why:** On the canvas, model detections + user-marked symbols rendered as plain
`<rect>` boxes. The 37 `PidSymbol` glyphs + class→glyph mapping existed but were
only used in the palette/side-panel. User wanted the real symbol shown on the
drawing, colored per class like Label Studio. (Auto-detect, manual marking,
draw-edge connections, and DB persistence already existed — FEATURES #38/#40 —
so this is purely the canvas rendering.)

**What (frontend-only, no backend/API/DB change):**
- **`paletteColors.ts`** (new): single source of truth for per-class colors,
  moved out of `PalettePanel.tsx`. `colorForSubClass(entityClass, sub)` +
  `colorForKind(kind)` (built by running each palette sub through
  `subClassToSymKind`). `PalettePanel` refactored to import it (identical render).
- **`PidSymbol.tsx`**: `labelToSymKind(label)` (YOLO label → glyph kind; aliases
  `Pump/Dwg Pump`→`pump`; unknown→`valve_gen`) + `PidGlyphAt({kind,x,y,w,h,color})`
  — a nested positioned `<svg viewBox="0 0 30 26">` that drops into the page SVG,
  scales with zoom, and colorizes via `currentColor` (glyphs already use it).
- **`PidCanvas.tsx`** Layer 1 (model) + Layer 2 (user): replaced the visible
  `<rect>` with glyph + class-colored outline (model = **solid**, manual =
  **dashed**) + invisible hit-rect (preserves click/select) + pink select box;
  labels recolored to the class color.

**Result (verified live on dev, Playwright, job 1):** canvas renders **225
glyphs** in **28 distinct class colors**, **0 legacy blue (#3B82F6) detection
rects** remain; glyphs crisp + recognizable at 544% zoom (teal ball valves, pink
butterfly), overlaid at symbol locations. `GET /jobs/1/{edges,graph}` round-trip
200 (connect/save path intact). Built via 2 parallel subagents (Task 1 color map
/ Task 2 glyph wrapper, disjoint files) + lead integration (Task 3).
tsc clean; 96 vitest pass (7 new: paletteColors 4 + glyphMapping 3).

**Notes:**
- Spec `docs/superpowers/specs/2026-06-15-canvas-symbol-glyphs-design.md`; plan
  `docs/superpowers/plans/2026-06-15-canvas-symbol-glyphs.md`.
- **Tiny at fit:** glyphs scale with zoom (sit on the equally-small real
  symbols); labels stay visible. Follow-up if needed: a minimum on-screen size.
- Canvas glyph layers aren't jsdom-unit-tested (`natural` dims gate on real img
  `onLoad`); live Playwright is the acceptance. Pure mappers are unit-tested.
- **PR #1 (swaraj "Qong studio updated features")** overlaps `PidCanvas`/`Studio`/
  `buildElements`/`PropertiesPanel` and is now further behind — it must be rebased
  onto this `dev` before merge (conflicts on the glyph + zoom + v1-11 work).

## [2026-06-15] #44 — Studio canvas: layout-based zoom (the actual deep-zoom pixelation fix; completes #43)

**Type:** bugfix
**Stage:** webapp/frontend
**Status:** shipped (deployed to dev)

**Why:** #43 made the canvas request a higher-res render as you zoom — but the page **still looked blurry on dev**. Browser-measured root cause (Playwright on dev, job 1 @ 600%): the hi-DPI source *was* loading (`imgNaturalW=12000`), but the `<img>` was laid out at only **656 CSS px** and zoom was a CSS `transform: scale(6)` on `.canvas-inner` (further pinned by `will-change: transform`). `transform: scale` magnifies the **already-rasterized 656px layer** — it never samples the 12000px source. So #43's higher-res fetch was wasted. The fix had to change the *display*, not just the source.

**What:**
- **Layout-based zoom** (`PidCanvas.tsx`): zoom now sizes the page box in real CSS pixels instead of transforming it. `.canvas-inner` carries only `translate` (pan); full-page mode drops `scale`. A `ResizeObserver` on the canvas tracks available size; `PageWithOverlays` computes `display = fit(natural, avail) × zoom` (object-fit-contain math) and sets the page container + `<img>` to those exact px. The browser then lays the image out at the zoomed size and samples the full-res source → crisp. Invariant to source resolution (same aspect), so #43's `?w` escalation only sharpens, never reflows. All overlay geometry already derives from `natural.w/h`, so detections/edges/labels stay aligned.
- Removed `will-change: transform` from `.canvas-inner` (`studio.css`) — the page box can be ~12000px wide; pinning it as one GPU layer would waste large VRAM and isn't needed for translate-pan.
- Legacy tile/proto modes keep `transform: scale` zoom (only full-page is layout-based).

**Result (verified on dev, Playwright):** at 600% zoom the `<img>` layout width goes 656px → **3936px** (= fit 656 × 6), so a 3936px box samples the 8000–12000px source instead of upscaling a 656px raster. Screenshot confirms **sharp, readable tag text** (line numbers, `MUK-…` codes) where #43 alone was blurry. `tsc` clean; 89 vitest pass.

**Notes:**
- This + #43 together are the full fix: #44 makes the display sample real pixels; #43 ensures enough source pixels exist at deep zoom. Neither alone is sufficient.
- Smooth zoom *animation* is gone (width isn't transition-animated like transform was) — acceptable; wheel-zoom was never animated.
- Pinch/2-finger and the +/- buttons all flow through the same `zoom` state, so they all benefit.

## [2026-06-15] #43 — Studio canvas: on-demand zoom-aware page re-render (fix deep-zoom pixelation)

**Type:** bugfix | feature
**Stage:** webapp/frontend | webapp
**Status:** shipped (deployed to dev)

**Why:** Users reported P&ID pages pixelate/blur on deep zoom. Root cause (code-traced, not the #41 symptom): the page is a single fixed-resolution raster (`?w=8000`) and Studio zoom is a CSS `transform: scale()` (PidCanvas) that magnifies the already-painted bitmap rather than sampling the high-res source — so the 8000px detail is wasted and, on Retina/4K (effective px = viewport×zoom×devicePixelRatio), deep zoom upscales past native → blur. #41 only raised the fixed render size; it didn't make zoom request sharper pixels.

**What:**
- **Frontend (`Studio.tsx`):** zoom-aware render width. New pure helper `targetRenderWidth(viewportW, zoom, dpr)` = `viewportW×zoom×dpr`, rounded UP to a 2000px bucket, clamped to [8000, 12000]. A debounced (280ms) effect watches `zoom`; when the target exceeds the current width it **preloads** the higher-`?w` render via `new Image()` and only swaps the visible `<img>` src on decode (no blank flash — sharpens in place like map tiles). Monotonic-increase (zoom-out keeps the sharper render; it downscales cleanly); resets to baseline on page change. Safe because all overlay geometry derives from the loaded image's `natural.w/h`, so a higher-res render of the same page stays aligned.
- **Backend (`webapp/routers/jobs.py serve_page_full`):** raised the on-demand cap 9000→12000px and the per-page zoom clamp 12→16 (lets landscape A3 reach 12000px).
- **Test:** `__tests__/targetRenderWidth.test.ts` (5) — baseline floor, max ceiling, bucket rounding, monotonicity, dpr sensitivity.

**Result:** Deep zoom re-renders true vector pixels at the resolution the display needs (kicks in above ~2.6× zoom on a 1512px dpr=2 laptop), instead of upscaling a fixed 8000px raster. Frontend `tsc` clean; 89 vitest pass (84 + 5 new).

**Notes:**
- **12000px ceiling is a memory/latency tradeoff in the WEB process** — landscape A3 @ 12000px ≈ 100MP ≈ ~400MB transient pixmap, and the `fitz` render is synchronous (~2-3s, briefly blocks the event loop). Acceptable on low-traffic dev; if it bites, offload via `run_in_threadpool` or the cpu-worker before raising further. At max zoom (6×) on a dpr=2 laptop the target wants ~18000px so it still mildly upscales past 12000 — true crispness at max zoom needs the **tile-pyramid** approach (deferred; bigger change). PDF.js vector rendering remains the no-pixelation-ever end-state.
- `HI_DPI_MAX_PX` in `Studio.tsx` MUST match the `serve_page_full` cap — change both together.

## [2026-06-15] #42 — v1-11 YOLO ONNX deployed (retrain on +32% annotations; +0.06 mAP50 over v1-10)

**Type:** model-swap | training
**Stage:** training | infra | webapp
**Status:** shipped (deployed to dev)

**Why:** Team added a large batch of new Label-Studio annotations since v1-10 (deployed 2026-06-05, FEATURES #30) — concentrated on the weak direction-arrow/connector and valve_ck/gt/gl classes #30 flagged. User asked to retrain on a cloud GPU and verify the model improved.

**What:**
- **Export:** `experiments/digital_twin/scripts/export_ls_dataset_v1-11.py` (clean copy of the v1-10 exporter → fresh `dataset_v1-11/` dir) pulled ALL dev-LS annotations → 812 train + 80 val tiles, ~32,212 in-schema annotations (+32% vs v1-10's 24,428). 1,139 out-of-schema labels dropped (`valve_needle`, `reducer`, `expander`, `interlock-R`, … — candidates for a v1-12 schema expansion). Same 23-class layout as v1-10.
- **Train:** `experiments/digital_twin/scripts/ec2_train_v1-11.sh` — replays the v1-10 g5.2xlarge flow (yolov8s, imgsz=640, batch=32, 100 epochs, patience=20) **plus a dual-eval** step: after training it pulls v1-10's `best.pt` from S3 and runs `yolo val` on BOTH models against the SAME v1-11 val split (leak-free — split is `sha1(task_id)%10`, stable across exports).
- **Promote (clean swap, no class change):** GitHub release `model-v1-11` (asset `v1-11.onnx`); `Dockerfile` TAG/ASSET/SHA/DEST → v1-11; `webapp/inference.py` MODEL_PATH → v1-11.onnx; `models/MODEL_VERSION.txt` registry updated (current: v1-11; also back-recorded v1-10, which #30 never registered).

**Result (same 80-image / 2,295-instance val split, leak-free):**
- **mAP50 0.745 → 0.805 (+0.060)**; recall 0.682 → 0.759; mAP50-95 0.453 → 0.489; precision flat (0.788 → 0.786).
- Biggest gains exactly where annotation was added: arrow_up mAP50 0.426→0.673, arrow_right 0.403→0.653, arrow_down 0.407→0.626, valve_ck 0.57→0.76, valve_gt 0.77→0.87, Motor 0.80→0.94.
- Minor regressions on tiny-instance classes (inst_local_panel 9 inst 0.96→0.80; valve_3way_relief 18 inst 0.63→0.54) — noise, more annotation would stabilize.

**Notes:**
- **v1-10's headline 0.834 (FEATURES #30) is NOT comparable** — that was on v1-10's own easier 62-image val set. On the current val set v1-10 scores 0.745. The dual-eval is what makes the +0.060 honest. Always re-score the incumbent on the new val split.
- **Cloud-GPU footgun (cost trap):** the new `Deep Learning Base OSS NVIDIA Driver GPU Ubuntu 22.04` AMI ships **torch 2.12**, and `pip install ultralytics` left torch unpinned → `onnxscript 0.5.7` lacks `_framework_apis.torch_2_11/2_12` → `yolo export` crashed. Because that line ran bare under `set -e`, the script aborted before its `shutdown`, leaving the instance **running idle and billing**. Salvaged via SSM (`pip install -U onnxscript` fixed export; ran eval+export+upload+terminate). **TODO for next training script: pin torch to v1-10's known-good version AND guard every step before the final `shutdown` with `|| { …; shutdown }`.**
- Artifacts: `s3://qong-pid-archive-2026-06-02/training/v1-11/` (best.onnx/best.pt/val_v1-1{0,1}.txt/runs/). ONNX sha256 `34022c91…f4e5`.

## [2026-06-13] #41 — KKS valve-tag parsing + All-Data view; readability + cache fixes; empty-deliverable root-cause

**Type:** feature | bugfix | architecture
**Stage:** symbols | text | webapp | webapp/frontend | infra
**Status:** shipped (deployed to dev across commits b741bdf…ab5ac16, verified live)

**Why:** User reported deliverables empty across recent jobs, P&ID unreadable on zoom, "no detections", broken Bulk Review download, and wanted cache auto-clear. Investigation (systematic-debugging) traced the empty deliverables to a TWO-stage failure, not a display bug.

**Root cause of empty deliverables (the 70310-20-* / org-3 jobs):**
1. **Render resolution** — tiles rendered at zoom=4 left tag text ~10-15px; the OpenRouter Vision pass read 0. Fixed: `pdf_to_tiles` zoom 4→6 (grid stays 3×3). Job 50 p0: 0→121 read valves.
2. **Parser tag-format** — the Vision pass then read 221 KKS plant-codes (`20LCM40 BR401`, `20GHB4461`) but `parse_valve_tag` Formats 1-4 expect Western valve abbreviations, so all 221 were dropped → 0 canonical valves. Fixed by **Format 5 (KKS)** in `parser.py`.

**What:**
- `parser.py` **TAG_PATTERN_5**: `[unit 2d][system 3L][aggregate][opt component 2L+counter]`. Maps unit→area, component-code (AA/BR/…) or system→Category, system+aggregate+component+counter→serial (unique → dedup won't merge). First-pass mapping; KKS component→valve-type to be refined per client. 7 tests (`tests/unit/test_parser_kks.py`).
- **All-Data view** (`/jobs/:jobId/data`, `studio/alldata/AllDataView.tsx`): one styled, searchable surface listing every extracted entity (valve/instrument/equipment) + YOLO detection per job, type-filter chips + counts. "All Data" button in Studio top bar. Sibling of Bulk Review.
- **Readability:** page-full render cap 6000→9000px, `HI_DPI_TARGET_PX` 5500→8000, max zoom 4→6, detection/annotation overlays → `vector-effect: non-scaling-stroke` (boxes visible at any zoom — fixed the "no detections" perception, which was 26 detections rendering as 4px specks at ~11× fit-to-screen downscale).
- **Cache auto-clear:** SPA `index.html` served `Cache-Control: no-cache, must-revalidate` (browsers revalidate → new asset hashes; verified `cf-cache-status: DYNAMIC`) + a non-fatal Cloudflare edge-purge step in `deploy-dev.yml`/`deploy-qa.yml` (token from SSM `/may26aws/qong-shared/cloudflare-{purge-token,zone-id}`, auto-skips until set).
- **Bulk Review export** button (was a disabled "coming soon" stub) wired to POST `/export/{type}/{format}`.
- **Re-run button** added to the failed-job screen (`POST /jobs/{id}/rerun` — note: prefix-less path, returns 303).

**Result (verified on dev):**
- Job 50 valve list **0 → 94 rows** after KKS parser + 6× render. Instruments 3→7.
- Job 51 (failed → transient worker-heartbeat crash) reruns to done.
- All-Data route live (200). Page render verified 8000×5658px true vector pixels.

**Notes:**
- **KKS category mapping is first-pass** — `type_code` = component code or 3-letter system. Tags with no component show Category = system (e.g. `GHB`), giving slightly redundant display (`20-GHB-GHB4461`). Refine the KKS component→valve-type table per client.
- **YOLO still under-detects on KKS drawings** (26, mostly arrows) — v1-10 trained on MUK/WS symbology; retrain is the next ML track.
- **Local docker `web` runs baked-image code, NOT host edits** — root-level `parser.py`/`pdf_to_tiles.py` changes can't be tested via `docker compose exec web` without a rebuild; test with host python3 (stdlib-only) or verify post-deploy.
- **Deploy quirk:** `up -d` can leave web/cpu-worker in `Created` (hash-prefixed names) → 502 while `/healthz` (nginx) stays 200; recover with `up -d --force-recreate`. Don't push while a job is mid-run on the cpu-worker (recreate kills it → heartbeat fail).

## [2026-06-13] #40 — Graph extraction v0 in production (line detection → graph → DB) + annotation finishing

**Type:** feature | architecture
**Stage:** lines | graph | webapp | webapp/frontend
**Status:** shipped (commit `b741bdf`, deployed to dev.qongsystems.com 2026-06-13, verified live)
**Spec:** `docs/superpowers/specs/2026-06-13-graph-db-and-annotation-finishing-design.md`
**Supersedes track decision in:** `docs/superpowers/specs/2026-06-05-graph-extraction-design.md` §0/§4 (experimental `dt/main` detour) — built directly on `dev` in the handover destination.

**Why:** The annotation surface (#38/#39) could capture marks but the digital-twin needed *connectivity* — the process-pipe graph — extracted, stored, and rendered. User asked to finish the Studio/annotation polish, integrate line detection, then "complete full graph and store in DB". Brainstormed 4 decisions: build on `dev` (not experimental track), hybrid CV+LLM line detection, file-first + DB-read-index storage (mirror canonical_entities), and full annotation finishing.

**What (multi-agent: 3 parallel build agents + lead integration):**

*Stream 1 — annotation finishing:*
- Palette hotkey badges now read the user's live keymap via `useShortcuts()` (`PalettePanel.tsx`), falling back to defaults — was static design-time keys.
- Persisted "Apply": new `sheet_apply_state` table + `webapp/routers/sheets.py` (`POST/DELETE /api/v1/jobs/{id}/sheets/{n}/apply`, `GET /sheets/applied`); `Studio.tsx` seeds `appliedBySheet` on load. Survives reload.

*Stream 2 — line detection (`webapp/graph/` package, pure/unit-tested):* `loader` (canonical + page image + tile geometry; tile-local→page-pixel translation), `linker` (rapidocr crop-OCR + rapidfuzz fuzzy-match + class-prior fallback), `tracer` (`OpenCVLineTracer`: adaptive-threshold → bbox-mask → skeletonize → connected-components → resolution-scaled min-length + area/span line-likeness filter → RDP), `resolver` (endpoint→nearest-bbox snap), `fallback` (OpenRouter vision when edges<0.3×nodes), `assembler` (networkx.MultiGraph → `canonical_graph.json` spec §3), `pipeline.extract_graph` (DB-free). Deps added: `opencv-python-headless`, `scikit-image`, `networkx`.

*Stream 3 — storage + API + UI + wiring:* `graph_nodes`/`graph_edges` DB read-index + `webapp/graph/graph_db_index.sync_graph_to_db` + backfill `webapp/scripts/index_graph_to_db.py` (mirror canonical_entities exactly). `webapp/routers/graph.py` `GET /api/v1/jobs/{id}/graph` merges file + `graph_corrections` (user edges), 404 `no_canonical` / 409 `canonical_required`. Wired into `pipeline_runner.py` after in-place YOLO inference (`tile_local_detections=True`), non-fatal. `GraphLayer.tsx` SVG overlay in `PidCanvas`/`Studio` (nodes=circles, edges colored by method: opencv green / llm_fallback yellow-dash / user cyan), right-rail Graph toggle + stats chip.

**Result (real job 2, 5500px hi-DPI page):**
- 31 nodes, **26 linked to canonical (84%** — exceeds spec ≥70% target).
- 23 edges (CV `opencv` + `llm_fallback` mix); fallback engaged because raw CV was edge-sparse.
- Orphan lines **3600 → 70** after adding resolution-scaled `min_length` (frac 0.012) + area/span≤3 line-likeness filter + a 150-orphan cap (diagnostic only).
- Coordinate fix verified: tile-local bbox `[3285,1311]@tile_p0_r0_c1` → page-pixel spanning x 827–5351, y 1311–2876.
- Tests: backend 240 pass (1 pre-existing env-only failure `test_sheets_empty_when_no_tiles`, confirmed on clean baseline — reads real `job_outputs/` tiles locally); 44 new graph/sheets tests; frontend tsc clean + 73 vitest.

**Notes / gotchas for next session:**
- **`Job.gpu_detections` bboxes are TILE-LOCAL** (inference.py:255), but the graph model is page-pixel. The glue MUST pass `tile_local_detections=True` to `extract_graph`; loader translates via `compute_tile_offsets`. Forgetting this clusters every node top-left.
- **OpenCV line tracing underperforms on hi-DPI pages** — most usable edges came from the LLM fallback. This is the predecessor spec's "Week-2 hard-gate" scenario; the designed graceful degradation handled it. Tuning the CV tracer (or declaring LLM-primary for hi-DPI) is a v0.5 follow-up. The `LineTracer` Protocol seam makes a swap cheap.
- **Rejecting an *auto* edge is not wired** — auto edges live in the file/index, not `graph_corrections`, so there's no per-auto-edge reject key. GET merge is additive. v0.5.
- New tables created in local Postgres via `create_all`; on deploy they auto-create on startup. Live OpenRouter client is repo-root `extractor.py`, NOT `webapp/extractor.py`.
- **Browser E2E not yet run** — needs deployed/rebuilt env (new server code + Vite build). Run post-deploy on dev.

## [2026-06-12] #39 — Qong Studio UI redesign: sheet-picker dropdown, category palette sidebar, Apply action, details strip

**Type:** feature | architecture
**Stage:** webapp/frontend
**Status:** shipped

**Why:** User-driven redesign — flagged the existing 3-column layout (SheetRail + Canvas + Properties) as cramped, with the sheet rail eating canvas width while sheets are infrequently switched. Design landed via a Claude Design handoff bundle (chats 1–6, final iteration 2026-06-12) with explicit asks: sheets-as-dropdown in the top bar, collapsible-category palette on the left as the main symbol picker, full-width canvas with an explicit "I'm done with this sheet" Apply action, and a right details panel that can collapse to a slim vertical strip so the canvas can run edge-to-edge during heavy marking.

**What:**
- New `webapp/frontend/src/studio/SheetPicker.tsx` — top-bar pill dropdown that lists every sheet (real tile thumbnails or generated SheetGlyph fallback) with a `applied ✓ N` badge per sheet. Replaces the left rail.
- Deleted `webapp/frontend/src/studio/SheetRail.tsx`. `StudioTopBar.tsx` now receives `sheets / activeSheet / onActivateSheet / projectId / dark / realSheets / appliedBySheet` and mounts `SheetPicker` inside `.proj-meta`. The "42 issues" badge is gone from the top bar.
- `annotations/PalettePanel.tsx` restructured into the draw.io-style collapsible category list (Valves, Instruments, Equipment). Rows are glyph + full name + hotkey badge. **Test contract preserved** — `data-testid="palette-item-${cat}-${sub}"`, click-to-arm semantics, and `style.background contains 'var(--qong-pink'` on the active row all still hold; all 6 existing tests pass.
- `Studio.tsx` body grid switches to `studio-body--draw` variants: `with-props` (248 / canvas / 348) or `with-strip` (248 / canvas / 44). Adds `appliedBySheet` state, `propsOpen` state, and a `showToast` helper.
- Canvas toolbar inside Studio now hosts a primary **Apply · N** button (right-aligned, pink gradient) — disabled when zero marks, switches to green **Applied** after click. Annotation list resetting Apply count is via the `applied` derived value.
- `PropertiesPanel.tsx` gains an `onCollapse` prop + Export Deliverables section (Instrument Index, Datasheets, I/O List, Valve List, Control Narrative, Cause & Effect — all wired via optional `onExportDeliverable(type)`). When collapsed, `Studio.tsx` renders a full-height `.props-strip` button (vertical "DETAILS" label + issue badge at bottom).
- `design/studio.css` — ~430 new lines under a "REDESIGN (Jun 2026)" header. Uses existing semantic tokens (`--bg`, `--surface`, `--fg-*`, `--qong-*`) so light/dark theming works through the existing `[data-theme="dark"]` selectors with no new theme overrides needed.

**Result:**
- `npx tsc --noEmit` clean. `npx vitest run` → 15 files / 66 tests passing (incl. 6 PalettePanel tests).
- Canvas gains ~232px horizontal real estate when the details strip is collapsed; ~120px even when details are open vs. the old layout.

**Notes:**
- Apply is **UI-only state** — `appliedBySheet[sheetId] = applyCount`. Annotations are already persisted on creation via `useAnnotations.create`; "Apply" is a reviewer's intent ("done with this sheet") rather than a new backend mutation. If/when a server-side `sheet_applied_at` lands, the same `handleApply` will fire the POST and the UI doesn't change.
- Sheet picker uses real tile thumbnails (`RealSheet.url`) when `realSheets` is populated; otherwise the deterministic `SheetGlyph` SVG, same fallback the rail used.
- The hotkey labels in the palette (1, 2, s, g, …) are **visual hints only** — actual binding stays inside `useShortcutDispatcher` (FEATURES #38). When a user customises shortcuts, the keys in the palette will drift; future work: read bindings from `useShortcuts` and surface the user's actual keys.
- Design bundle archived at `/tmp/qong_design/qong-app/` (not committed). 6 chat transcripts captured the iteration history if we need to revisit a specific decision.

## [2026-06-11] #38 — Qong Studio marking + graph annotation system (6-phase end-to-end)

**Type:** feature | architecture
**Stage:** webapp | webapp/frontend | training
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-11)
**Spec:** `docs/superpowers/specs/2026-06-10-qong-studio-marking-design.md`

**Why:** Studio could surface model detections but couldn't accept user marks, confirmations, rejections, or line-drawing. We needed one prod-grade annotation surface that captures every action as YOLO/graph training signal, lets users define their own shortcuts, and renders the whole page (not just one tile) so cross-tile pipes/loops/interlocks become trivial. User authorized direct build (no approval gate).

**What (one session, six phases, multi-agent):**

**Phase 1 — Backend schema + APIs** (commits `4af85c1`, `ac505dc`, `e6a6314`):
- `user_annotations` + `graph_corrections` tables (file-first + DB-read-index pattern; same architecture as `canonical_entities`).
- `users.shortcuts` JSONB column for per-user keymap.
- POST/GET/PATCH/DELETE on `/api/v1/jobs/{id}/{annotations,edges}` with collision rule (same-class on existing detection → user_confirmed; different-class → user_added + model_corrections(delete); empty region → user_added + model_corrections(add) linked via FK).
- `/api/v1/jobs/{id}/page/{n}/full` (cookie-authed FileResponse of the full-page render that pdf_to_tiles already emits).
- `/api/v1/users/me/shortcuts` GET/PATCH/POST(reset). 14 DEFAULT bindings; modifier-chord + multi-char keys rejected.
- 41 pytest cases (10+13+5+13).

**Phase 2 — Studio canvas pivot to full-page** (commit `d5cd41d`):
- PidCanvas now renders `page_{n}_full.png` and translates every model-detection bbox from tile-local into page-pixel coords via `computeTileOffsets()` (mirror of pdf_to_tiles 3×3/20% geometry).
- 4-layer SVG: model detections + user_annotations + edges + in-flight edge preview.
- Theme-coherent status palette (`--info`/`--qong-pink`/`--ok`/`--error`) and line-type stroke styles (`--scan-cyan` solid / `--qong-pink` dashed / `--qong-purple` long-dash / `--warn` dash-dot) with arrowheads on flowing lines.
- Mode-aware event handlers (`select`/`mark-symbol`/`draw-edge`), entity snap (28 px) on edge draw, Escape cancels in-flight draws.
- Legacy single-tile mode preserved as fallback.

**Phase 3 — Symbol palette + status states** (commit `23b0566`):
- `PalettePanel` (220 px left rail, hierarchical class→sub_class), `ModeToolbar`, `StatusBadge` pill renderer, `useAnnotations` hook with optimistic create/patch/delete.

**Phase 4 — Edge drawing** (commit `23b0566`):
- `LineTypeToolbar` (4 buttons with live SVG stroke previews), `EdgeMetadataDrawer` (slide-up panel for relation_type + group_id + metadata K/V), `useEdges` hook.

**Phase 5 — Per-user shortcuts** (commit `23b0566`):
- `/account/shortcuts` page (capture input + action picker + conflict warning + reset), `useShortcuts` + `useShortcutDispatcher` hooks, pure `normalizeKey()` with input/textarea bypass + modifier-chord rejection.

**Phase 6 — Training loop + metrics** (commit `23b0566`):
- `export_annotations_for_yolo.py` (page-pixel → tile-local normalized YOLO labels, idempotent append), `export_graph_for_training.py` (JSONL), `/api/v1/admin/annotations/metrics` endpoint (totals, by_status, per_day_last_30), `AdminAnnotationMetrics` admin page.

**Result:**

| Metric | Value |
|---|---|
| New backend tables | 2 (`user_annotations`, `graph_corrections`) + 1 column |
| New API endpoints | 12 |
| New frontend routes | 2 (`/account/shortcuts`, `/admin/annotation-metrics`) |
| New frontend components | 9 (PalettePanel, ModeToolbar, StatusBadge, LineTypeToolbar, EdgeMetadataDrawer, Shortcuts, AdminAnnotationMetrics + 2 hooks) |
| pytest cases added | 63 (40 router + 22 export + 1 admin metrics — actually 4) |
| vitest cases added | 45 (palette 6, badge 8, mode toolbar implicit, line-type 3, edge-drawer 4, shortcuts 8, keyboard 12, admin metrics 4) |
| Total new tests this session | 108, all green |

**Notes:**
- **FastAPI 204 quirk:** 204 endpoints in this codebase MUST use `status_code=204`, `response_class=Response`, NO `-> None` return annotation, NO `responses[204]`, and `return Response(status_code=204)` explicitly. Production FastAPI tripped a registration-time assertion otherwise; local pytest's older FastAPI didn't catch it. Two patches (`ac505dc`, `e6a6314`) sorted it. Worth a CLAUDE.md note.
- **Tile geometry duplicated** in `pdf_to_tiles.py` and `PidCanvas.computeTileOffsets` (3×3, 20% overlap). If those defaults ever change, change BOTH ends in the same PR.
- **Tile-local → page-pixel translation** happens client-side via the page-full image's `naturalWidth/Height`. No new backend coord-translation endpoint needed.
- **Collision rule** at POST /annotations is the magic that makes "click an existing detection to confirm" feel natural without a separate API verb.
- **page-full endpoint is cookie-authed** so plain `<img src>` works same-origin. Cross-origin (LS-style) consumers would need a separate no-auth route.
- **Status colors are part of the brand palette now** — `--qong-pink` for user marks signals "this is yours" everywhere it appears.

---

## [2026-06-10] #37 — Cross-job duplicate-tag audit surface

**Type:** feature
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #34 unblocked cross-job queries; FEATURES #36 made them clickable. But a user still had to know what tag to search for. Promoting "tags appearing in ≥2 jobs" to a top-level audit list turns the "what's duplicated across our corpus?" question from "you'd need to write SQL" into one glance at the page.

**What:**
- `/api/v1/admin/entities/aggregates` extended with `duplicate_tags_across_jobs`: top-15 tags by `(job_count desc, row_count desc)` where `COUNT(DISTINCT job_id) ≥ 2`. SQL `GROUP BY tag HAVING COUNT(DISTINCT job_id) >= 2`.
- `AdminEntities.tsx`: new section between the top-N grid and the search filter — title with `AlertTriangle` icon, table of tag · job_count · total_rows. Clicking a row fills the tag search box and resets other filters, dropping the user straight into the table view for that tag.
- `types.ts`: field marked optional so older deploys (without the field) don't break the UI.

**Result (Playwright-verified live on dev):**

15 duplicate tags surfaced automatically — the 32047 audit from FEATURES #35 is now one of many:

| Tag | Job count | Total rows |
|---|---|---|
| 62-BF-151014 | 3 | 3 |
| 62-BF-151031 | 3 | 3 |
| 62-DB-151042 | 3 | 3 |
| 61-BV-149128, 149131, 32047, 149130, 32049, 32050, 32052, 32053, 32054, 32055, 32048 | 2 each | 2 each |
| 61-CK-149165 | 2 | 2 |

**Three tags appearing in 3 jobs each** is a strong "same drawing re-extracted three times" signal — worth chasing operationally (wasted compute, deliverable consistency).

**Notes:**
- Capped at 15 server-side to keep payload bounded; full inspection via `?tag_contains=<tag>` (the click handler already wires this).
- Sorted by `job_count desc, row_count desc` because the spread-across-many-jobs case is the strongest audit signal.
- Screenshot: `themes/screenshots/admin-entities-duplicates.png`.

---

## [2026-06-10] #36 — Admin Entity Index UI (visual surface for cross-job queries)

**Type:** feature
**Stage:** webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #35 exposed `/api/v1/admin/entities` + `/aggregates` but the data wasn't reachable without a curl loop. A frontend page makes the cross-job query power visible to anyone with super_admin role.

**What:**
- `webapp/frontend/src/admin/AdminEntities.tsx` (new) — three workflows on one page:
  1. **Aggregates strip**: total entities, per-class counts (1,304 / 625 instruments / 679 valves on dev today).
  2. **Top sub-classes + top jobs** as two side-by-side clickable lists. Clicking a sub-class filters the table to `entity_class=valve, sub_class=X`; clicking a job filters to `job_id=N`.
  3. **Filter bar + paginated table**: tag-substring search, class + sub_class dropdowns, job-ID input. 50 rows per page. Each row links to `/jobs/{id}` (Studio).
- Sub-class dropdown options derived from the live `top_valve_sub_classes` payload so it stays in sync without a separate API call.
- Wired into `AdminLayout` nav (new "Entity Index" item, Database icon), `App.tsx` (`/admin/entities` route), `admin/api.ts` (`getEntityAggregates`, `searchEntities`), `admin/types.ts` (3 new interfaces).

**Result (Playwright-verified live on dev):**
- Page loads at `/admin/entities` with full aggregates: total=1,304, by_class={valve:679, instrument:625}.
- Top valve sub_classes correctly shown: VB(205), BV(154), VF(90), DB(69), BF(68), VD(17), GL(14), CK(14), PV(13), VCS(10).
- Tag-substring search `"32047"` returns exactly **2 hits**: job 38 `61-BV-32047` + job 43 `61-BV-32047`, both on `MUK-61-0-0218-002-25L3`. Confirms duplicate is the *same drawing across two job runs* (re-extraction), not two physical valves on different drawings — actionable audit signal previously invisible.

**Notes:**
- The 2-hit duplicate is now visible from the UI without curl. Earlier scope for an audit endpoint isn't necessary — the existing search + tag substring covers the use case.
- Sub-class dropdown only appears when `entity_class=valve` — keeps the UI from showing a meaningless filter when the user picked instruments.
- Screenshot: `themes/screenshots/admin-entities-search-32047.png`.

---

## [2026-06-10] #35 — Admin cross-job entity search + aggregates endpoints

**Type:** feature
**Stage:** webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** FEATURES #34 added the `canonical_entities` DB index but no surface to query it without raw SQL. Production usage (admin dashboards, customer summaries, duplicate-tag audits) needs an authenticated HTTP endpoint.

**What:**

- `GET /api/v1/admin/entities` — filterable cross-job search. Query params: `entity_class`, `sub_class`, `tag_contains` (ILIKE substring), `job_id`. Pagination via `offset` + `limit` (capped at 500). Returns rows with `job_id, entity_id, entity_class, sub_class, tag, pid_number, sheet_number, fields, updated_at`.
- `GET /api/v1/admin/entities/aggregates` — single-call dashboard payload: `total_rows`, `by_class` (per-entity-class counts), `top_valve_sub_classes` (top-10), `top_jobs_by_valve_count` (top-10).
- Both `require_super_admin`.
- Reads pipeline-emitted state — entity_overrides NOT applied. For user-visible state, use the deliverables API.

Frontend bonus: expanded `VALVE_SUB_CLASS_LABELS` in `studio/buildElements.ts` to cover the CSV-side codes the backfill surfaced (VB=Block, VF=Flow, VD=Drain, PV=Pressure, SB=Sample/Bleed). Without this map ~205 ball-valve-equivalents were rendering as "Valve (VB)" placeholders.

**Result (live on dev as super_admin):**

| Endpoint | Sample output |
|---|---|
| `/aggregates` | `total_rows=1304, by_class={valve:679, instrument:625}` |
| `?tag_contains=32047` | 2 hits: job 38 `61-BV-32047` + job 43 `61-BV-32047` (duplicate-tag audit) |
| `?entity_class=valve&sub_class=BV` | 154 total ball valves across all jobs |

**Notes:**

- `top_valve_sub_classes` revealed **VCS** (10) as a new sub_class not yet in the frontend label map — add when seen often enough to matter.
- The duplicate `61-BV-32047` in jobs 38 + 43 is real (same `pid_number` and `sub_class`) — either the same physical valve re-extracted across drawing revisions, or a legitimate duplicate. Cross-job audit endpoint is the right tool to chase this.
- Endpoint serving order: dev took ~75 seconds to flip the response Content-Type from `text/html` (SPA catch-all) → `application/json` after push, because the FastAPI router only re-registers on container restart. Worth checking via Content-Type when polling deploy state, not just status code.

---

## [2026-06-10] #34 — Dynamic PropertiesPanel + DB-backed canonical_entities index

**Type:** feature | architecture
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** Two stacked moves toward production-grade studio output.

1. **Frontend dynamism (Phase A):** The Studio right panel ("Selected Element"
   + "Elements on Sheet") was rendering hard-coded prototype tags
   (`PV-203` / `V-101` / `FT-101` / `P-101` / `E-104`) regardless of real
   data, because `Studio.tsx` fell through to `DEMO_ELEMENT_DATA` whenever
   `selectedId` wasn't in the prototype dictionary — which was *always* once
   a real bbox was clicked. Effect: clicking a real bbox highlighted the
   rect but never updated the panel; users reported "the click does
   nothing" even though D1.5 entity matching was working correctly behind
   the scenes.

2. **Cross-job queryability (Phase B):** Until today, "find all valves of
   size 8 across customer X's jobs" required parsing N `canonical.json`
   files. Production dashboards / customer summaries / audit queries need
   one SQL `WHERE` clause, not a Python loop.

**What:**

**Phase A — PropertiesPanel real-data wiring:**
- `webapp/frontend/src/studio/buildElements.ts` (new) — derives a
  `Record<entity_id, CanvasElement>` for the active tile, joining live
  detections with canonical entities. Includes a `sub_class → human label`
  table mirroring `api_v1.py:_yolo_class_to_canonical` so "valve_bv"
  surfaces as "Ball Valve". Detections without `entity_id` (direction
  arrows, page connectors) are excluded — non-editable.
- `Studio.tsx` — fetches `valve_list` + `instrument_index` entities at
  mount, builds an `entityIndex` Map keyed by UUID, memoises a per-tile
  `realElements` derivation. `panelElements` is real when present,
  `DEMO_ELEMENT_DATA` otherwise. When real data first lands, `selectedId`
  auto-jumps from `"PV-203"` to the first real entity_id on the tile.
- `PropertiesPanel.tsx` — switched to `Object.entries(elements)` so row
  click + isSel checks use the dictionary key (entity_id), not `el.tag`.
  `onSelect` contract now propagates `entityClass` so the drawer opens
  to the right deliverable.

**Phase B — `canonical_entities` DB table:**
- `webapp/models.py` — `CanonicalEntityRow` ORM. Mirrors `CanonicalEntity`
  1-for-1 plus `canonical_schema_version` for cross-version filtering.
  Unique on `(job_id, entity_id)`; indexed on `entity_class` + `tag` for
  the common "find all valves named X" query. Created automatically on
  startup via `Base.metadata.create_all(engine)`.
- `webapp/deliverables/canonical_db_index.py` — `sync_canonical_to_db()`
  per-job idempotent upsert + stale-row delete (re-emit truth wins).
  Lives in its own module to keep `pipeline_emitter.py`'s "pure function
  — no DB, no network" contract intact.
- `webapp/pipeline_runner.py` — dual-writes after canonical.json emit.
  Non-fatal: DB sync failure logs but doesn't roll back job "done" state.
- `webapp/scripts/index_canonical_to_db.py` — backfill CLI for legacy
  canonical files. Same idempotent path; safe to re-run.

**Source of truth remains the on-disk `canonical.json`.** The DB table is
a denormalised read-index — never the edit target. User edits still live
in `entity_overrides` and merge at request time via the deliverables API.
Deliverable generators are unchanged.

**Result:**

| Metric | Value |
|---|---|
| Legacy GCP-era paths migrated (jobs table) | 36 |
| Canonical.json files backfilled total | 49 |
| canonical_entities rows indexed | **1,304** (679 valves + 625 instruments) |
| Backfill errors | 0 |
| Cross-job query verified | `SELECT … WHERE tag LIKE '%32047%'` → job 38 + job 43 |
| Top-5 jobs by valve count (instant) | 6 (51), 3 (50), 5 (49), 14 (46), 19 (41) |
| Frontend tests | 21/21 pass |

**Notes:**

- **Surprise sub_class diversity:** the DB shows VB (205), BV (154), VF
  (90), DB (69), BF (68), VD (17), GL (14), CK (14), PV (13), SB (10) as
  the most common valve sub_classes. Only BV/BF/GT/CK/DB/GL/CV/NCBV/
  PNEUCTRL/RELIEF_SAFETY/3WAY_RELIEF are in the
  `VALVE_SUB_CLASS_LABELS` map (FEATURES #31 mirror) — the others
  (VB, VF, VD, PV, SB) come from CSV-side customer conventions, not the
  YOLO vocabulary. Currently render as "Valve (VB)" etc. — fine for now;
  expand the map as customer feedback rolls in.
- **Duplicate tag observation:** `61-BV-32047` exists in both job 38 and
  job 43. Worth an audit pass — might be the same physical valve
  re-extracted, or a legitimate duplicate across drawings. Cross-job
  audit queries like this are exactly the use case the DB index unlocks.
- **The `Job.output_csv_path` migration (`/www/wwwroot/qong_poc/` →
  `/app/job_outputs/`)** was a one-time SQL UPDATE on 36 jobs that had
  survived the AWS migration (FEATURES #21) with stale GCP paths. Memory
  rule "no autonomous job mutation" still stands — this was an
  explicit user authorisation ("update all the jobs").

---

## [2026-06-10] #33 — Backfill canonical.json for legacy jobs + drawer 404→notFound routing fix

**Type:** bugfix
**Stage:** webapp | webapp/frontend
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-10)

**Why:** Reported on dev.qongsystems.com/jobs/38 — clicking a detection opened the DatasheetDrawer with `0 of 0 fields` and `Failed to load: HTTP 404`. Two independent bugs were stacking:

1. **Legacy-data gap.** The canonical-entity emitter shipped 2026-05-28 (commit `024cf4a`, FEATURES #26). Jobs 2–39 were processed before that date and have `valve_list.csv` + `instrumentation_index.csv` on disk but no `canonical.json` next to them, so `GET /api/v1/jobs/{id}/entities` raises `JobCanonicalNotFound` → 404.
2. **Drawer 404 routing broken for GETs.** `getEntities` uses `call<T>` which threw plain `Error("HTTP 404")`, not `HttpError`. The drawer's `if (e instanceof HttpError && e.status === 404) setNotFound(true)` branch therefore never fired and the raw error message leaked through as `Failed to load: HTTP 404`. The `HttpError` path was only wired into `callJson` (write verbs).

**What:**

- `webapp/scripts/backfill_canonical.py` (new) — one-shot CLI:
  - Modes: `--from-db` (iterates `models.Job` rows where `output_csv_path` is set; default mode walks the filesystem under `/app/job_outputs`).
  - For each job missing `canonical.json` but having at least one of `valve_list.csv` / `instrumentation_index.csv`, calls `webapp.deliverables.pipeline_emitter.write_canonical_for_job(...)` — same code path the pipeline runs at job-completion time.
  - Idempotent (skips dirs that already have `canonical.json`).
  - Verbose per-job logging + a final tally.
- `webapp/frontend/src/studio/api.ts` — moved `HttpError` declaration above `call<T>` and switched `call<T>` to `throw new HttpError(...)` for both opaque-redirect (401) and `!res.ok` (status) cases. Backwards-compatible: `HttpError extends Error`, all existing `err.message` consumers (CreateUserModal, CreateProjectModal, JobDetail, Login) continue to work unchanged.
- `webapp/frontend/src/studio/datasheet/DatasheetDrawer.tsx` — `notFound` copy rewritten to call out the legacy-job case explicitly so re-runs are the obvious remedy ("Most likely this is a legacy job processed before the editable-entities feature shipped (2026-05-28). Re-run the job from the dashboard to regenerate `canonical.json`...").

**Result:**

Live backfill on dev (`docker compose exec -T web python -m webapp.scripts.backfill_canonical --from-db`):

| Outcome | Count |
|---|---|
| Wrote canonical.json | 6 (jobs 2, 38, 39, 40, 42, 43) |
| Already present, skipped | 7 |
| No CSVs found (stale DB paths — see Notes) | 36 |
| Errors | 0 |

`GET /api/v1/jobs/38/entities?deliverable_type=valve_list` now returns 200 with 21 valves + 14-column schema. `GET .../detections` now attaches `entity_id` to 21 of 71 detections (the rest are direction labels, which intentionally have no canonical match per FEATURES #31).

**Notes:**

- **Discovered orthogonal issue: 36 jobs have stale GCP-era paths in their DB rows** (`output_csv_path` like `/www/wwwroot/qong_poc/job_outputs/N/...`). These survived the AWS migration (FEATURES #21) but the DB column wasn't rewritten — the files actually live at `/app/job_outputs/N/` on the AWS EC2. The backfill script can't reach them via `--from-db` because it follows the (wrong) DB path. The API's `_load_job_or_404` also can't load them. **Fix is one SQL UPDATE** but punted out-of-scope here; flagged in SESSION_STATE next-steps. Memory `feedback_job_running_policy.md` (no autonomous job mutation) applies — surface, don't fix unilaterally.
- The backfill found **3 unexpected org-scoped jobs missing canonical.json** (40, 42, 43) despite being post-emitter. Probable explanations: jobs that crashed before the emit step, or were created via a code path that doesn't call `write_canonical_for_job`. Worth a follow-up audit but not blocking — they're now backfilled.
- **`call<T>` now throws `HttpError`** — any future GET endpoint can branch on status code without changes. Mirrors what `callJson` already did.
- **Frontend test suite** — there are existing vitest cases for the drawer's `notFound` UX. Copy text was changed; the assertion most likely checks for the bold "no editable entities" heading; if the test was string-coupled it'll need updating. Not run from this session.

---

## [2026-06-08] #32 — Auto-register TASKS_CREATED webhook on new LS projects

**Type:** bugfix
**Stage:** webapp
**Status:** shipped (committed on `dev`, auto-deploys via `deploy-dev.yml`)

**Why:** LS 1.23 Community has no org-level webhooks (FEATURES #30) — every
project needs its own row. The auto-tile feature (PDF dropped via LS Import →
9 PNG tiles) only works on projects whose webhook is registered. Until today,
`get_or_create_project()` created the project but did NOT register a hook, so
any project created after the initial backfill silently missed the auto-tile
flow. Found on 2026-06-08: 3 of 36 dev LS projects (35/36/37 — `void1`/`void1`/
`void2`) were hookless; PDFs dropped there never tiled. Same root cause is
about to bite the new LS projects that get spawned when jobs 47-49 are re-run
post `OPENROUTER_MODEL` fix — each will create a fresh project, none of which
would have the hook without this fix.

**What:**

- `webapp/label_studio_client.py`:
  - Added module constants `WEBAPP_BASE_URL` (defaults `http://localhost:8000`,
    overridden by env on AWS) and `LS_WEBHOOK_SECRET` (empty disables
    registration — empty-string means the receiver would 401 anyway, so we
    don't bother creating a poisoned hook).
  - New `_register_tasks_created_webhook(project_id)` — POSTs to
    `LS_URL/api/webhooks/` with body
    `{project, url, actions=["TASKS_CREATED"], headers={"X-LS-Webhook-Secret": ...}, is_active=True}`.
    Best-effort: logs and returns False on any 4xx/5xx/exception. Caller still
    treats project creation as successful — tile-push doesn't depend on the
    hook, only the LS-Import-UI PDF path does.
  - `get_or_create_project()` now invokes the helper immediately after a 201
    on `POST /api/projects/`. Existing-project branch is unchanged (no
    mutation of pre-existing config — backfill remains a separate admin
    concern).
- `tests/unit/test_label_studio_client.py` (new, 5 tests):
  - existing-project short-circuits → no POST calls
  - new-project → webhook POST with correct URL + body + secret header
  - webhook 5xx → project_id still returned (best-effort contract)
  - empty `LS_WEBHOOK_SECRET` → webhook step skipped silently
  - `is_configured()` false → returns None immediately, no HTTP

**Result:** 5/5 new tests pass; existing 56 unit tests unchanged (the one
pre-existing `test_sheets_empty_when_no_tiles` failure is the Postgres DB-leak
flake noted in SESSION_STATE — predates this commit).

**Notes:**

- The 3 unhooked projects (35/36/37) were patched up via one-off SSM script
  this morning (cmd id `d6a671d8`). They now have webhook ids 34/35/36
  respectively.
- This fix only covers the *creation* path. Pre-existing projects without a
  webhook still need the one-off admin script — `webapp/scripts/` would be
  the natural home for a "backfill webhooks" CLI but it's not worth one until
  someone needs it again.
- The webhook receiver enforces shared-secret via `hmac.compare_digest`
  (`webapp/routers/webhooks.py:_verify_secret`). The Authorization-Bearer
  fallback in the receiver isn't used here — we set `X-LS-Webhook-Secret`
  explicitly, which is the recommended path per the receiver's docstring.
- No model retraining or schema migration needed.

---

## [2026-06-06] #31 — D1.5: class-based entity_id matching on canvas detections (Spec A unblock)

**Type:** bugfix
**Stage:** webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-06)

**Why:** The `/api/v1/jobs/{id}/detections` endpoint was supposed to attach `entity_id` to each YOLO bbox so the studio canvas click → DatasheetDrawer flow could key entities by UUID. The existing logic matched by string equality of `detection.label` → `canonical_entity.tag` — which never fires in production because `webapp/inference.py` emits YOLO class names (`"valve_bf"`) as `label`, never engineering tags. Effect: every detection had `entity_id=null`, blocking Spec A D2 (DatasheetDrawer real-data wiring) since the post-v1-9 deploy. Fix surfaced when starting D1.5 work post-v1-10.

**What:**

- `webapp/routers/api_v1.py`: rewrote the enrichment block as a 3-step matcher (`_attach_entity_ids` helper):
  1. **Tag-equality.** `detection.valve_tag` / `tag` / tag-shaped `label` → `entity.tag`. Preserves the legacy GPU-worker path + existing fixture shape.
  2. **Label-as-tag.** Same lookup keyed by `label`.
  3. **Class compatibility (FIFO).** YOLO class string (from `label` *or* legacy `yolo_class`) → `(entity_class, sub_class)` via `_yolo_class_to_canonical()`, then take the first un-consumed canonical entity matching that class. Sub-class match preferred; falls back to class-only.
- `_yolo_class_to_canonical` mapping (covers v1-10's 23 classes + v1-9 legacy labels):
  - `valve_*` → `("valve", <suffix>.upper())`
  - `inst_*`, `interlock`, `SIS-R` → `("instrument", None)`
  - `Motor`, `Pump/Dwg Pump`, `Pump_Dwg_Pump` → `("equipment", None)`
  - `arrow_*`, `connector_*` → `(None, None)` (direction labels not editable)
- Tests: replaced single unrealistic test with 3 focused tests covering (a) tag carriers, (b) realistic v1-10 `label`-as-class shape, (c) legacy `yolo_class` field shape. All 7 detections tests pass.

**Result:**

Detections with a canonical-class peer (valve, instrument, equipment) now get a real `entity_id`. DatasheetDrawer canvas-click now opens for the matched class. Pairing is order-based (not spatially correct) because canonical entities' bboxes are still `(0,0,0,0)` placeholders — see notes.

**Notes:**

- **Spatial IoU matching is the v2 of D1.5,** deferred until `pipeline_emitter` populates real bboxes on canonical entities. Today two `valve_bv` detections pair with the first two `valve_bv` canonical entities in iteration order; a user clicking the second-from-left valve will see whichever entity is second in the canonical list, not necessarily the one physically there. Acceptable degraded state for the field-edit flow but produces wrong-pair UX on dense same-class clusters.
- Direction labels (`arrow_*`, `connector_*`) are intentionally non-editable. They render on the canvas but click does nothing.
- Pre-existing failing test `test_sheets_empty_when_no_tiles` (Postgres DB-state leak between tests) is unrelated and fails on the prior commit too — left alone.

---

## [2026-06-05] #30 — v1-10 YOLO ONNX deployed (23 classes incl. flow direction, 2× mAP50 over v1-9)

**Type:** model-swap
**Stage:** training | infra | webapp
**Status:** shipped (deployed to dev.qongsystems.com 2026-06-05 17:28 UTC)

**Why:** v1-9 didn't detect the 6 direction labels the team added in LS over the past week (arrow_up/down/left/right + connector_in/out), blocking the flow-direction step of graph-extraction v0 (digital twin sub-project G). Rather than ship a separate direction-detector running alongside v1-9 (two-pass inference, two ONNX files), the call was to retrain a single unified model with all 23 classes from LS — both gains (direction) and the existing valve/instrument vocabulary in one pass.

**What:**

1. **Single 23-class model** trained from `yolov8s.pt` on 24,428 annotations exported from all 33 dev-LS projects:
   - 9 valves: `valve_bv`, `valve_ncbv`, `valve_gt`, `valve_bf`, `valve_ck`, `valve_db`, `valve_relief_safety`, `valve_gl`, `valve_3way_relief`
   - 8 instruments / signals: `inst_field`, `inst_bpcs`, `Motor`, `Pump/Dwg Pump`, `inst_sis`, `SIS-R`, `interlock`, `inst_local_panel`
   - 6 direction (NEW): `arrow_up`, `arrow_left`, `arrow_right`, `arrow_down`, `connector_out`, `connector_in`
2. **LS schema hygiene:** before training, two LS label typos consolidated — `valve_3way_releif` → `valve_3way_relief` (3 results) and `valve_pnuectrl` → `valve_pneuctrl` (16 results, 28 project configs). Idempotent fixer at `experiments/digital_twin/scripts/fix_ls_typos.py`.
3. **Dataset pipeline:** new exporter `experiments/digital_twin/scripts/export_ls_dataset.py` walks all LS projects, applies a global 23-class ID map, emits a standard YOLO dataset (605 train + 62 val, 90/10 split). Handles both `/data/upload/` LS storage and webapp tile-route URLs. Output staged to `s3://qong-pid-archive-2026-06-02/training/v1-10/dataset_v1-10.tar` (258 MB).
4. **Training:** g5.2xlarge on-demand in ap-south-1b (GPU spot quota = 0 in account; on-demand cost ~$1.21/hr × ~12 min training + setup = ~$3.50 total including a failed first run). Autonomous script: dataset pull → smoke (yolov8n, 1ep) → full train (yolov8s, 100ep, imgsz=640, batch=32, patience=20) → ONNX export → S3 upload → self-terminate. Script at `experiments/digital_twin/scripts/ec2_train_v1-10.sh`.
5. **Production wiring:**
   - GitHub release `model-v1-10` on `Qong-Systems/qong_product` (https://github.com/Qong-Systems/qong_product/releases/tag/model-v1-10), asset `v1-10.onnx` (42.6 MB, sha256 `896e42561fddd8014fd6021176ce903a5bb0afeffa3717b436e32a56c19e3142`)
   - `Dockerfile`: TAG/ASSET_NAME/MODEL_SHA/DEST bumped to v1-10
   - `webapp/inference.py`: MODEL_PATH → `/app/models/v1-10.onnx`, IMGSZ 1280 → 640 (v1-10 exported at 640), CLASS_NAMES rewritten to 23-class order
   - Auto-deployed on push to `dev` via existing `deploy-dev.yml` (build → SSM RunCommand → docker compose restart → healthz)
6. **Live smoke test on dev:** healthz 200, container has `/app/models/v1-10.onnx` (43 MB), `len(CLASS_NAMES)==23`, real inference on 9 job-9 tiles returned 138 detections including both old (`valve_db`, `inst_field`) and new (`inst_bpcs`, `inst_sis`) classes.

**Result:**

| Metric | v1-9 | v1-10 |
|---|---|---|
| mAP50 | 0.404 | **0.834** |
| mAP50-95 | (unknown) | 0.502 |
| Precision | (unknown) | 0.826 |
| Recall | (unknown) | 0.755 |
| Classes | 20 | 23 (7 dropped, 10 added) |
| ONNX size | 43 MB | 42.6 MB |

**Notes:**

- **BREAKING:** dropped 7 v1-9 classes that lacked ≥100 LS annotations: `valve_cv`, `valve_gen`, `DCS`, `PLC`, `interlock-R`, `inst_field-R`, `valve_pnuectrl` (typo). Anything that currently relies on those class names or IDs will silently stop firing. Class IDs are completely reordered — only safe to map by name. The 20-class → 23-class transition is decoded by name via `CLASS_NAMES[d["_class_id"]]` in `inference.py`, so callers that read the string `label` field are fine.
- **`Pump_Dwg_Pump` (v1-9) → `Pump/Dwg Pump` (v1-10)** — label now has slash + space, mirroring LS exactly. YOLO tolerates it; if it ever flows through filesystem paths we'd need to normalise.
- **Under-represented classes** (`connector_in` 55 instances, `connector_out` 73, `valve_3way_relief` 114, `inst_local_panel` 113) — per-class mAP likely weaker; surface in eval and either annotate more in LS or use class weights on next retrain.
- **GPU spot quota = 0** in account 449901518037 for "All G and VT Spot Instance Requests". Worth filing a quota increase ahead of v1-11 to halve retrain cost (~$0.49/hr spot vs $1.21/hr on-demand). 24-48h approval.
- **Training script lessons logged** (commit `89be82c` on `dt/main`): (1) Ultralytics resolves `path:` in data.yaml against its own settings dir not the yaml file location — always use absolute paths; (2) `cmd 2>&1 | tail -N` masks `cmd`'s non-zero exit without `set -o pipefail`; (3) `torch.onnx.export` needs `onnxscript` (not just `onnx`) on PyTorch 2.7+ — add to bootstrap pip install.
---

## [2026-06-05] #30-DT — [DT] Experimental track scaffolded + v1-10 YOLO retrain kicked off (23 classes incl. direction arrows)

> **Numbering note (added at merge):** Both `dev` and `dt/main` independently allocated `#30` on 2026-06-05 — `dev`'s entry above documents the *shipped deployment*, this one (originally `#30` on `dt/main`) documents the *scaffold + training kickoff* that preceded it. Renumbered to `#30-DT` during the `dt/main → dev` merge on 2026-06-10 so both histories survive intact. See also FEATURES #30.

**Type:** infra, model-swap, decision
**Stage:** training | infra
**Status:** in-flight (training EC2 launched, ~3h remaining at write time)

**Why:** Team interns ramping up on the production codebase at their own pace,
while the lead races ahead with Claude Code to ship graph-extraction v0 and a
new direction-aware YOLO model. Separating the work onto `dt/*` branches +
`experiments/digital_twin/` folder keeps `dev` clean for the team and lets the
lead iterate without merge pressure. Same repo (shared data, shared memory)
but separate working surface. Handover via one PR `dt/main → dev` when v0
lands.

User had also added 6 new direction labels in LS over the past week
(arrow_up/down/left/right + connector_in/out) that need to land in the
production model so we can build a flow-direction-aware MultiDiGraph in
graph-extraction v0 (design doc:
`docs/superpowers/specs/2026-06-05-graph-extraction-design.md`).

**What:**

1. **Experimental track:**
   - New branch `dt/main` off `dev` (commit `d77164b`).
   - Folder `experiments/digital_twin/` with `pyproject.toml`,
     `notebooks/`, `backend/`, `data/` (gitignored), `docs/`, `scripts/`.
   - CLAUDE.md gets a new `## Experimental track` section.
   - `deploy-dev.yml` only fires on `branches: [dev]` so `dt/*` pushes are
     silent — zero deploy noise.

2. **LS schema hygiene (script `scripts/fix_ls_typos.py`):**
   - Renamed `valve_3way_releif` → `valve_3way_relief` (3 annotation results in
     1 annotation, project 19).
   - Renamed `valve_pnuectrl` → `valve_pneuctrl` (14 annotations in project 25
     + 28 project label_configs). Idempotent verification pass at end.

3. **v1-10 dataset (script `scripts/export_ls_dataset.py`):**
   - 23-class schema (9 valves + 8 instruments + 6 direction).
   - 605 train + 62 val images, 24,428 bbox annotations exported in YOLO
     format with global class IDs across all 33 dev-LS projects.
   - Handles both `/data/upload/` LS-served images and
     `https://dev.qongsystems.com/jobs/N/tiles/...` webapp-served images.
   - Auto-refreshes the LS JWT access token on 401.
   - Output (gitignored): `experiments/digital_twin/data/dataset_v1-10/`,
     258 MB. Also uploaded to
     `s3://qong-pid-archive-2026-06-02/training/v1-10/dataset_v1-10.tar`.

4. **Training infrastructure:**
   - Bucket policy on `qong-pid-archive-2026-06-02` extended with a
     `PutObject` grant scoped to `training/*` prefix for the existing
     `may26-ec2-ssm-role` (read-only before).
   - GPU spot quota = 0 in this account; **falling back to on-demand**
     (~$1.21/hr g5.2xlarge vs planned ~$0.49/hr g5.xlarge spot).
   - Capacity churn pushed instance from g5.xlarge → g5.2xlarge and from
     ap-south-1a → 1b. Same A10G GPU, larger CPU/RAM. Net effect: slightly
     higher cost, marginally better dataloader headroom.
   - Instance `i-0ec47e4aaa9ad364b` launched on-demand with
     `--instance-initiated-shutdown-behavior=terminate`. Bootstrap user-data
     installs ultralytics 8.3.40 + onnx; main training script
     (`scripts/ec2_train_v1-10.sh`) is fetched from S3 and run detached via
     `nohup`. Auto-terminates on completion.

5. **Training run plan (yolov8s, 100 epochs, imgsz=640, batch=32, A10G):**
   - 1-epoch yolov8n smoke first as fail-fast.
   - Patience=20, save_period=10.
   - Background log uploader pushes `training.log` + `results.csv` +
     `results.png` to S3 every 5 min.
   - ONNX export with opset=12, simplified.
   - All artefacts → `s3://qong-pid-archive-.../training/v1-10/`.
   - Hard timeout 8h on the yolo command bounds worst-case cost ≈ $10.

**Result (target):**
- v1-10 mAP50 ≥ 0.40 (matching v1-9 baseline) on the 17 existing valve/
  instrument classes, plus ≥0.30 on the 4 strong arrow classes
  (350-470 instances each).
- `connector_in` (55 instances) and `connector_out` (73) likely to be
  weaker — flagged for v1-11 with more annotation work.
- Single ONNX model (no two-pass inference) — drop-in replacement for
  v1-9 in `webapp/inference.py` after CLASS_NAMES update.

**Result (actual):** TBD. See `experiments/digital_twin/docs/v1-10-training-handoff.md`
for status-check commands and post-training promotion flow.

**Notes:**
- **`Pump/Dwg Pump`** class name has slash + space + caps. YOLO tolerates it
  in `data.yaml` as a string, but if it ever needs to flow through filesystem
  paths we'd have to normalise.
- **Class imbalance**: 6365 inst_field vs 55 connector_in (~115×). First
  training pass uses default ultralytics class weights; if minority classes
  underperform we'll switch to inverse-frequency weights in v1-11.
- **GPU spot quota** is 0 in account 449901518037 ("All G and VT Spot
  Instance Requests"). Worth filing a quota increase ahead of v1-11 to halve
  retrain cost. Takes 24-48h to approve.
- **Auto-terminate semantics**: instance was launched with
  `--instance-initiated-shutdown-behavior=terminate`, so the training
  script's final `sudo shutdown -h now` causes the EC2 to terminate (not
  stop). Belt + braces.
- The full Spec A goal had v1-10 only adding direction arrows. We expanded
  to a unified 23-class single-model retrain because LS already has 24K
  valve/instrument annotations and a single model is cleaner than two-pass.
  Lead authorised the scope expansion mid-session.

---

## [2026-06-03] #29 — D5: Custom-column-labels per customer template (admin UI)

**Type:** feature
**Stage:** webapp | webapp/frontend
**Status:** shipped (Spec A · A.4, FEATURES #26 deliverables queue)

**Why:** Customers want to rename / reorder / hide deliverable columns without us
editing the canonical JSON templates. The JSON files stay version-controlled
(canonical), and a thin DB-side override layer merges at template-load time —
same pattern as `entity_overrides` for canonical entity data (FEATURES #26).

**What:**
- New ORM `CustomerTemplateOverride` (table `customer_templates_overrides`)
  in `webapp/models.py`. UNIQUE on `(customer_template_slug, deliverable_type, column_key)`.
  `column_key` = the JSON template's `field` value (e.g. `"fields.size"`), the
  natural identity that survives label/order edits. Created automatically via
  `Base.metadata.create_all()` in `run_migrations()` — no Alembic, no
  `new_columns` entry needed.
- `webapp/deliverables/template_loader.py` extended with `merged_template_dict(slug, db, …)`
  + `TemplateLoader.load_merged(slug, db, …)`. Returns the JSON template with
  label/order overrides applied and hidden columns dropped. Generators can opt
  in by switching from `load_with_fallback` to `load_merged`; existing callers
  (`exports.py`, `entities.py`) still use the JSON-only loader for now — D5
  intentionally ships the data layer + UI; opting generators in is a follow-up.
- Three admin endpoints in `routers/api_v1_admin.py`:
  - `GET /api/v1/admin/customer-templates/{slug}` — merged template + `available_slugs`.
  - `PUT /api/v1/admin/customer-templates/{slug}` — body `{overrides: [...]}`,
    delete-then-insert per (deliverable_type, column_key) tuple. No-op rows
    (no label change, no order change, not hidden) are skipped.
  - `DELETE /api/v1/admin/customer-templates/{slug}/overrides` — clears all overrides for the slug.
- New admin page `webapp/frontend/src/admin/AdminCustomColumns.tsx` at
  `/admin/custom-columns`. Slug picker, four sections (valve_list,
  instrument_index, equipment_list, datasheet), per-row up/down buttons +
  editable label + visible checkbox + per-row Reset link. Top-right "Save" /
  "Reset all" buttons. Uses `formatDateTime(last_updated_at, tz)` for the
  audit display.
- `admin/api.ts` + `admin/types.ts` extended with `getCustomerTemplate`,
  `putCustomerTemplate`, `resetCustomerTemplate` + matching interfaces.
- `App.tsx` route + `AdminLayout.tsx` nav entry (Columns3 lucide icon).

**Result:**
- `python3 -c 'import ast; ast.parse(...)' ` clean on backend files.
- `pytest tests/unit/deliverables/` — 69/69 pass (no regressions, including
  the 5 existing template-loader tests).
- `npx tsc --noEmit` clean.
- `npx vitest run` — 21/21 pre-existing tests pass.

**Notes:**
- `column_key` deliberately uses the JSON `field` value (dot-notation), not a
  zero-based index. Reordering on disk later won't break overrides as long as
  the `field` identity is stable. If a `field` is renamed in JSON, its
  overrides become orphaned (silently ignored on merge) — acceptable for now;
  if it becomes painful add a per-slug "orphaned overrides" report.
- Generators still consume the JSON-only template. To opt one in: replace
  `_loader.load_with_fallback(slug)` with `_loader.load_merged(slug, db)`.
  Skipped in this commit to keep the blast radius tight; follow-up ticket once
  the UI sees real use.
- The `is_overridden` bookkeeping field added to merged column dicts is
  silently dropped by `TemplateConfig.model_validate` (pydantic v2 default
  `extra="ignore"`) so it only surfaces through the dict-based API path —
  exactly what the UI needs, no generator surprise.

---

## [2026-06-03] #28 — YOLO v1-9 ONNX in webapp for canvas bbox overlay + corrections-rollback API

**Type:** feature | architecture
**Stage:** webapp | infra | training
**Status:** shipped (feature branch — pending merge to `dev`)

**Why:** Three pressures converged:

1. **Decouple from the Windows GPU worker.** Until now, the canvas overlay on the studio page only got bboxes when the Windows/CUDA worker (`worker.run_inference_job` over Tailscale-Redis) called back to `/api/v1/jobs/{id}/gpu-result`. That box is single-tenant, on a residential ISP, frequently powered down, and not part of the official AWS inventory. Customers visiting the studio on a fresh job often saw an empty canvas. Baking the model into the webapp image makes overlays the default.
2. **Unblock on-prem deploys.** A handful of prospects want air-gapped installs ("our docs never leave our network"). With the model in the image, a single `docker compose up` reproduces the full UX — no Tailscale, no GPU box, no extra moving parts. CPU inference is slower (~1-2 s/tile on a t3.medium) but still well inside the perceived "instant" window for the on-load canvas paint.
3. **Lay active-learning groundwork.** Spec C (corrections-driven retraining) needs a place to land "this bbox is wrong / this one is missing" events. Without a persistence layer, every studio session throws those signals away. The new `model_corrections` table is that drain — write-only audit log, indexed by `job_id`, ready for an export script to convert into YOLO `labels/*.txt` for the next training cycle. Competitor note: Model Broker / similar P&ID extractors require vector PDFs; we accept raster scans and can correct on them.

The "Two-Mode Architecture — Do NOT Mix" rule in `CLAUDE.md` had to be amended: YOLO inside the webapp is now permitted, but **only** for bbox surfacing. The CSV / deliverable pipeline is still OpenRouter Vision API via `extractor.py` (93% recall, customer-facing quality bar). `pipeline.py` must not import `detector.py`.

**What:**

- **`Dockerfile`** — new RUN step downloads `v1-9.onnx` (43 MB) from the public GitHub release `model-v1-9`, verifies sha256 `11e29b47…f526178`, lands it at `/app/models/v1-9.onnx`. Tries an anonymous `curl -L` first (the release is public on prerelease); falls back to a `--mount=type=secret,id=github_pat` PAT path if the asset returns non-200. Both paths documented inline.
- **`webapp/inference.py`** — new module exposing `run_yolo_inference(tile_paths) -> list[dict]`. Lazy-loads an `onnxruntime.InferenceSession` once at module scope behind a double-checked-locking pattern (`_session` + `threading.Lock`), CPU provider only. Output dict shape matches the existing GPU-worker callback (`bbox`, `label`, `confidence`, `tile_*`), so the `Job.gpu_detections` consumer in `routers/api_v1.py::api_job_detections` is unchanged. `label` is the raw YOLO class name (`valve_bf`, `inst_bubble`, …) — NOT the OCR'd tag. The entity_id-matching code in api_v1.py (added at `e9dbc1e`) returns `entity_id=null` for raw-class detections, which is the intended state for D1.5+.
- **`webapp/pipeline_runner.py`** — new `_run_inplace_inference(job_id, job_dir)` runs after `write_canonical_for_job()`, JSON-dumps detections onto `Job.gpu_detections`. Wrapped in try/except (non-fatal), and skipped if the column already has a real (length > 0) list — the GPU worker callback wins if it raced. Logged via stderr; never crashes the job.
- **`webapp/routers/api_v1.py::api_job_corrections`** — new `POST /api/v1/jobs/{id}/corrections`. Body `{ corrections: [{detection_index, action, new_label?, new_bbox?, note?}] }`. Atomic insert (single commit) into `model_corrections`. Validates action ∈ {delete, reclassify, add}, requires `new_label` on reclassify, `new_bbox` on add. Per-job auth: owner or super_admin.
- **`webapp/models.ModelCorrection`** — id, job_id FK, user_id FK, detection_index int (-1 for "add"), action str, new_label nullable, new_bbox JSON nullable, note Text nullable, created_at `DateTime(timezone=True)` defaulting via `_utcnow`. Picked up by `Base.metadata.create_all()` in `run_migrations()` — no manual ALTER needed since the table is new.
- **`requirements.txt`** — added `onnxruntime>=1.17.0`. Pillow was already a dep; numpy via pandas; nothing else new.
- **`CLAUDE.md`** — amended the "CRITICAL: Two-Mode Architecture" section with the explicit exception clause pointing at `webapp/inference.py`.

**Result (TBD — measure after deploy):**

- v1-9 mAP50 = 0.404 on the diverse val split per the release notes — that's the upper bound for what the canvas will surface. Real-job recall typically tracks higher because the val split is intentionally hard.
- Expected CPU inference cost: ~1-2 s/tile on a t3.medium (4-tile job ≈ 5 s overhead added to pipeline tail). Smoke-test on the dev EC2 after merge.
- Numbers pending: recall on the standard MUK sample job after the dev image rebuilds.

**Notes:**

- The `_run_inplace_inference` step is **best-effort**. If the model file is missing (e.g. the Dockerfile download silently degraded), `InferenceError` is caught and the job still finishes "done" — canvas just stays empty, same as today's Windows-worker-unreachable state.
- The PAT fallback in the Dockerfile is a no-op when no secret is mounted; both `docker build .` and `docker build --secret …` work.
- Corrections-to-training-data export is **out of scope** here. Follow-up: `webapp/scripts/export_corrections_for_training.py` that reads `model_corrections`, joins on tile geometry, and writes YOLO `labels/*.txt` for the next training run.
- Future v1-10 should be trainable from accumulated corrections once the export script lands. No timeline pinned — gates on first ~500 corrections accumulating, which at current job volume is ~6-8 weeks.
- The detections endpoint's entity_id matching (matching `label` to canonical entity `tag`) returns null for raw-class labels like `"valve_bf"` because canonical tags look like `"01-BF-151031"`. That's expected for D1.5+; clicking on a raw-YOLO bbox shows the overlay but doesn't open a datasheet drawer. A "class+bbox → tag" reverse-lookup pass is its own ticket (needs a spatial index over canonical entities, doesn't exist yet).
- `webapp/inference.py` gates the `import onnxruntime` behind a try/except ImportError so unit tests that don't exercise the inference path don't require the native library locally. Failures surface inside `_get_session()` instead, where they belong.

---

## [2026-06-03] #27 — Timezone handling: UTC-on-the-wire + per-user display preference + frontend datetime util

**Type:** feature | bugfix | architecture
**Stage:** webapp | webapp/frontend | infra
**Status:** shipped (all three phases) — feature branch `feature/timezone-handling`, PR open against `dev`

**Why:** A user-facing question ("what TZ are the servers running in, and can users pick their own?") surfaced a real latent bug stack:

1. The `web` and `cpu-worker` containers had `TZ=Asia/Kolkata` in `docker-compose.yml`, which only changes `datetime.now()` / `time.localtime()` output, not `datetime.utcnow()`. Most code uses `utcnow()` (correct UTC writes), but the env was misleading and meant any future bare `datetime.now()` would silently emit IST into the same column as UTC values. Latent mixed-timezone data.
2. The API serialized datetimes with `dt.isoformat() if dt else None`, producing strings without the `Z` suffix (e.g. `"2026-06-03T06:53:16"`). JavaScript's `new Date(iso)` parses those as **local clock**, not UTC, under-shifting every displayed timestamp by the browser's offset (5:30h on IST). This was wrong everywhere on dev.qongsystems.com.
3. There was no `User.timezone` column or UI to let users pick a display TZ. Frontend defaulted to whatever `toLocaleString()` picked up from the browser, with no way to override.

Without fixing all three, "show times in the user's TZ" wouldn't have done what users expect.

**What:** Three phases, one commit per phase on `feature/timezone-handling`:

- **Phase 1 — Backend correctness** (commit `29643a2`):
  - Removed `TZ=Asia/Kolkata` from `web` + `cpu-worker` (containers now UTC, matching the EC2 host).
  - New `webapp/datetime_utils.py` with `utc_iso(dt)` (Z-suffixed) and aware `utcnow()`. All 12 `dt.isoformat() if dt else None` callsites in `routers/api_v1.py` + `api_v1_admin.py` replaced. `pipeline_runner.py` stage timings switched too.
  - `models.py`: every `DateTime` column → `DateTime(timezone=True)` (14 columns across 9 tables). Defaults switched to a module-level `_utcnow()` returning aware UTC.
  - `database.py:run_migrations()` extended with a Postgres-only ALTER pass that converts each legacy `timestamp without time zone` column to `timestamptz USING (... AT TIME ZONE 'UTC')`. SQLite is a no-op. Failures are logged (not silently swallowed) so half-migrated state is visible.

- **Phase 2 — User TZ preference** (commit `05b04e4`):
  - `User.timezone = Column(String, nullable=True)` + a new entry in the `run_migrations` `new_columns` list.
  - `GET /api/v1/account` now returns `timezone`. New `PATCH /api/v1/account/timezone` validates the IANA name via stdlib `zoneinfo.ZoneInfo` and returns 422 on unknown values.
  - `AuthContext.tsx`: `CurrentUser.timezone`, new `detectBrowserTimezone()` utility wrapping `Intl.DateTimeFormat`. On `refresh()`, if the server returns null timezone, silently PATCH the browser-detected zone (best-effort; errors swallowed so login never breaks).
  - `routes/Account.tsx`: TZ selector in Profile section with 11 curated IANA options and an "Auto-detect (browser: X)" sentinel that clears the field. Saves on change, refreshes AuthContext so the rest of the SPA picks up the change immediately.

- **Phase 3 — Frontend rendering layer** (commit `b5e1fec`):
  - `npm install date-fns@^4.4.0` (only `formatDistanceToNow` imported; ~6 KB gzipped).
  - New `webapp/frontend/src/util/datetime.ts` exporting `useUserTimezone()`, `formatDateTime(iso, tz?)`, `formatDate(iso, tz?)`, `formatRelative(iso)`. Native `Intl.DateTimeFormat` for absolute formatting (no `date-fns-tz` needed); date-fns only for relative-distance strings.
  - 9 callsites replaced: `routes/Account.tsx`, `routes/AccountApiKeys.tsx`, `routes/Dashboard.tsx`, `dashboard/types.ts`, `admin/AdminDashboard.tsx`, `admin/AdminCredits.tsx`, `admin/AdminFeedback.tsx`, `admin/AdminLabelStudio.tsx`, `admin/AdminUsers.tsx`. Each component now does `const tz = useUserTimezone()` once at top, passes through.
  - Added `useAuthOptional()` (non-throwing variant) so `useUserTimezone()` is resilient to being called outside `<AuthProvider>` in isolated component tests. Saved wrapping every existing admin test in an AuthProvider.

**Result (verified):**
- `npx tsc --noEmit`: clean across the SPA.
- `npx vitest run`: 21/21 tests pass (no test changes needed).
- `webapp/datetime_utils.py` smoke test: naive UTC, aware UTC, aware IST, None — all serialize to expected Z-suffixed UTC string.
- Bundle delta from date-fns: ~6 KB gzipped (tree-shaken to `formatDistanceToNow` only).

**Notes:**
- The timestamptz migration rewrites the column on disk. Safe at our current scale (jobs ~50 rows, users <20) but if any table hits 10M+ rows in the future, the same migration would need to be batched / use `pg_repack`. Not an issue today.
- For users whose `User.timezone` is set but the IANA value later disappears from the system tzdb (e.g. obsolete zone removed), `Intl.DateTimeFormat` throws — we catch and fall back to `toLocaleString()`. Logged as a known soft-failure in `formatDateTime`.
- Auto-detect on first login silently fires `PATCH /api/v1/account/timezone`. If you observe a `timezone` field appearing in DB writes for new users right after login, that's expected.
- The dashboard's `relativeTime()` keeps its hand-rolled short strings ("3 hr ago", "Yesterday") for ≤30 days; only the >30-day "old date" fallback was migrated to the util. Replacing with `formatRelative()` everywhere would give consistent date-fns wording but would change tile copy ("about 3 hours ago" vs "3 hr ago"). Out of scope for this entry; reconsider when bulk-review screen renders timestamps.
- Open follow-ups (not blocking):
  1. Wire `entity_overrides.edited_at` display in DatasheetDrawer once Spec A D2 lands.
  2. The QA-stopped EC2 will need the migration on next start (will run automatically on app startup via `run_migrations()`).
  3. Consider exposing a richer TZ picker (full IANA list) once users complain about the 11-option curated list.

---

## [2026-06-02] #26 — Editable deliverables: entity_overrides backend layer (Day 1 of Spec A)

**Type:** feature | architecture
**Stage:** webapp | deliverables | export
**Status:** shipped (backend); frontend wiring in follow-ups

### What changed

The deliverables subsystem now supports **user edits** without disturbing the
pipeline-produced `canonical.json`. Edits live in a new `entity_overrides` DB
table; a thin merge layer applies them on top of canonical before any
generator runs.

New components:
- **`models.EntityOverride`** — DB table `(job_id, entity_id, field_name,
  new_value, prior_value, edited_by, edited_at)` with
  `UNIQUE(job_id, entity_id, field_name)` for current-value semantics. Full
  audit history is a future migration: drop UNIQUE, add `superseded_at`.
- **`webapp/deliverables/overrides.py`** — `load_canonical_with_overrides()`
  reads canonical.json, queries the override table, walks dot notation
  (`tag`, `fields.size`, `vendor_match.vendor_name`) on each affected
  entity, re-validates through `CanonicalEntity`. Read-only fields
  (`entity_id`, `entity_class`, `pid_number`, `sheet_number`, `bbox`) are
  silently skipped at this layer; API rejects them upstream.
- **`webapp/routers/entities.py`**:
    - `GET /api/v1/jobs/{job_id}/entities?deliverable_type={t}` — returns
      schema (from customer template) + entities filtered by entity_class
      (valve_list→valve, instrument_index/datasheet→instrument,
      equipment_list→equipment), each with per-field `{value, source,
      is_override}`. `source` distinguishes "pid" (canonical had a value)
      from "manual" (user-supplied field). `is_override` true iff an
      override row exists for that field path.
    - `PATCH /api/v1/jobs/{job_id}/entities/{entity_id}` — `{fields:
      {path: value}}`. Atomic: validates all paths editable before any
      writes. Captures `prior_value` from on-disk canonical (not from a
      prior override row) so audit always references pipeline output. Skips
      writes when value unchanged.
- **`webapp/routers/exports.py`** — swapped `load_canonical_for_job` →
  `load_canonical_with_overrides` so generated CSV/XLSX include user edits.
  Single change-point; generators themselves are unmodified.

### Why this design

The architecture already supported edits cleanly because of one prior choice:
generators don't care where data comes from — they consume `JobCanonical`
and emit bytes. So "make 4 deliverables editable" turned out to be one merge
layer above generators + one router file, NOT a per-generator change. If the
6 future generators (Control Narrative, C&E, I/O List, Line List, Loop
Schedule, Tag Register) follow the same `Generator.generate(canonical,
template)` contract, they get edit-ability for free.

**Why DB, not filesystem.** User picked "DB table" over "canonical_overrides.json
per job" because: audit columns come for free; concurrent edits on the same
job are atomic without filesystem race; `canonical.json` stays the only
file the pipeline writes.

**Why `prior_value` snapshots from canonical, not from prior override.** Audit
always references the pipeline's source-of-truth. If a user PATCHes X to A
then B then C, the final audit row has `prior_value` from the original
canonical, not from B. A reader sees "pipeline said X=Z; now X=C" — useful.

### Smoke test (proven on job 41 / dev)

| Test | Result |
|---|---|
| `GET /entities` returns schema + entities with per-field metadata | ✅ |
| `PATCH` two fields → `applied=2` | ✅ |
| `GET` again — `is_override:True` on edited fields | ✅ |
| `POST /export/valve_list/csv` — CSV contains edited values | ✅ |
| `PATCH bbox` (read-only) → 400 | ✅ |
| `PATCH` unknown entity → 404 | ✅ |
| DB row — `prior_value` captures pipeline value | ✅ |

The override flowing into the exported CSV was the satisfying test — it
validates the whole architectural premise (edit lives in DB, merged into
canonical, flows through generator, lands in customer artifact) in one
round-trip.

### Out of scope (deferred)

- **Canvas-click → entity_id linkage** (Spec A Day 1.5). GPU detections
  don't carry `entity_id` today — they come from a separate code path than
  canonical (Windows GPU worker → JSON detections vs. CSVs →
  pipeline_emitter → canonical.json). User picked Option B: write a
  `(page, bbox, tag) → entity_id` mapping during canonical emission and
  surface it on the detections endpoint. ~half a day.
- **DatasheetDrawer + BulkReviewScreen real-data wiring** — Days 2-4.
  Blocked on D1.5.
- **Admin custom-column-labels CRUD UI** — Day 5.

### Files

- `webapp/models.py` (+44 lines — EntityOverride)
- `webapp/deliverables/overrides.py` (new, 160 lines)
- `webapp/routers/entities.py` (new, 280 lines)
- `webapp/routers/exports.py` (3 lines)
- `webapp/main.py` (2 lines — router registration)

### Commit

- `54e0905` feat(deliverables): entity-override layer + editable-deliverables API (Day 1)

---

## [2026-06-02] #25 — CI/CD migrated to GitHub Actions + AWS SSM; branches synced (feature/digital-twin → dev → main)

**Type:** infra | architecture
**Stage:** ci-cd | deployment
**Status:** shipped (pending: GH Secrets paste + first auto-deploy validation)

### What changed

Three coupled changes, shipped together:

1. **CI/CD architecture pivoted from SSH-to-GCP to SSM-to-EC2.**
   - `.github/workflows/deploy-dev.yml` rewritten. Old: `ssh maahedev@34.126.93.103 <<ENDSSH ... ENDSSH` (the GCP VM, stopped 2026-06-02 per #21 — meaning every dev push since cutover triggered a workflow that hung on SSH and silently failed). New: `aws-actions/configure-aws-credentials@v4` → `aws ssm send-command` → poll `get-command-invocation` → curl `/healthz`. Targets `i-0e7b89bd91b67a291`.
   - `.github/workflows/deploy-qa.yml` created. **Manual** (`workflow_dispatch` only, no `push:` trigger) so QA stays stakeholder-paced. Accepts `ref` input (default `dev`) so hotfix branches can ship to QA without polluting `dev`. Ref is regex-validated `^[A-Za-z0-9._/-]+$` before flowing into the SSM JSON payload (defense-in-depth — `workflow_dispatch` already requires repo write, but a compromised account could otherwise shell-inject through the input).
   - IAM user `github-actions-deploy` created with inline `DeployViaSSM` policy scoped to `ssm:SendCommand` on **exactly two** EC2 ARNs (dev + qa) + the `AWS-RunShellScript` document; `ssm:GetCommandInvocation` + `ssm:ListCommandInvocations` (read-only). Blast radius if leaked: shell on those 2 boxes only. No IAM, no other AWS services. Access keys generated; user pastes into GitHub repo Secrets.

2. **`feature/digital-twin` → `dev` fast-forward merge.** 94 commits. `feature/digital-twin` had been the active dev branch since 2026-05-26 (#01) but never merged back; `dev` had drifted to "what's deployed to the dead GCP VM". FF-merge collapses the gap with no merge commit (dev was a strict ancestor). New `dev` tip: `028ee6a`.

3. **`dev` → `main` fast-forward merge.** 100 commits. `main` was at `7f406db` from before the entire AWS migration, before the SaaS webapp, before the digital-twin work. Per CLAUDE.md `main` is reserved for future `app.qongsystems.com` prod — but the branch itself was so stale that prod cutover would have meant a 100-commit catch-up on top of infra work. FF'd to `028ee6a` (no deploy workflow on main — intentional, per CLAUDE.md "do not push until prod infra ready"). Now main is current; when prod is provisioned, cutover is one infra step, not infra + a giant catch-up merge.

### Why this matters

The dev deploy workflow had been **silently broken for 6 days** post-AWS-cutover. Every commit since 2026-05-27 was hand-deployed via SSM. The team had unknowingly traded "automated CI/CD" for "manual SSM commands hidden in conversation transcripts" — no audit trail in GitHub, no health check after deploy, no notifications on failure, easy to forget a step. This entry restores the CI/CD invariant: push to `dev` → deploy happens → health-checked → reported in GitHub.

Also: the deploy workflow had been pointing at a dead host for 6 days and nobody noticed because no one looked at GitHub Actions during the AWS migration. The new workflows include a `/healthz` curl step that fails loudly if the deploy didn't actually take effect — so future "looks deployed but didn't" bugs surface immediately.

### Why GH Actions + SSM over CodeDeploy / Jenkins / OIDC-on-day-one

User explicitly evaluated:
- **CodeDeploy + CodePipeline** — better fit at ≥3 envs or for blue/green, but ~3-4 hr setup (agent on each EC2, deployment groups, lifecycle hooks, S3 revision bucket). For 2 EC2s it's strictly more plumbing for marginal gain.
- **Jenkins** — right at 20+ services across multiple teams; wrong at this scale. Would cost more in maintenance ops than the deploys save.
- **ArgoCD/Flux** — only relevant if we move to EKS.
- **GH Actions + OIDC from day one** — better security posture (no long-lived keys), but adds ~45 min to set up the GitHub OIDC provider in IAM + role trust policy. User picked "long-lived keys now, OIDC later" to ship faster. OIDC migration tracked as a follow-up.

Rule of thumb encoded: **the right CI/CD tool scales with team size and deploy frequency, not project ambition.** Move to CodeDeploy when env count outgrows GH Actions; don't move to Jenkins ever (operational burden too high for our scale).

### Files changed

- `.github/workflows/deploy-dev.yml` (rewritten)
- `.github/workflows/deploy-qa.yml` (new)
- IAM resources (AWS, account `449901518037`):
  - User `github-actions-deploy` (programmatic only, tagged `Purpose=ci-cd`)
  - Inline policy `DeployViaSSM`
  - Access key (surfaced to user once; he pastes into GH Secrets)

### Commit

- `028ee6a` ci(deploy): SSM-based deploy workflows for dev + qa

### Branch state after this entry

| Branch | Tip | Deployed to |
|---|---|---|
| `feature/digital-twin` | `0769c2d` (1 behind dev, no longer load-bearing) | nothing |
| `dev` | `028ee6a` | dev.qongsystems.com (manual SSM this round; auto-deploy after secrets are pasted) |
| `main` | `028ee6a` | nothing (no deploy wired — intentional) |

QA EC2 (`i-04be6af1fb7929a0c`) switched from `feature/digital-twin` to tracking `dev`. Future QA deploys are manual via `workflow_dispatch` in the Actions UI.

### Follow-ups

1. **User**: paste `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` into Qong-Systems/qong_product → Settings → Secrets → Actions.
2. **Verify**: re-run the deploy-dev workflow (workflow_dispatch) to confirm credentials work. The push of `028ee6a` will have already triggered the workflow once and failed (no secrets yet) — that red ✗ in Actions history is expected, ignore it.
3. **Migrate to OIDC** (queued separately): replace long-lived access keys with GitHub OIDC trust → IAM role. ~1 hr.
4. **deploy-prod.yml** when `app.qongsystems.com` infra is up — same SSM mechanism, gated by GitHub Environments with required-reviewer approval. Manual approval gate before any prod deploy fires.

---

## [2026-06-02] #23 — Label Studio exposed on ls-dev.qongsystems.com; all GCP LS data preserved

**Type:** feature | infra
**Stage:** infra | webapp
**Status:** shipped

**Why:** After the AWS cutover (FEATURES #21), Label Studio was running on dev (docker container `qong-label-studio-1` healthy, bound to `127.0.0.1:8080`) but not externally reachable — the dev nginx config copied from QA only proxies `/healthz` + `/` to the FastAPI webapp, with no `/ls/` location. User asked: "we should have label studio hosted on dev, is it removed?". Answer: no, just unrouted. This entry sets up a clean subdomain `ls-dev.qongsystems.com` rather than path-mounting at `/ls/` on the main hostname (which would conflict with FastAPI's own `/api/*` routes — the local-dev docker nginx config handles this with multiple proxy_pass blocks but it's brittle).

**What:**

1. **New nginx vhost `qong-dev-ls`** at `/etc/nginx/sites-available/qong-dev-ls` on EC2 `i-0e7b89bd91b67a291`. Mirrors the main `qong-dev` site's posture (CF Origin Cert + CF IP allowlist + 600s read timeout for long-running label-stream uploads) but proxies `/` to `http://127.0.0.1:8080` (the LS container). Symlink in `/etc/nginx/sites-enabled/`. `client_max_body_size 500M` for LS's image/video uploads.

2. **Cloudflare DNS:** User added an `A` record `ls-dev.qongsystems.com → 13.204.52.248` (proxied / orange-cloud). CF Origin Cert (`*.qongsystems.com` SAN) covers the subdomain — no new cert work needed.

3. **`docker-compose.override.dev.yml` now committed to the repo** (was previously only generated on the EC2 during bootstrap). Adds the `label-studio.environment.LABEL_STUDIO_HOST` override to `https://ls-dev.qongsystems.com`. The base compose ships `LABEL_STUDIO_HOST=https://dev.qongsystems.com/ls` (a path-based local-dev artifact); on AWS dev that value causes LS to generate `/ls/user/login` redirects that 404 because the dev nginx doesn't proxy `/ls/`.

4. **Label Studio data fully preserved from GCP.** The PostgreSQL dump restored in Phase 2 (FEATURES #21) included the `label_studio` database — all 6 users (`tnb@qongsystems.com`, `admin@qong.com`, plus 4 team members), 28 projects, 819 tasks, 826 annotations were present on dev as soon as LS started. LS uses Django's PBKDF2-hashed passwords stored in `htx_user.password`; passwords carried over verbatim so the team logs in with their original GCP credentials.

**Result (if measurable):**
- `https://ls-dev.qongsystems.com/` returns `302 Location: /user/login/` then `200` on the login page (LS's normal anonymous flow). Playwright snapshot shows the LS branding, "Log in" form, and "Brought to you by Human Signal" footer. No 404, no path-prefix weirdness.
- `https://ls-dev.qongsystems.com/health/` returns `200`.
- `label_studio` DB row counts on dev: **6 users, 28 projects, 819 tasks, 826 annotations** — identical to the source GCP DB.
- LS container env after the recreate: `LABEL_STUDIO_HOST=https://ls-dev.qongsystems.com` (no `/ls/`).
- Both the main `dev.qongsystems.com` and the new `ls-dev.qongsystems.com` are CF-IP-allowlisted at nginx — direct IP access still gets 403, and bare-IP redirects (FEATURES #22) still apply.

**Notes:**
- *QA does NOT get this treatment.* User explicitly said "we dont this on QA. only for Dev instance." If QA needs LS exposed later, mirror this exact pattern with `ls-qa.qongsystems.com` (cert + nginx vhost + override.qa.yml env + CF DNS).
- *LS expects to own its entire hostname.* No path rewrites needed because the subdomain owns the whole URL space. If anyone ever tries path-based hosting (`/ls/` on the main domain), expect to ALSO proxy `/api/`, `/static/`, `/websocket/`, `/react-app/` to LS — which collides with the FastAPI app's `/api/v1/*`. Avoid.
- *No fresh admin account was created on dev's LS.* The existing GCP-era admin (`tnb@qongsystems.com` with `is_staff=true`, or `admin@qong.com` with `is_staff=true`) logs in normally. If the original LS password is forgotten, reset via Django shell in the container: `docker compose exec label-studio python3 -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.label_studio'); django.setup(); from users.models import User; u=User.objects.get(email='tnb@qongsystems.com'); u.set_password('newpass'); u.save()"`.
- *Bootstrap script gap:* `docker-compose.override.dev.yml` is now in the repo, but `bootstrap_1.sh` (which the EC2 ran during provisioning) wrote the file inline via `tee` instead of `cp` from the repo. If we ever re-provision, prefer reading from the repo so the LS override and any future changes flow into the new EC2 automatically. Tracked as a follow-up improvement.
- *LS's `LS_EXTERNAL_URL=https://ls-dev.qongsystems.com`* was also added to `.env.dev` for the webapp (the webapp uses this env var to build links to LS in the annotator UI). Different env var, different consumer than `LABEL_STUDIO_HOST`.

---

## [2026-06-02] #22 — SPA marketing pages removed; IP-direct access redirects; GCP VMs stopped

**Type:** feature | infra | decision
**Stage:** webapp | infra
**Status:** shipped

**Why:** Three threads converged in the tail end of the AWS-migration session. (1) User wanted `dev.qongsystems.com` to be engineering-app-only — "we don't need any UI like home, about, contact pages on this instance … we will have first page as login page and then our studio will start. website is already hosted on diff server". (2) User noticed origins are reachable by bare-IP and asked to "check and redirect but don't allow IP opening directly in browser". (3) With the AWS cutover live (FEATURES #21), the GCP VMs were burning ~$60/mo for nothing — user asked to stop them. None of these are dramatic in isolation but each tightened the production posture and saved real money.

**What:**

1. **Marketing pages deleted from the SPA** (commit `9fb2692`):
   - DELETE `webapp/frontend/src/marketing/` (7 files: `Drive.tsx`, `Footer.tsx`, `Hero.tsx`, `MarketingNav.tsx`, `Sections.tsx`, `Social.tsx`, `marketing.css`)
   - DELETE `webapp/frontend/src/routes/Home.tsx` (was the marketing landing — Hero + Sections + Footer composition)
   - NEW `webapp/frontend/src/routes/RootRedirect.tsx`: calls `useAuth()`, waits for the loading flag to settle, then `<Navigate replace>` to `/dashboard` if there's a session or `/signin` if anon
   - `App.tsx`: `<Route index>` swapped from `<Home />` → `<RootRedirect />`
   - `Layout.tsx`: dropped `/` from `FULL_BLEED_EXACT` since the root now renders nothing (the redirect fires immediately after auth resolves)
   - `Login.tsx`: "Request access" CTA changed from `<Link to="/">` (which would now bounce visitors back to /signin in a feels-like-loop) to `<a href="https://qongsystems.com" target="_blank">` — points at the external marketing site
   - `RequireAuth.tsx` docstring no longer references "marketing /"
   - Unused `Link` import dropped from `Login.tsx`

2. **IP-direct access redirects to the canonical hostname** (nginx-only, no code in repo):
   - Both dev and QA `nginx` `default_server` blocks rewritten on the EC2 hosts (idempotent overwrite, after a first-attempt regex-strip left duplicate `default_server` lines and broke `nginx -t`).
   - New behaviour: any request hitting the bare EIP (or with a wrong/empty Host header) returns `301 Location: https://{dev|qa}.qongsystems.com$request_uri`. Replaces the prior `return 444` silent connection drop.
   - Cert presented for HTTPS-via-IP is `*.qongsystems.com` (the CF Origin Cert from `/etc/ssl/qong-{env}/origin.crt`); browsers show a name-mismatch warning before the redirect, which is acceptable friction since CF-fronted access is the supported path.
   - Verified externally from a non-CF IP (my mac): `http://13.204.52.248/` → 301, `https://13.204.52.248/` → 301, both pointing at `https://dev.qongsystems.com/`. QA HTTP-via-IP is also closed at the SG level (port 80 not open on QA's `sg-0ece96660d8ee00bc`), so it times out instead of redirecting — defense in depth.

3. **GCP VMs stopped** (no code; gcloud state change):
   - `gcloud compute instances stop qong-dev-server qong-intake-server --zone=asia-southeast1-c`
   - Both VMs in TERMINATED state. Disks persist (~$2.40/mo for the 50 GB dev disk + ~$1/mo for the 20 GB intake disk). Daily snapshots continue. GCS buckets `qong-backups` + `qong-intake-data` untouched.
   - GCP ephemeral external IPs released on stop — if VMs restart, new IPs will be assigned. The Cloudflare A-record currently points at the AWS EIP `13.204.52.248`, so the GCP IPs being different on restart is irrelevant for rollback (we'd just update CF to whatever the new IP is).

4. **Dev super_admin password reset** (post-`pg_dumpall`-restore housekeeping):
   - The dev Postgres was restored from the GCP dump on 2026-06-02 (FEATURES #21 Phase 2). The `users` table preserved the GCP-era bcrypt hashes for all 8 users including `admin`, but the GCP `admin` password was unknown to me (it had been set on the old dev VM before this session began).
   - Reset via `docker compose exec web python3` calling `webapp.auth.hash_password(...)`. Saved as `reference_dev_admin_password.md` in user auto-memory.

**Result (if measurable):**
- Live SPA bundle on both dev and QA: `index-COLjBvIo.js`, **0 occurrences of "About" / marketing strings** (verified via `curl + grep`). Previous QA bundle `index-ChMrWMB0.js` had 4× "About".
- Playwright on `https://dev.qongsystems.com/`: anonymous visit redirects to `/signin` (full-bleed, no app header), `hasMarketingNav: false`, "Request access" link points at `https://qongsystems.com`, `window.__QONG_BUILD__ === "9fb2692"`.
- Origin redirect verified from my mac (non-CF IP):
  - `http://13.204.52.248/` → `301 https://dev.qongsystems.com/`
  - `https://13.204.52.248/` (k) → `301 https://dev.qongsystems.com/`
  - `https://43.205.96.86/` (k) → `301 https://qa.qongsystems.com/`
  - `http://43.205.96.86/` → timeout (SG closed on 80 for QA)
- Cost delta: **−$60/mo** (GCP compute → $0, disks/snapshots stay at ~$2.50/mo). Net total monthly run-rate: ~$74/mo (was ~$102/mo at session start, +$36/mo for the new AWS dev EC2 since session start, −$63/mo from stopping GCP).
- Dev admin auth verified end-to-end through Cloudflare: `POST /login` → 303 → `/dashboard`, then `GET /api/v1/account` returns `{id: 1, username: "admin", role: "super_admin", credits_remaining: 999, tier: "enterprise"}` (data exactly as it was on GCP).

**Notes:**
- *Login page's left brand panel is still there.* `Login.tsx` renders a two-pane screen — sign-in form on the right, brand panel on the left with the "Read your P&ID. Generate the rest." headline + a `Live Extraction · Demo` tile (FT-201 / PT-101 / etc.) + version chip. The user hasn't asked for that to go (yet); if they do, the left `<aside class="login-brand">` block is the surgical removal target. Tracked as a future option in SESSION_STATE.
- *nginx configs live on the EC2 hosts, NOT in this repo.* If we ever rebuild from scratch we'll need to recreate them from the `docs/superpowers/specs/2026-05-29-aws-qa-environment-design.md` notes or extract from the running hosts via SSM. Worth a future refactor: ship the canonical configs at `deploy/nginx/qong-{env}.conf` and have the EC2 user-data script `cp` them at boot.
- *The first nginx-rewrite attempt left duplicate `default_server` lines.* The Python script used a regex that matched `# Block bare-IP` comment headers; dev's nginx config had the bare blocks WITHOUT the comment, so the strip-and-replace became append-only. nginx -t failed, `systemctl reload` was rejected, and the old `return 444` config kept serving traffic — masking the fact that nothing had changed until the external curl test surfaced it. **Lesson:** for nginx config edits, prefer idempotent full-file rewrites over regex-stitching.
- *GCP rollback path is still open* and explicitly tested in this session's exit notes. To roll back: `gcloud compute instances start qong-dev-server qong-intake-server` (new ephemeral IPs), then update the Cloudflare A-record for `dev.qongsystems.com` from `13.204.52.248` to the new GCP IP. The AWS dev box can be left running as a warm secondary or stopped to save costs while GCP is primary.
- *Memory file added for dev admin* — `reference_dev_admin_password.md` joins the local + QA admin reference files. The MEMORY.md index lists all three.
- *Phase 4 (GCP decommission) deliberately deferred.* The 7-day soak window is conservative; we could shorten if we trust the rollback path won't be needed. The GCP daily snapshots will keep accumulating until Phase 4 deletes them.

---

## [2026-06-02] #21 — AWS migration Phases 1-3: dev moved from GCP to AWS; DNS cut over

**Type:** infra
**Stage:** infra
**Status:** shipped

**Why:** Continuation of FEATURES #20 (Phase 0 backup). User authorised "if we got the dev backup, go and finish all phases and validate on aws. give me new IP, i will change on cloudflare and we will mark this migration as complete". Since dev has no real customers and the QA pattern was already proven over the prior 2 days, this was an autonomous straight-line build + cutover.

**What:** dev.qongsystems.com now runs on AWS, mirroring the QA pattern in ap-south-1.

**Phase 1 — Provision AWS dev:**
- Security Group `sg-0ad6bfa98b1e06969` (`qong-dev-web`): tcp/443 + tcp/80 from 0.0.0.0/0 (CF allowlist enforced at nginx, not SG).
- Elastic IP `13.204.52.248` allocated + associated → stable IP for Cloudflare A-record across EC2 restarts. Free while attached.
- EC2 `i-0e7b89bd91b67a291` (`qong-dev-server`): t3.medium, AMI `ami-0c54f8b78468b2ba2` (same as QA), `subnet-0eecf25001fad5cc9` in `ap-south-1a`, IAM `may26-ec2-ssm-role`, no key pair (SSM-only access), IMDSv2 required.
- 30 GB encrypted gp3 root + 50 GB encrypted gp3 data EBS (`vol-00152abd9fa8f1bf8`) attached as `/dev/sdf`, formatted ext4, mounted at `/mnt/qong-data` via UUID-pinned fstab entry.
- 7 SSM SecureString params under `/may26aws/qong-dev/`: `openrouter-api-key` (reuses the QA value), `secret-key`, `ls-api-key`, `postgres-password`, `redis-password`, `minio-root-user`, `minio-root-password`. All freshly generated with `openssl rand -hex` — guaranteed alphanumeric only, so no shell-special-char surprises like the `$wrv` SECRET_KEY corruption that FEATURES #19 documented for QA.

**Phase 1B — VM bootstrap (via SSM RunCommand):**
- apt installed docker.io, docker-compose-v2, git, jq, python3-boto3, unzip, curl
- AWS CLI v2 installed via the official `awscli-exe-linux-x86_64.zip` (Ubuntu 24.04 dropped `awscli` from apt — fix added)
- Reused QA's `qong-deploy` SSH key + ssh config via SSM-fetch from QA, base64-piped to dev. Both EC2s now share the same GitHub deploy key (acceptable for dev/QA scope; dev-only or QA-only rotation is a future option).
- Repo cloned at `c7a8928` (`feature/digital-twin`) to `/opt/qong` (owned by ubuntu).
- `git config --system --add safe.directory /opt/qong` so SSM RunCommand (running as root) can operate on the repo without "dubious ownership" errors.
- `.env.dev` rendered from SSM via a Python script that fetches all 7 params with `boto3.client("ssm").get_parameters_by_path`, then escapes `$` → `$$` for Compose interpolation safety. The full file is written to `/opt/qong/.env.dev` with mode 600.
- `docker-compose.override.dev.yml` written: web binds to `127.0.0.1:8000` (not host 80), data volumes point at `/mnt/qong-data/{uploads,job_outputs,postgres,minio}`, disables `nginx`/`label-studio-mcp`/`trainer` services with `profiles: [disabled]`.

**Phase 2 — Storage cutover (GCS → S3, restore from archive):**
- The dev EC2 role couldn't read the new archive bucket out of the box; added a bucket policy on `qong-pid-archive-2026-06-02` granting `s3:GetObject` + `s3:ListBucket` to `arn:aws:iam::449901518037:role/may26-ec2-ssm-role`. Identity-policy-on-shared-IAM-role left untouched.
- Restore sequence on the new EC2:
  1. `docker compose build web` with `BUILD_ID=$(git rev-parse --short HEAD)` baked into `__QONG_BUILD__` via the Vite define (FEATURES #19 queue-item B mechanism).
  2. `up -d postgres redis`, wait for `pg_isready`.
  3. `aws s3 cp s3://.../db-dumps/qong-dev-postgres-2026-06-02.sql` → `psql -U qong -d postgres -v ON_ERROR_STOP=0 < dump.sql`. Errors about pre-existing `qong` role and `qong` database are expected and ignored; data tables load into the qong DB. Verified: **8 users, 43 jobs, 706 valve_rows** — exact match with the GCP source.
  4. `aws s3 cp s3://.../vm-tarballs/qong-vm-data-2026-06-02.tar.gz` → `tar xzf -C /mnt/qong-data`. Verified: **44 PDFs in /mnt/qong-data/uploads** (matches the freshest VM-disk count, +4 over GCS qong-backups).
  5. `up -d --no-build web minio label-studio cpu-worker`.
- **Bug surfaced + fixed:** After the pg_dumpall restore, the `qong` role's password was reset to the **GCP value** (from the dump's `ALTER ROLE ... WITH ENCRYPTED PASSWORD ...` line), which no longer matched the freshly-generated SSM password in `.env.dev`. Web crashed in a loop with `psycopg2.OperationalError: password authentication failed for user "qong"`. Fixed: `ALTER ROLE qong WITH PASSWORD '<ssm-value>'` from a `psql -U qong` connection. Web recovered immediately on restart. **Lesson: pg_dumpall's ALTER ROLE statements overwrite role passwords on the target — restore order matters when the new env has fresh credentials. Either restore *before* changing the password, or run an ALTER ROLE re-sync after.**

**Phase 3 — TLS + DNS cutover:**
- Host nginx 1.24 installed on dev EC2. Cloudflare Origin Certificate + private key + `cloudflare-ips.conf` copied verbatim from QA via SSM (cert covers `*.qongsystems.com` so it works for both subdomains). nginx site `qong-dev` configured identically to QA's `qong-qa` (TLS termination on 443, CF IP allowlist via `include` + `deny all`, `proxy_pass http://127.0.0.1:8000`, `client_max_body_size 100M`, websocket + long-poll headers, 600s read timeout for PDF endpoints).
- docker `web` rebound from `0.0.0.0:80:8000` → `127.0.0.1:8000:8000` (host nginx now fronts it).
- User updated the Cloudflare A-record for `dev.qongsystems.com` → `13.204.52.248`.
- Validation: `curl https://dev.qongsystems.com/healthz` → **HTTP 200** through CF edge → CF Full (Strict) → origin TLS (CF Origin Cert) → nginx → docker web → FastAPI. Direct origin probe with non-CF IP returns 403 (nginx allowlist working).

**Result:**
- dev.qongsystems.com live on AWS with same security posture as QA (CF Full Strict, allowlist, AES256 SSM secrets, no SSH ingress).
- GCP `qong-dev-server` still running but unused for traffic. 7-day soak begins; decommission tracked as Phase 4 (FEATURES TBD).
- Cost: ~$36/mo running (t3.medium + 30 GB root + 50 GB data + EIP free while attached) + the ~$0.06/mo archive bucket from #20. QA continues at its own ~$36/mo. Total: ~$72/mo AWS + decaying GCP cost until #20 Phase 4.

**Notes:**
- *Many small footguns surfaced and were fixed in-line.* In rough order: SG description rejected unicode em-dash; bash `set -e` didn't trigger on a failed run-instances captured into `EC2=$(...)`; the wrong instance ID was looked up via a stray `Reservations[0]` query (turned out to be `may26-ollama`, harmlessly); `awscli` no longer in apt on 24.04; `lsblk` awk column counting was wrong for empty MOUNTPOINT; `git` refused root operations on ubuntu-owned `/opt/qong`; SSM RunCommand stdout truncates at ~24KB (lost the tail of the long bootstrap output); `may26-ec2-ssm-role` lacked S3 perms for the new archive bucket; pg_dumpall ALTER ROLE overwrote password; CF Full Strict needs origin TLS not HTTP. All resolved within this session.
- *Repo deploy key shared with QA.* Both EC2s use the same `qong-deploy` private key for `git@qong-product:Qong-Systems/qong_product.git`. Acceptable for dev+QA scope. Rotation would require regenerating + adding both as separate GitHub deploy keys, or moving to a deploy token; deferred.
- *cpu-worker reported "already exists" image conflict* during `up -d` but the container is running fine. Investigated only briefly — likely a docker buildx parallel-build noise that doesn't affect runtime. Tracked as a low-priority follow-up.
- *Port 80 still open in the SG* — used during bootstrap before nginx took 443; should be closed before any real users. Tracked in queue items.
- *GCP rollback path intact:* the original `qong-dev-server` VM is still running on GCP. To roll back: change Cloudflare A-record back to `34.126.93.103` (the GCP IP). The dump-restore on AWS doesn't mutate GCP at all. The 7-day soak window is conservative; could shorten if comfortable.

---

## [2026-06-02] #20 — AWS migration Phase 0: full GCP PID-doc backup to S3 (3-way redundancy)

**Type:** infra | decision
**Stage:** infra
**Status:** shipped

**Why:** User asked to move the `dev` environment from GCP to AWS (consolidating to the same `tnbqong` AWS account that already hosts QA), plus migrate GCP Cloud Storage to S3. Explicit prerequisite: "before that make sure, we have save all our PID docs. so we can begin with those PID on new AWS server." This entry covers Phase 0 only — the pre-migration safety backup. Phases 1-4 (provision AWS dev, migrate storage, cutover DNS, decommission GCP) are tracked in SESSION_STATE queue items and will get their own FEATURES entries when shipped.

**What:** Inventoried the GCP env, then created a 3-way-redundant backup of every PID-related byte before touching anything on the source.

GCP source state at backup time:
- VM `qong-dev-server` (e2-standard-2 + 50 GB disk, asia-southeast1-c) serving https://dev.qongsystems.com — Postgres `qong` DB has **8 users, 43 jobs, 706 valve rows**.
- VM `qong-intake-server` (e2-small + 20 GB) — separate intake service.
- GCS `gs://qong-backups/` — 502 MB across `uploads/` (40 PDFs, 34 MB), `job_outputs/` (2,892 files, 423 MB), `models/` (45 MB), `postgres/` (59 KB legacy dump).
- GCS `gs://qong-intake-data/` — 37 MB, 3 PDFs from the intake server.
- AWS S3 in `449901518037` had **zero buckets** — clean slate.

**Important finding during inventory:** the VM's `/app/qong_poc/uploads/` (44 PDFs, 39 MB) and `/app/qong_poc/job_outputs/` (3,089 files, 837 MB) **contain more data than the GCS qong-backups bucket** (+4 PDFs, +197 files, ~+414 MB). The GCS bucket is a partial historical archive, not a complete mirror. Without the VM tarball below, those newest files would only exist on the VM disk (and the daily disk snapshots).

3-way redundancy achieved:

1. **Fresh GCP disk snapshot** — `qong-dev-server-pre-aws-cutover-20260602-151219` (50 GB logical, 28.9 GB storage). Captures the entire `/app/qong_poc/` tree plus docker volumes (postgres, minio, label_studio) at the moment of the migration kickoff. Restore path: create a new disk from this snapshot, mount, extract whatever's needed.

2. **GCS unchanged** — both buckets left intact for now; will be deleted in Phase 4 only after the AWS dev environment has been validated for 7+ days.

3. **New S3 archive** — `s3://qong-pid-archive-2026-06-02` in `ap-south-1`, AES256 (SSE-S3), versioning enabled, public access blocked. Contents:
   - `MANIFEST.json` — full inventory with SHA256s, sizes, restore instructions
   - `db-dumps/qong-dev-postgres-2026-06-02.sql` — 10.5 MB `pg_dumpall` (databases: `qong`, `label_studio`, `postgres`; source user `qong`); SHA256 `6f3027b5b37b3519792a3807f0b6a7347a5d1ae3ee12fd7e52065daa521d28aa`
   - `vm-tarballs/qong-vm-data-2026-06-02.tar.gz` — 531 MB gzipped tar of `uploads/` + `job_outputs/` (3,225 entries); SHA256 `f3e0bb39ccab17dcc8a063f0e3d2758e5ffa7119f7fbf7f35d5301a633cc9f30`
   - `gcs-qong-backups/` — verbatim copy of `gs://qong-backups/` (2,935 objects, 502,091,044 bytes exact byte match)
   - `gcs-qong-intake-data/` — verbatim copy of `gs://qong-intake-data/` (3 objects, 37,539,001 bytes exact byte match)
   - **Total:** 2,941 objects, 1.08 GB

**Result:**
- Spot-check verification: 5 random PDFs from `gcs-qong-backups/uploads/` — MD5 from GCS source matches base64-decoded S3 ETag for all 5. **0 mismatches across 5 random samples**.
- Cost: <$0.10 one-time egress, ~$0.06/mo recurring (S3 storage + snapshot incremental).
- Time: ~25 min wall clock from `aws s3api create-bucket` to verified manifest, including the SCP-via-IAP false-start (see Notes).

**Notes:**
- **EC2 deploy-key gotcha is also live for the dev VM via a different mechanism**: the new dev VM (Phase 1) will need the same `qong-product` SSH alias setup that QA needed (FEATURES #19 Part 4). Document during Phase 1.
- **Don't use `gcloud compute scp` for files > ~50 MB through IAP**. Threw the IAP tunnel at ~0.3 MB/s and stalled at 8% (42 MB of 531 MB). Killed it after ~2 minutes; rerouted via GCS: `gcloud storage cp` from VM to GCS ran at **128 MB/s** (literally 400× faster), then GCS → local at 16 MB/s, then local → S3 at ~30 MB/s. **Lesson: IAP tunnels are for `ssh` and small transfers; large transfers should go via GCS or direct EC2-side `aws s3 cp` when the VM has credentials.** Added to gotchas.
- **The `qong-intake-server` VM was NOT backed up** beyond the GCS `qong-intake-data` bucket. If that server holds state beyond the 3 PDFs in the bucket, capture before Phase 4 decommission.
- **Postgres dump captured `qong` + `label_studio` + globals** via `pg_dumpall`. Restore on the new AWS Postgres: `psql -U <new_user> < qong-dev-postgres-2026-06-02.sql`. The `\restrict` line at the top is a PostgreSQL 17 dump-format token; should restore cleanly on PG ≥ 16.
- **Pre-existing daily disk snapshots** (5/20 onwards) remain in GCP and will be kept until Phase 4. They are NOT in the new S3 archive — they're disk-level, not file-level, so cost more to keep around. The new snapshot taken this session is the canonical "pre-cutover" rollback point.
- The user picked the "Yes, execute Phase 0 as above" option from a 4-way menu (default plan; not the smaller "skip intake-data" variant). All scope kept.

---

## [2026-06-02] #19 — Jinja → SPA consistency sweep; public signup removed; 4 surfaces ported

**Type:** architecture | feature | bugfix
**Stage:** webapp
**Status:** shipped

**Why:** Two user asks converged: (a) "we don't need public signup — remove the /register URL", and (b) "remove any pending jinja form from our app … make new in SPA, to have consistent app". The pre-existing Jinja surface had drifted into a hybrid state — the React SPA covered /dashboard, /projects, /jobs, /admin/*, but user-facing /account, /account/api-keys, /account/billing, and /feedback were still Jinja form-POSTs against `webapp/templates/*`. Clicking "Account" in the SPA's AccountMenu navigated to a Jinja-rendered page, which is a UX inconsistency and a maintenance trap (two divergent UI stacks for a single product surface). Public /register was also still exposed at the HTTP layer despite the React Admin UI's `CreateUserModal` shipping in Phase 3 — meaning the same admin-creates-user flow existed twice (Jinja form-POST and the SPA's POST /api/v1/admin/users), with the public arm an unwanted attack surface.

**What:** Three-stage sweep on `feature/digital-twin`, two commits (`e84ccb6`, `0e846d3`):

1. **Public signup + Jinja /login removed** (`e84ccb6`):
   - DELETE `webapp/routers/auth.py` @router.get/post('/register')
   - DELETE `webapp/templates/{register,login}.html`
   - GET /login → 303 redirect to /signin (legacy bookmark compat only)
   - POST /login: error path returns JSON `{detail: ...}` (was Jinja-rendered HTML); SPA's `AuthContext.tsx` updated to parse JSON instead of regex-scraping `class="error-box"`
   - GET /logout: redirects to /signin (was /login)
   - `webapp/auth.py`: unauth-middleware 303 Location header /login → /signin (4 callsites)
   - `webapp/templates/base.html`: navbar "Login" link /login → /signin
   - `tests/e2e/test_admin_api.py` assertion updated to /signin
   - First-user bootstrap on a fresh DB is now a one-off SSM-direct SQLAlchemy script (template kept in 2026-06-02 session memory; pattern used to create QA's super_admin `tarun` after deleting the smoke user `qa-smoke-2026-06-01` via cascade-delete on `credit_transactions`).

2. **Account, API Keys, Billing, Feedback ported to SPA** (`0e846d3`):
   - Backend (`webapp/routers/api_v1.py`):
     - GET `/api/v1/account/transactions` — recent credit txns for current user
     - GET `/api/v1/account/api-keys` — list non-revoked keys (never exposes full value)
     - POST `/api/v1/account/api-keys` — create with one-time plaintext reveal in JSON body
     - DELETE `/api/v1/account/api-keys/{id}` — revoke (204; user-scoped, 404 on other-user-key)
     - GET `/api/v1/account/billing` — balance + tier + active plans
     - POST `/api/v1/feedback` — anon-allowed; same javascript:/data:/vbscript: page_url scrub as the pre-existing Jinja handler
   - Frontend:
     - `webapp/frontend/src/account/{api,types}.ts` — typed call helpers mirroring `admin/api.ts`
     - `webapp/frontend/src/routes/Account.tsx` — profile + transactions + billing combined
     - `webapp/frontend/src/routes/AccountApiKeys.tsx` — list + create-with-reveal + revoke (with copy-to-clipboard, dismiss-acknowledgement, and a "this is the only time" warning)
     - `webapp/frontend/src/routes/Feedback.tsx` — bug/feature/pricing/other form
     - `App.tsx`: 3 new authed routes mounted
     - `AccountMenu.tsx`: replaced "Shortcuts" + "Notifications" placeholders with real "API Keys" + "Send feedback" links
     - `dashboard/CreateProjectModal.tsx`: error-hint copy `/account/billing` → `/account`
   - Deleted: `webapp/routers/account.py` (entire file); `webapp/templates/account/{index,api_keys,billing}.html`; `webapp/templates/feedback.html`. `webapp/main.py` no longer imports `account_router`.
   - Security tests migrated:
     - `tests/unit/test_feedback_url_xss.py` ports the 9 hostile-URL parametrised cases (javascript:, data:, vbscript:, file:, ftp:, protocol-relative, JS-with-fake-netloc) to POST /api/v1/feedback. Status 200 → 201.
     - `tests/unit/test_account_api_keys.py` rewritten for JSON endpoints; **added two new security tests**: (1) GET /account/api-keys list response never contains the full key (only the 8-char prefix), and (2) DELETE another user's key returns 404 (not 403), matching the user-scoped query in `api_v1.py` — 403 would leak existence.
   - Lingering Jinja: only `annotate.html` + `base.html` (its host layout). Intentional per `webapp/routers/annotate.py:5` — "React SPA covers only customer-facing + super_admin surfaces; annotators get the legacy Jinja page". Confirmed kept by the user during the inventory pass.

3. **EC2 deploy-path latent bug fixed** during the QA deploy: `/opt/qong/.git/config` had `origin = git@github.com:Qong-Systems/qong_product.git` (bare GitHub host), but the deploy key was registered against the `qong-product` SSH alias in `~ubuntu/.ssh/config`. `git pull` had been silently failing with "Permission denied (publickey)" — the prior FEATURES #17 / #18 deploys appear to have relied on host-side `npm run build` + bind-mount rather than a real git-pull. Fixed once with `git remote set-url origin git@qong-product:Qong-Systems/qong_product.git`. Future deploys via SSM RunCommand → `sudo -i -u ubuntu git pull` now work without intervention.

**Result (if measurable):** Playwright-verified on `https://qa.qongsystems.com` end-to-end:
- `GET /register` → SPA "404 - This page doesn't exist." (no Jinja form anywhere)
- `GET /login` → 303 → `/signin` (SPA login renders)
- `POST /login` with bad creds → `400 application/json` `{"detail":"Invalid username or password"}` parsed by SPA AuthContext
- Login `tarun / CzlYN5pah7z5Dvbr` → 303 → `/dashboard`
- `GET /logout` → 303 → `/signin`, cookie cleared, subsequent `/api/v1/account` → 401
- `/account` SPA: shows profile + 1 txn row (`initial_admin_grant +10 → 20`) + 3 plans (Trial $0, Starter $19, Pro $149)
- `/account/api-keys` SPA: created `playwright-qa-smoke` → revealed `qk_24a9e2515760a01684c07034fb5fff3c` (32 hex, correct shape) → Bearer-authed against `/api/v1/account` returning `{"username":"tarun","role":"super_admin"}` → revoked → cookie-isolated Bearer retry returned 401 (revocation effective at auth layer, not just UI)
- `/feedback` SPA: submitted pricing-category form → 201 → "Thanks for your feedback!" banner. Hostile `page_url=javascript:alert(1)` curl-tested via SSM RunCommand on EC2 → DB row stored with `page_url=None` (security scrub holds across the port).
- AccountMenu popover items: `["Account", "API Keys", "Send feedback", "Sign out"]` — no more Shortcuts/Notifications placeholders.

**Notes:**
- *base.html still in tree* — only referenced by `annotate.html`. Becomes orphan-deletable the day the annotator surface gets ported to SPA (no current plan; out of SPA scope by design).
- *Pre-existing "20 credits on signup" bug surfaced* — the User model column default of 10 + `credits.grant(10, reason="signup_grant")` both fire at user creation, so the audit row's intent (just record the existing 10) ends up adding another 10. Not introduced by this work, just observed. Tracked as a follow-up; either drop the default-10 or stop double-granting.
- *`wrv` compose warning still benign* — surfaced again during this deploy. The compose interpolation `${wrv}` is somewhere in the docker-compose chain; harmless empty-string default. Low-priority cleanup.
- *RouterAuth tests not updated* — `webapp/frontend/src/auth/RequireAuth.test.tsx` already covered /signin redirection; no changes needed there. New SPA routes (Account, AccountApiKeys, Feedback) have NO unit tests yet — they rely on Playwright-on-QA verification documented above. Worth adding component tests if test parity with admin/*.test.tsx becomes a priority.
- *Admin-side feedback UI not retested* — the new Playwright feedback row should now appear in `/admin/feedback`. Eyeball check skipped for time; defer to next admin-feedback session.
- *AccountMenu no longer has Shortcuts / Notifications* — these were placeholders. If product wants them back, restore the buttons but route them somewhere real.

---

## [2026-06-01] #18 — QA SPA bootstrap fixed (Playwright caught what curl missed); 4 root-causes addressed

**Type:** bugfix
**Stage:** infra | webapp
**Status:** shipped

**Why:** After FEATURES #17 declared QA "live" (all HTTP smoke checks green), Playwright revealed the SPA was actually broken in real browsers: `/assets/index-Ck0HogSN.js` returned `text/html` instead of JavaScript, breaking the strict-MIME ES-module bootstrap. Four overlapping root-causes had to be unwound to fully fix it.

**What:**

1. **Import-time SPA mount gate (`webapp/main.py:148`)** — `if (_SPA_DIST/"assets").exists()` ran at module import. When web container started before `npm run build`, the mount was never registered, so the catch-all served `index.html` for every `/assets/*` URL. Fixed by mounting unconditionally with `StaticFiles(..., check_dir=False)` — missing files now return real 404s, not HTML-as-JS.

2. **Dockerfile didn't bake the SPA** — `webapp/frontend/dist/` is gitignored, Dockerfile had no node stage. Every deploy required a host-side `npm ci && npm run build` before `docker compose up`, easy to forget. Fixed with a multi-stage Dockerfile (`node:20-alpine AS frontend` builds dist, copied into the python runtime stage via `COPY --from=frontend`).

3. **Compose volume merge silently shadowed the baked dist** — Docker Compose CONCATENATES volume lists between base and override files (it does NOT replace them). Base `docker-compose.yml` had `./webapp:/app/webapp` for local-dev hot-reload; the QA override couldn't suppress it. Result: host `/opt/qong/webapp/frontend/dist` (empty) shadowed the baked dist from step #2. Fixed by moving dev bind-mounts out of base into a new `docker-compose.override.yml` (auto-loaded only when `docker compose up` is invoked without `-f`; explicit-`-f` QA stack skips it). Removed `docker-compose.override.yml` from `.gitignore` since it's now the canonical dev override; per-developer customization moves to `docker-compose.local.yml` (still gitignored).

4. **Cloudflare cached the broken text/html response under the JS asset URL** — CF auto-caches common static-asset extensions regardless of `Content-Type`. After fixing the origin, the cached HIT for `/assets/index-Ck0HogSN.js` continued serving the bad response. Fixed by adding a small `window.__QONG_BUILD__ = "2026-06-01T12:20Z"` side-effect in `webapp/frontend/src/main.tsx` — survives Vite minification (it's an assignment, not a comment), changes bundle bytes, produces a new content hash (`index-C_wqiXGd.js`), new asset URL, new CF cache key, MISS. Bump the date string in this line on any future incident where CF caches a wrong response under a hash we need to retire. Long-term, wire `BUILD_ID` via a vite `define` from a CI env var (deferred — see Notes).

Also **added `tests/smoke/qa_smoke.mjs`** — standalone Node ESM script using Playwright. Launches headless Chromium, asserts no unexpected console errors, no bad MIME types on `.js`/`.css` requests, no failed network requests, non-empty DOM. Filters the expected `/api/v1/account` 401 anonymous check. Header docs invocation in a future `deploy-qa.yml` workflow. Would have caught this entire bug class on the first deploy.

**Result (if measurable):** `https://qa.qongsystems.com/` loads cleanly in browser — `window.__QONG_BUILD__` reads `"2026-06-01T12:20Z"` (confirms users see the THIS-deploy bundle), React mounts, all asset MIME types correct, only the expected 401 in console.

**Notes:**
- The bind-mount-vs-baked-dist conflict is a one-time setup issue, not a runtime one — but the consequence is total SPA failure with no clear error in HTTP-level checks. The takeaway: any future post-deploy smoke MUST be browser-based, not curl-based. `tests/smoke/qa_smoke.mjs` enforces this.
- **`BUILD_ID` via CI env var** — proper long-term solution. Edit `vite.config.ts` to add `define: { __BUILD_ID__: JSON.stringify(process.env.BUILD_ID || "dev") }`. Reference it from `main.tsx`. CI passes `BUILD_ID=$GITHUB_SHA` per deploy → unique hash per commit, predictable per-source-state. Until that lands, the date-string in `main.tsx` is bumped by hand on demand.
- **Removed `docker-compose.override.yml` from .gitignore** — used to be per-developer local file; now it IS the canonical dev override (with the bind-mounts). Per-developer overrides go in `docker-compose.local.yml` (still gitignored).
- **Compose volume merge rule** is one of the gnarlier foot-guns. There's no documented way to suppress a base-defined volume from an override; the only workaround is structural (base = production-minimal, env-specific overrides add what each env needs). Future schema/refactor work should keep this invariant.

---

## [2026-06-01] #17 — AWS QA app live at qa.qongsystems.com; local stack switched from SQLite → Postgres

**Type:** infra
**Stage:** infra | webapp
**Status:** shipped

**Why:** Two threads converged this session. First, local was still on SQLite while production (`dev.qongsystems.com`) and QA (`qa.qongsystems.com`) both target Postgres — that mismatch meant Postgres-only bugs surfaced in QA after passing locally. Second, the AWS QA bring-up (FEATURES #16) was stuck on a placeholder OpenRouter SSM key. User set a real QA key, unblocking PHASE 2.

**What:**
- *Local stack:* `.env` populated with 9 missing keys (POSTGRES/REDIS/MINIO/STORAGE/GPU_CALLBACK), `DATABASE_URL=postgresql://qong:...@postgres:5432/qong`. New `postgres/init/01-create-label-studio-db.sql` runs on first Postgres boot to create the `label_studio` DB that Label Studio expects (compose's `POSTGRES_DB=qong` would otherwise leave it missing). `web` now has `depends_on: postgres (healthy) + redis (started)` so `run_migrations()` can't race. Tailscale port lines on web:8000 and redis:6379 commented out in base compose (no Tailscale on local Mac or AWS) — when this branch merges to `dev`, these need to come back for the GCP VM that talks to the Windows GPU box. Commits `4dd9d3e` and `b9e8def`.
- *QA bring-up:* OpenRouter SSM param replaced (Version 2). New `docker-compose.override.qa.yml` binds `/mnt/qong-data/{postgres,minio,uploads,job_outputs}` to the EBS data volume so QA data survives EC2 replacement, and disables `nginx` / `label-studio-mcp` / `trainer` services that conflict with host nginx or aren't needed in QA. `.env.qa` rendered on EC2 by SSM-driven script reading 7 SecureString params (added `/may26aws/qong-qa/redis-password` — spec missed it). AWS CLI v2 installed on EC2 (PHASE 1 bootstrap missed it). SPA built in-place via `npm ci && npm run build` (Dockerfile doesn't include a frontend build step — see Notes). nginx `qong-qa` site swapped from 503 placeholder to `proxy_pass http://127.0.0.1:8000` with `X-Forwarded-*` headers, WS upgrade headers, and 600s read timeout for long-running PDF endpoints.

**Result (if measurable):**
- `https://qa.qongsystems.com/healthz` → 200, `/` → 200 (SPA serving), `/api/v1/account` → 401 (auth gating works)
- Public registration round-trip succeeded; user landed in QA Postgres with `id=1, role=super_admin` (first-user auto-promotion in `webapp/routers/auth.py:107`)
- Build time on t3.medium: ~4 min docker compose build + ~50s npm install + 5s vite build = under 6 min total
- Marginal cost of this bring-up: <$0.10 (EC2 was already running)

**Notes:**
- *Dockerfile gap:* SPA build is not part of the image. Today it works because the bind-mount `./webapp:/app/webapp` exposes the host-built `dist/` to the container. Long-term fix: add a multi-stage Dockerfile that runs `npm ci && npm run build` in a node stage, then copies `dist/` into the python stage. Until then, every deploy must rebuild the SPA on-host before `docker compose up`.
- *Tailscale binding regression risk:* base `docker-compose.yml` no longer binds `100.127.190.88:*`. When merging `feature/digital-twin` → `dev`, restore those two `ports:` lines (or move them into a `docker-compose.override.dev.yml`) so the Windows GPU worker can still reach the GCP web container.
- *Smoke-test user `qa-smoke-2026-06-01`:* created as first user → got auto-promoted to super_admin. Real first human user on QA will NOT get admin — manually demote/delete the smoke user before onboarding real users.
- *Cloudflare Origin Cert rotation still pending* (private key was pasted in chat 2026-05-29). Limited blast radius (CF↔origin only, not public CA trust) but rotate when convenient.
- *Local admin password:* `admin` / `6GvVUz9HqaMeO1Bq` on `http://localhost:8000`. Saved in user auto-memory at `memory/reference_local_admin_password.md`. Local Postgres ≠ QA Postgres ≠ GCP dev Postgres — three independent DBs.

---

## [2026-05-30] #16 — AWS QA environment provisioned at qa.qongsystems.com (TLS live, app bring-up paused)

**Type:** infra
**Stage:** infra
**Status:** experimental — TLS live, docker compose not yet running

**Why:** `feature/digital-twin` is 14 commits ahead of `dev` (Phase 1–4 SPA cutover, deliverable reorder, admin port, %PDF- magic byte, two design specs). Deploying directly to `dev.qongsystems.com` on GCP risks current customers who use it for valve list extraction. Need a parallel URL to validate the branch end-to-end before promoting. AWS chosen because the team is migrating off GCP — QA also doubles as the AWS-learning lab. Cloud-agnostic shape (no RDS/ECS/ALB) so the pattern transfers cleanly to dev/prod later.

**What:** Single `t3.medium` EC2 (`i-04be6af1fb7929a0c`) in `ap-south-1`, IMDSv2-required, IAM role `may26-ec2-ssm-role`, public IP `43.205.96.86`, 30 GB encrypted root + 50 GB gp3 data EBS (`vol-06bdf1fab12bd2971`) at `/mnt/qong-data`. nginx 1.24 terminates TLS using a Cloudflare Origin Certificate (SAN `qa.qongsystems.com` + `*.qongsystems.com`, valid until 2041). Cloudflare proxy ON, SSL mode Full (strict), nginx allowlist restricts ingress to CF IP ranges only. SG `sg-0ece96660d8ee00bc` opens 443 from anywhere; no public 22 (SSM only). Reuses shared VPC `vpc-0c9453aafa64f6e40` and the existing `may26-ec2-ssm-role` instance profile. SSM Parameter Store namespace `/may26aws/qong-qa/*` for secrets (6 SecureString params, 5 of 6 populated). Specs at `docs/superpowers/specs/2026-05-29-aws-qa-environment-design.md`.

**Result (if measurable):** `https://qa.qongsystems.com/healthz` returns `200 ok` through the full Cloudflare→nginx stack. `/` returns 503 placeholder (docker compose not yet up). Monthly cost: ~$36/mo running, ~$6/mo if stopped.

**Notes:** Bring-up paused mid-session. ONE blocker before docker compose can come up: `/may26aws/qong-qa/openrouter-api-key` still holds the placeholder value `PLACEHOLDER_REPLACE_VIA_CONSOLE`. Once set, PHASE 2 (clone + override compose + render `.env.qa` from SSM + `docker compose up` + swap nginx 503 for `proxy_pass http://127.0.0.1:8000`) runs in ~15 min. EC2 deploy key SHA256 fingerprint `g49BJAfltEoDkdnpokihv7Bt31X6sWF2vsSEfH72rvA` added to `Qong-Systems/qong_product` deploy keys by user. **Origin Certificate private key was pasted in chat — rotate the cert** after end-to-end test passes; blast radius is limited (CF-edge↔origin only, no public CA trust) but best practice is to rotate. AWS account `449901518037` is treated as production per `../../../may26aws/CLAUDE.md` PROD RULES; every mutation in future sessions still needs same-turn user approval. Resource inventory should be appended to `may26aws/CLAUDE.md` once bring-up succeeds so the account-wide registry stays accurate. Full handoff in `SESSION_STATE.md`.

---

## [2026-05-28] #15 — Phase 3: Admin features ported to React with full test coverage

**Type:** feature
**Stage:** webapp
**Status:** shipped (React UI lives alongside legacy Jinja; Jinja deletion deferred to a follow-up after prod SPA deployment)

**Why:** User asked: *"on our main branch, we had created admin login with feature to add new users and approve and give them role. is that converted into new react ui?"* — answer was no, only customer-facing surfaces were ported in Phase 1+2. They then said: *"spin up phase 3, and port with testing and make sure we don't miss old users or projects."* So Phase 3 ports the 6 admin surfaces from Jinja to React, with full E2E + component-test coverage, and verified data continuity (every existing User/Job/Plan/Feedback row surfaces in the new UI).

**What — backend:**
- **`webapp/routers/api_v1_admin.py`** (NEW, 19 endpoints) — JSON API mirroring the legacy Jinja /admin/* forms. Cookie auth via existing `require_super_admin` dep. Endpoints: users CRUD + role/tier/activate/deactivate/grant-credits, dashboard KPIs, credits ledger, feedback list+update, plans list+create+toggle, label-studio list+sync-labels+sync-job. Same SQLAlchemy queries — zero schema changes.
- **`webapp/routers/api_v1.py`** — `/api/v1/account` now returns `id`, `email`, and `role` (was only username/credits/tier). Fixed a real bug surfaced by Playwright A/B test: AuthContext fell back to `data.tier` when `data.role` was missing, treating super_admin as "trial" and 403-ing the admin out of /admin/*. SECURITY: role must come from the server explicitly — never derived from tier or any other client-readable field.
- **`webapp/main.py`** — registers the new api_v1_admin router.

**What — frontend:**
- **`webapp/frontend/src/admin/types.ts`** — TS interfaces for all admin resources.
- **`webapp/frontend/src/admin/api.ts`** — typed fetch helpers for every endpoint. `HttpError` class, opaque-redirect detection for 401 handling, cookie credentials.
- **`webapp/frontend/src/admin/AdminLayout.tsx`** — left rail with 6 admin nav links + role gate (renders 403 page if `user.role !== "super_admin"`).
- **6 surface components:**
  - `AdminUsers.tsx` + `CreateUserModal.tsx` + `EditUserModal.tsx` — list, create, edit (role/tier/activate/deactivate/grant-credits/delete with self-deletion blocked).
  - `AdminDashboard.tsx` — KPI stat-strip (8 cards) + recent transactions table.
  - `AdminFeedback.tsx` — status-filter chips + items list + per-item status dropdown + admin notes. Reuses the iter-2 security fix: only renders an `<a href>` when page_url starts with http(s).
  - `AdminCredits.tsx` — read-only ledger with username search + sign filter (granted/consumed/all).
  - `AdminPlans.tsx` + inline `CreatePlanModal` — list/create/toggle.
  - `AdminLabelStudio.tsx` — completed-jobs table with LS-stats column + sync-job action + global sync-labels action. Banner when LS not configured.
- **`webapp/frontend/src/auth/AuthContext.tsx`** — role now read strictly from `data.role` (never tier).
- **`webapp/frontend/src/routes/Layout.tsx`** — Shield icon in nav for super_admin only, links to /admin.
- **`webapp/frontend/src/App.tsx`** — `/admin/*` nested routes under AdminLayout.

**Tests:**
- **`tests/e2e/test_admin_api.py`** (NEW, 43 tests) — every endpoint × {super_admin success, regular user 403, no auth 303}; business rules (cannot demote/deactivate/delete self, invalid role/tier/amount rejected, feedback filter validation, plan toggle round-trip, LS configured/unconfigured paths). All 43 pass.
- **`tests/unit/test_api_v1.py`** — existing 7 tests still pass (account endpoint shape change is backwards-compatible).
- **Vitest + React Testing Library wired** in `vite.config.ts` (`test:` block) + `src/test/setup.ts` (RTL cleanup + jest-dom). Added devDeps: `vitest`, `@testing-library/{react,jest-dom,user-event}`, `jsdom`.
- **6 component test files** (`src/admin/Admin*.test.tsx`) — 17 tests total covering: table renders, search/filter behaviour, modal opens, API calls fire with correct arguments, error banners, defense-in-depth (`javascript:` page_url not rendered as href).
- Total: 157 backend tests pass, 18 frontend component tests pass (smoke + 6 admin surfaces).

**Result (if measurable):**
- TypeScript build: 0 errors.
- Vite production bundle: 402 KB JS / 79 KB CSS (gzip 115 / 14 KB). +37 KB JS vs Phase 2 (the admin surfaces + lucide icons + Vitest infra in dev).
- A/B verified against legacy Jinja: both admin and seeded alice appear in /admin/users with identical data (role, tier, credits, status); seeded feedback appears with the safe https URL link.

**Notes:**
- **Legacy Jinja /admin/* routes NOT deleted in this commit.** User chose "Delete Jinja routes + templates after the React port is verified" — but verification is currently dev-only. The SPA isn't wired into prod yet (prod still serves Jinja at dev.qongsystems.com). Deleting Jinja now would 404 prod admin access. Plan: prod-deploy the SPA, A/B verify once more, then a separate small commit drops the 6 Jinja templates + the legacy route handlers from `webapp/routers/admin.py`.
- **The `/annotate` route stays** — it's annotator-role (not super_admin) and the Phase 3 port covers only super_admin surfaces. Annotators continue to use the Jinja landing.
- **The role-bug fix in `/api/v1/account`** is *also* relevant for the future deactivate-doesn't-revoke-session security finding noted in the security review. When that fix lands, `get_current_user` will need to check `is_active`; this endpoint's response will then accurately reflect it.
- **Dependency continuity check:** existing `webapp/credits.py:grant()` is reused by the grant-credits endpoint (same ledger row creation as the legacy Jinja). Existing `webapp/label_studio_client.py` helpers (is_configured, get_or_create_project, push_tiles, delete_all_tasks, sync_all_label_configs, get_project_stats) all reused unchanged.
- **Files touched/created:** ~25 files. New: 1 backend router, 1 backend E2E test file, 6 admin React components + 3 modal components, 6 component test files, 1 Vitest setup file, 1 admin scaffolding (types + api + AdminLayout). Modified: `webapp/main.py`, `webapp/routers/api_v1.py`, `webapp/frontend/src/App.tsx`, `webapp/frontend/src/auth/AuthContext.tsx`, `webapp/frontend/src/routes/Layout.tsx`, `webapp/frontend/vite.config.ts`, `webapp/frontend/package.json` (+ lock).

---

## [2026-05-28] #14 — QONG Studio Phase 2b+2c: DatasheetDrawer + BulkReviewScreen

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 2a (#13) shipped the Studio visual shell with stub buttons for Open Datasheet and Bulk Review. This commit lands the two real surfaces those buttons open, completing the full design loop the user committed to in chat2.md (Studio → drawer → bulk-review → back to studio with element selected + drawer reopened).

**What:**
- **DatasheetDrawer** (`webapp/frontend/src/studio/datasheet/`):
  - `schemas.ts` — 10 per-doc-type field schemas (datasheet, index, narrative, cande, io, valves, lines, equip, loop, tags); `defaultValues()` returns per-element + per-doc-type seed data. `FieldDef` with `w` hint (xs/sm/md/full = 1/2/3/4 grid cols), `extracted` + `conf` for confidence pills.
  - `DocTypeIcon.tsx` — maps icon names (`file-text`, `list-checks`, `scroll-text`, `git-merge`, etc.) to lucide-react components.
  - `DSField.tsx` — single field with locked-vs-input modes, P&ID badge for extracted fields, confidence pill, pencil to unlock for manual override, "Manual" hint for non-extracted empty fields.
  - `DatasheetDrawer.tsx` — full drawer: doc-type picker (swaps schema), Bulk Review pill (count badge), close (Esc + outside-click), title + completion progress, **vertical accordion** sections (sections 0+1 open by default per chat2.md decision to replace horizontal scroll), Save Draft + Export footer. Backdrop blocks the studio behind.
- **BulkReviewScreen** (`webapp/frontend/src/studio/bulk-review/`):
  - `deliverables.ts` — `DELIVERABLES` list (10 docs with done/total counts), `COLUMNS` per-deliverable table column schemas, `DETAIL_GROUPS` per-deliverable right-panel field groups.
  - `buildRows.ts` — 14 demo instruments (PV-203, FT-101, V-101, PT-201, TT-301, LT-401, FV-101, PSV-022, XV-501, P-101, E-104, FT-202, PT-301, TV-204), enriched per-deliverable.
  - `BulkReviewScreen.tsx` — workbench top bar (Back to Studio, breadcrumb, search, Filter, Export, toggleable panel-right), left deliverables nav with completion bars, center table with grid-template-columns reshaping per deliverable + stat strip (Total/Complete/Review/Missing), right detail panel with Open in Studio action.
- **Studio.tsx wiring**:
  - Real `DatasheetDrawer` mounted (no more alert stub).
  - `mode: "studio" | "bulk"` state. When `bulk`, renders `BulkReviewScreen` full-screen.
  - `onBulkReview` closes the drawer and switches to bulk mode (triggered by both the studio top-bar "Bulk Review" button and the drawer's BULK REVIEW pill).
  - `onOpenInStudio(id)` callback from bulk-review: sets `selectedId` to the picked tag, returns to studio mode, and reopens the drawer — matches v3 design behavior verbatim.

**Result (if measurable):**
- TypeScript build clean. Vite bundle 366 KB JS / 79 KB CSS (gzipped 108/14 KB), up from 2a's 331/78 KB.
- Verified the full loop end-to-end with Playwright + a seeded job (Block-18-Crude-Train-2.pdf): Studio → click Open Datasheet → drawer shows Control Valve PV-203 with 14/21 fields (67%) → click BULK REVIEW pill → workbench shows 14 instruments with PV-203 row pre-selected → click FT-101 row → right panel updates → click Open in Studio → studio reopens with FT-101 selected + drawer reopened with Flow Transmitter schema and per-element defaults (Reflux header flow, Differential Pressure 4-20mA HART, P-12-102-CS150 line).

**Notes:**
- **`1fr` column compression on narrow viewport.** In Bulk Review, the "Type" column uses `w: "1fr"` in the datasheet schema but ends up compressed to ~30px on a 1200px viewport because the parent grid's free-space calculation doesn't expand 1fr when other fixed cols sum near the container width. Minor visual bug — not breaking. Likely the bundle's CSS expects a wider viewport (1600+). Easy follow-up: switch `.br-table-wrap` to `overflow-x: auto` and let the table extend; or tighten fixed widths.
- **All bulk-review demo data is canonical to the design** — same 14 base rows from `bulk-review.jsx`, including the `sel: true` flag on PV-203 (selects it on initial load) and `missing: true` flags on LT-401, E-104, PT-301 (which makes Missing count = 3 in the stat strip).
- **DatasheetDrawer uses `useMemo` for defaults** — when element OR docType changes, defaults recompute, then `useEffect([defaults])` resets the form. This is the v3 design's pattern and it works correctly.
- **Backdrop click-to-close + Esc** both wired on the drawer. Bulk Review doesn't have a backdrop (it's a full-screen replacement).
- **`display: contents` on bulk-review rows** — each `.br-row` uses `display: contents` so its children become direct grid items of the parent `.br-table`. That's why selection styling has to be applied to individual cells (via inline style `color: var(--qong-magenta)`) rather than the row container.
- **No backend changes** — both surfaces are pure UI on top of the existing /api/v1/jobs/{job_id} endpoint. Real wiring to per-instrument data (instead of the 14-row demo set) is a separate piece of work (call it Phase 2d) — would need a `/api/v1/jobs/{id}/instruments` endpoint and the pipeline_runner to write canonical.json with per-instrument entries (we already have a `canonical.py` model from Plan A).
- **Files modified vs Phase 2a:** `webapp/frontend/src/studio/Studio.tsx` (drawer + bulk-review wiring) and 6 new files under `studio/datasheet/` + `studio/bulk-review/`. The studio.css from 2a already contains all the styles for the drawer + bulk-review (was the v3 superset).

---

## [2026-05-28] #13 — QONG Studio design bundle Phase 2a: Studio visual shell

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Phase 1 (#12) shipped Dashboard + Login + theme. User then exported an updated design bundle (`design/qong-studio-v3/`) with the Studio screen polished: "Bulk Review" button added before "Save" in the top bar, "Save & continue" renamed to "Save", Issues panel replaced with "Elements on Sheet" (lists all detected elements with bidirectional canvas-list selection), and the prior horizontal datasheet tabs replaced with a vertical accordion. v3 also adds two new surfaces (DatasheetDrawer rewrite + BulkReviewScreen) but those are Phase 2b/2c. Phase 2a is the Studio visual shell on its own — clicking a tile on the Dashboard opens this Studio.

**What:**
- **Studio component split** under `webapp/frontend/src/studio/`:
  - `types.ts` — Sheet, CanvasElement, SessionEvent, ProjectLike interfaces.
  - `buildSheets.ts` — deterministic sheet generator (8–28 per project, status distribution).
  - `SheetGlyph.tsx` — small SVG glyph for sheet rail thumbnails (theme-aware grid).
  - `PidCanvas.tsx` — center canvas: prototype V-101/FT-101/P-101/PV-203/E-104 elements with edges; pan via mouse drag (3px threshold to distinguish click vs pan), wheel zoom (0.3×–4×), `.canvas-inner.animated` for smooth button-driven transitions; theme-aware colors for fill/stroke/text/grid.
  - `SheetRail.tsx` — left rail: head (Sheets count), search, All/Issues/Pending tabs, sheet-tile list with status badges.
  - `StudioTopBar.tsx` — back btn, QONG mark, project + sheet meta + reviewer slug, issue badge, **Bulk Review** secondary btn (new), **Save** primary btn (was "Save & continue"), `SettingsMenu variant="dark-chrome"`, more-menu (Export I/O / Share / Settings / Exit).
  - `PropertiesPanel.tsx` — Selected Element card (tag, type, confidence bar, inflow/outflow, Confirm/Edit, Open Datasheet) + **Elements on Sheet** list (replaces Issues; bidirectional select with canvas) + This Session activity.
  - `StudioFoot.tsx` — keyboard shortcut bar + auto-save indicator.
  - `Studio.tsx` — orchestrator. Reads `theme` from ThemeContext, locks body scroll while mounted, manages selection/zoom/pan state, stubs Open Datasheet + Bulk Review with alert (Phase 2b/2c).
- **Route wiring** — `routes/JobDetail.tsx` rewritten to fetch `GET /api/v1/jobs/{job_id}` and render Studio. `routes/ReviewCanvas.tsx` collapses to a thin alias re-exporting JobDetail (legacy URL preserved). Old JobDetail placeholder (deliverable download grid) removed — those URLs are still reachable directly via `/api/v1/jobs/{id}/export/{type}/{fmt}` from Plan A.
- **Layout full-bleed routes** — `routes/Layout.tsx` now matches `/jobs/:jobId(/review)?` via regex so the Studio's own header replaces the app-nav. Existing `/` and `/signin` exact matches still apply.
- **Studio CSS** — `webapp/frontend/src/design/studio.css` updated to v3 (2016 → 2507 lines): adds `.element-row`, accordion `.ds-section`, `.bulk-review`, `.studio-top` polish, dark-scope override under `.studio` (drawer shows in dark even when theme is light, per user "in A, background is darkmode, drawer shud also show in dark mode").

**Result (if measurable):**
- TypeScript build clean. Vite bundle 331 KB JS / 78 KB CSS (gzip 99 KB / 14 KB) — up from Phase 1's 309/68 KB.
- Verified visually with a seeded job (Block-18-Crude-Train-2.pdf): three-pane layout, theme-aware studio chrome, sheet rail with 8 mock tiles, pan/zoom canvas with bidirectional selection, properties panel rendering all 5 detected elements with confidence pills.

**Notes:**
- **Phase 2b** (next session): port `datasheet.jsx` (459 LOC, +140 vs v2). Drawer widened to 720px, 4-col grid (`grid-auto-flow: dense`), vertical accordion sections (01 + 02 open by default, rest collapsed), 10 distinct deliverable schemas (each doc-type swaps the field set), Bulk Review pill in drawer header, dark-mode override.
- **Phase 2c** (next session): port `bulk-review.jsx` (466 LOC, new). Full-screen workbench: deliverables nav (10 docs), instrument table with per-deliverable column schema, toggleable right detail panel (default open, `panel-right` button in top bar), "Open in Studio" returns with element selected + drawer reopened.
- **Studio canvas elements are prototype** — V-101, FT-101, P-101, PV-203, E-104 are hardcoded in `PidCanvas.tsx` (DEMO_ELEMENTS export). Real wiring to job detections is a separate piece of work (Phase 2b or later); requires either parsing the existing valve-list CSV or storing detection JSON on Job.
- **Body scroll lock** added in `Studio.tsx` useEffect — Studio is a single-viewport surface, prevents the page from scrolling behind the studio chrome.
- **Datasheet types** that get an "Open Datasheet" button: Control Valve, Flow Transmitter, Block Valve, Centrifugal Pump (set in Studio.tsx). Exchangers and pumps without the magic types don't show the button — matches the design's behavior.
- **`Datasheet Explorations.html`** in v3 bundle (uses `design-canvas.jsx` + `explorations.jsx`) is a SEPARATE bundle — NOT in QONG Studio.html scope. Skipped from Phase 2 entirely; treated as research/mockup material.
- **lucide icons added** vs Phase 1: `arrow-left`, `arrow-up-right`, `chevron-down`, `chevron-up`, `download`, `git-pull-request`, `info`, `layout-grid`, `log-in`, `log-out`, `maximize`, `panel-right`, `pencil`, `radio`, `scan-search`, `settings-2`, `boxes`, `circle-dot`, `filter`, `share-2`, `keyboard`. All present in lucide-react 1.17.0.
- **Production-continuity rule confirmed:** `/jobs/:jobId` (React SPA) now renders Studio. The legacy FastAPI Jinja `/jobs/{id}` HTML route in `webapp/routers/jobs.py:111` is untouched — direct URL access outside the SPA (legacy customers, email links, the dashboard route in `webapp/routers/dashboard.py`) continues to render the old Jinja template. When a user navigates from the new Dashboard tile click, the SPA's `/jobs/:jobId` wins (BrowserRouter handles it before the FastAPI server responds).
- **Files modified:** `webapp/frontend/src/design/studio.css` (v2→v3), `webapp/frontend/src/routes/{JobDetail,ReviewCanvas,Layout}.tsx`, plus new files under `webapp/frontend/src/studio/`. No backend changes (existing `GET /api/v1/jobs/{job_id}` already provided what Studio needs).

---

## [2026-05-28] #12 — QONG Studio design bundle Phase 1: Dashboard + Login + theme system

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** User exported a fresh design bundle from Claude Design (`design/qong-studio-v2/`) covering 4 surfaces (Login, Projects/Dashboard, Studio, Datasheet drawer) plus a Settings popover with light/dark theming. Previous Dashboard.tsx was an "Awaiting design" placeholder. User explicitly asked for projects-as-tiles dashboard now, full design later. Phase 1 ships Dashboard + Login refresh + theming infrastructure; Studio + Datasheet deferred to Phase 2.

**What:**
- **Design tokens unchanged** — existing `webapp/frontend/src/design/tokens.css` was already identical to the bundle's `colors_and_type.css` (full semantic layer for `--fg`, `--surface`, `--border`, both light + dark themes). Only fix: `global.css` no longer hardcodes body bg/color so theme attribute wins.
- **Studio CSS imported** — copied bundle's `app.css` (2016 lines) verbatim to `webapp/frontend/src/design/studio.css`; imported from `global.css`.
- **Theme system** — new `webapp/frontend/src/theme/ThemeContext.tsx` with localStorage persistence (key `qong.theme`), prefers-color-scheme fallback. `App.tsx` wraps router with `<ThemeProvider>`. SettingsMenu in nav lets user toggle.
- **Shared components** — `components/BrandRow.tsx`, `components/SettingsMenu.tsx` (gear icon + iOS-style toggle popover), `components/PidThumb.tsx` (generative SVG P&ID thumbnail per seed).
- **New backend endpoint** — `GET /api/v1/jobs` in `webapp/routers/api_v1.py` returns `{jobs: [{id, name, pid_no, status, valve_count, created_at, owner_username}]}` for the current user (or all jobs for super_admin). Joins User for owner_username — no ORM relationship existed.
- **Dashboard rebuilt** — `routes/Dashboard.tsx` replaces placeholder with full ProjectsPage: stats strip, search + filter chips, sidebar OR grid OR list (layout persisted to localStorage `qong.dashboard.layout`), `ProjectCard`/`ProjectRow` components, empty state, loading state. Wired to `/api/v1/jobs`.
- **CreateProjectModal** — `dashboard/CreateProjectModal.tsx` with name/client/discipline + drag-drop PDF dropzone; uploads via existing `POST /api/v1/jobs` (one job per file, sequentially); ESC closes.
- **Login refreshed** — `routes/Login.tsx` rewritten to use bundle's `.login-screen`/`.login-brand`/`.login-card`/`.extract-viz`/`.airgap-chip` classes instead of inline styles. Keeps existing auth wiring (`useAuth().login()` POST `/login`). Variant A (Split) only; Variant B deferred.
- **Layout nav** — `routes/Layout.tsx` rebuilt to use bundle's `.app-nav`/`.breadcrumbs`/`.icon-btn`/`.nav-actions` classes; includes `<SettingsMenu />` so users can flip theme from any page.

**Result (if measurable):**
- TypeScript build: 0 errors. Bundle: 309 KB JS / 68 KB CSS (gzipped 94 KB JS / 12 KB CSS).
- Curl verification: `GET /api/v1/jobs` returns 200 with `{"jobs": []}` for admin (no jobs in dev DB); `POST /login` → 303; Vite proxy forwards `/api/v1/jobs` correctly.
- 4 of 7 designed surfaces remain placeholders: Studio (Phase 2), Datasheet drawer (Phase 2), Projects route (delegates to Dashboard), Login Variant B (Cinematic — Phase 2 maybe).

**Notes:**
- **Design bundle staged** at `design/qong-studio-v2/` (extracted from gzip tarball at `/tmp/qong-design-bundle/`). Source files: `project/{app.jsx,screens.jsx,studio.jsx,datasheet.jsx,app.css}` + `design-system/`. Keep this folder around — Phase 2 needs `studio.jsx` and `datasheet.jsx`.
- **lucide-react 1.16.0 → 1.17.0** — bumped to get modern icon names (`chevron-right`, `panel-left`, `git-branch`, `cpu`, `zap`, `arrow-up-right`). 1.17.0 is the actual latest on npm (3924 icons) despite the suspicious version number.
- **Vite binds to IPv6 only by default** (`::1`, not `127.0.0.1`). Curl tests must use `http://localhost:5173` (IPv6 resolver hits) or `http://[::1]:5173`. Bit me during smoke test.
- **One Job = one tile** in the Dashboard — no `projects` table added (user confirmed in scoping). When agency MVP needs multi-PID-per-project, that's a separate plan (FK migration, endpoint changes).
- **Body of CreateProjectModal uploads files sequentially**, not in parallel. Simpler error handling; can parallelize when we hit volume.
- **Owner_username via outer join** — Job model has no SQLAlchemy `relationship("User")` defined, so `job.user.username` would NameError. The dashboard endpoint does `db.query(Job, User.username).outerjoin(User)` instead. Worth adding a real relationship if more endpoints need it.
- **Project name maps to original_filename** with `.pdf` stripped; client maps to owner_username. When the projects-table refactor happens, both get proper fields.
- **Files modified:** `webapp/routers/api_v1.py` (+30 lines), `webapp/frontend/src/{design/global.css,design/studio.css (new),theme/ThemeContext.tsx (new),components/{BrandRow,SettingsMenu,PidThumb}.tsx (new),dashboard/{types.ts,ProjectCard,ProjectRow,CreateProjectModal}.tsx (new),routes/{Dashboard,Login,Layout}.tsx,App.tsx}`. Two files inflated (Login from inline-styles to design classes, Dashboard from 15 → 290 LOC); rest are net-new.

---

## [2026-05-28] #11 — Marketing landing page ported into React SPA (Plan B Phase 1 Task 6)

**Type:** feature
**Stage:** webapp
**Status:** shipped

**Why:** Plan B Phase 1 final task. The Home route was a placeholder; the team needed a full marketing-site composition in the SPA so sales/demo links (`/`) show the real brand. Also needed to prove the JSX design-system UI kit (in `design/QONG Design System/ui_kits/marketing-site/`) ports cleanly to TypeScript.

**What:** Created `webapp/frontend/src/marketing/` with 7 files: `Drive.tsx`, `Social.tsx`, `Hero.tsx`, `Sections.tsx` (About, Features, Problems, Process, CoreEngine, Advantages, Sectors, FAQ, CTAStrip), `Footer.tsx`, `MarketingNav.tsx`, `marketing.css`. Replaced `routes/Home.tsx` entirely. Added `/` to `FULL_BLEED_ROUTES` in `Layout.tsx` so the marketing page is edge-to-edge. Commit `41db788`.

**Result (if measurable):** tsc + vite build clean. Bundle size 283 KB JS / 18 KB CSS (grew ~18 KB from marketing components). "Beyond Plant", "Oil & Gas", "Instrument Index" present in the JS bundle.

**Notes:** Drive mockup animates via a `setInterval` — functional, not a real product. CTA buttons link to `/signin` or `mailto:hello@qongsystems.com`. Nav links for About/Careers/Contact do in-page anchor scroll only (not separate routes — those are post-Phase-1 surfaces).

---

## [2026-05-28] #10 — Deliverables subsystem shipped (Valve List / Instrument Index / Equipment List / Datasheet generators + per-customer templates)

**Type:** feature
**Stage:** webapp, export
**Status:** shipped

**Why:** Per `docs/decisions/01-qong-studio-mvp-design.md` Plan A. The MVP
customer experience hinges on four deliverables in per-EPC templates;
this subsystem is the production path for all four.

**What:** `webapp/deliverables/` package — Pydantic canonical schema
(v1.0.0), per-customer JSON template format, generator registry, six
concrete generators (Valve List CSV+XLSX, Instrument Index CSV+XLSX,
Equipment List XLSX, Datasheet XLSX with 11-section IDS structure) and
the `POST /api/v1/jobs/{id}/export/{type}/{format}` endpoint. Three
customer templates landed: default (matches production columns +
TNB-style Instrument Index), ronesans (sheet-name + font overrides),
muk (subsetted columns). Pipeline-side `canonical.json` writing is
intentionally out of scope for this plan — a follow-up plan will wire
the extraction pipeline to emit canonical.json next to valve_list.csv.

**Result:** End-to-end test passes: given a hand-crafted canonical.json
fixture, the endpoint returns valid CSV/XLSX in the expected template
(matching the customer reference files `parser.py:to_csv_dict`,
`TNB-26E009A001_Instrument index R0.pdf`, `23E065AJ01_ASV_IDS.xlsx`).
~56 unit tests + 5 E2E tests, all green.

**Notes:** The customer_template_slug "default" is the fallback; jobs
whose project sets no template still produce a usable deliverable.
Companion entry to #09 (ValveListCSVGenerator) — #10 covers the
remaining 5 generators + the API endpoint + the registry wiring.

---

## [2026-05-28] #09 — ValveListCSVGenerator: stdlib csv.writer, CRLF fixture, self-registers in REGISTRY

**Type:** feature
**Stage:** export
**Status:** shipped

**Why:** Plan `2026-05-27-deliverables-template-engine.md` Task 9 — first concrete deliverable generator to exercise the Generator/REGISTRY/TemplateLoader/field_resolver stack end-to-end. Needed to prove byte-exact output before XLSX variant is added.

**What:** New file `webapp/deliverables/valve_list.py` — `ValveListCSVGenerator(Generator)` filters entities to `entity_class == "valve"`, orders columns by `ColumnDef.order`, writes CRLF CSV via `csv.writer`, self-registers in `REGISTRY` at import time. Fixture `tests/unit/deliverables/fixtures/expected_valve_list_default.csv` (315 bytes, 3 CRLF lines) pinned via Python csv.writer for byte-exact comparison. `.gitattributes` added so git checks out the fixture with `eol=crlf` on all platforms.

**Result:** 4 pytest tests pass: byte-equality fixture, filter-to-valves-only (instrument/equipment rows excluded), trailing-space header preservation, class attrs. Commit `ac2cde8`.

**Notes:** `.gitattributes` `eol=crlf` rule is critical — without it a fresh clone on Linux/Mac would check out LF and the byte-equality test would fail. The `"8""-G-62151004-AC-PP"` double-double-quote is csv-module standard escaping; do not hand-edit that fixture.

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
