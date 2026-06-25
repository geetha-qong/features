# Graph Extraction → DB + Annotation Finishing — Design

**Status:** Approved 2026-06-13
**Track:** Production (`dev` branch) — supersedes the experimental `dt/main` approach in `2026-06-05-graph-extraction-design.md` §0/§4 (we build directly in production's handover destination)
**Owner:** Lead + Claude Code
**Predecessor specs:** `2026-06-05-graph-extraction-design.md` (algorithm + data model — still authoritative for §3 data model and §8 testing), `2026-06-10-qong-studio-marking-design.md` (annotation system that ships the edit-layer tables)

## 0. Context & decisions

The annotation/marking system (FEATURES #38, #39) is live on `dev`. It already shipped the **edit-layer** tables `user_annotations` and `graph_corrections` — the latter with `source ∈ {opencv, llm_fallback, user}` already enumerated, anticipating an auto-extractor that did not yet exist. This spec builds that extractor, stores its output, renders it in Studio, and finishes three annotation-polish items.

Decisions taken at brainstorm (2026-06-13):

1. **Track:** build directly on `dev` (production), not the experimental `dt/main`. The old plan's experimental detour + handover PR is collapsed — code lands in its eventual home (`webapp/graph/`, `webapp/routers/graph.py`) from the start.
2. **Line-detection engine:** hybrid — `OpenCVLineTracer` primary, OpenRouter vision **fallback** when edge density is low. Built together from day one (no formal Week-2 hard-gate ceremony; revisit only if the real-job spot check is poor).
3. **Graph storage:** file-first + DB read-index, mirroring the `canonical.json → canonical_entities` pattern exactly.
4. **Annotation finishing:** all three of — real-hotkeys-in-palette, persist Apply, E2E verification.

## 1. Goals & success criteria

- Annotation flow verified end-to-end (mark / confirm / reject / draw-edge / delete / custom shortcut → persist + reload + training-export pick-up).
- "Applied" state survives reload (backed by DB).
- `canonical_graph.json` produced automatically post-pipeline for every new job, indexed into DB.
- Unified graph (auto edges + user edits) served at `GET /api/v1/jobs/{id}/graph` and rendered as a toggleable Studio layer.
- Spec §1 recall targets (from predecessor): **80% node recall, 60% edge recall** spot-checked on a real sheet. Full 5-sheet eval doc is a follow-up, not a merge blocker.

**Scope locks (v0):** single page, process-pipes only, undirected `networkx.MultiGraph`. Deferred: flow-direction edges (arrows are detected by v1-10 but not wired), cross-sheet OPC stitching, signal/interlock line types (the `graph_corrections` schema already supports them for *manual* entry).

## 2. Stream 1 — Annotation finishing

### 1a. Real hotkeys in the palette
`PalettePanel` rows show static design-time key hints. Read live bindings from the existing `useShortcuts()` hook (fetches `/api/v1/users/me/shortcuts`, FEATURES #38) and render the user's actual key per action, falling back to the DEFAULT keymap when uncustomised. Frontend-only.

### 1b. Persist "Apply"
"Applied · N" is currently UI-only (`appliedBySheet` state). There is no `sheets` table, so add:

```
sheet_apply_state(id, job_id FK, sheet_number, applied_at timestamptz, applied_by FK users)
  UNIQUE(job_id, sheet_number)
```

Created via `webapp/database.py:run_migrations()` (no Alembic; follow the table-creation path, not the `new_columns` append since this is a new table — use `Base.metadata.create_all` coverage + an existence-probe log).

- `POST /api/v1/jobs/{id}/sheets/{n}/apply` → upsert row (`applied_at = now`, `applied_by = current user`). `DELETE` clears it (re-arm).
- Job detail payload (or a dedicated `GET /api/v1/jobs/{id}/sheets/applied`) returns `{sheet_number: applied_at}` so Studio seeds `appliedBySheet` on load.

Datetime: `utc_iso()` on the wire (CLAUDE.md convention).

### 1c. E2E verification
Playwright on a real job (47/46/48): mark a symbol, confirm an existing detection, reject one, draw an edge, delete a user mark, exercise a custom shortcut. Assert each persists (DB row + reload) and that `export_annotations_for_yolo.py` + `export_graph_for_training.py` consume them. Close browser when done.

## 3. Stream 2 — Line detection (`webapp/graph/` package)

Pure package, no web/DB imports — unit-testable in isolation. Modules:

| Module | Responsibility |
|---|---|
| `loader.py` | Per-job object: page-full image path, tile-grid metadata, canonical entities (`canonical.json`), YOLO bboxes (`Job.gpu_detections`). Tile geometry reuses the 3×3 / 20%-overlap constants — **must stay in sync** with `pdf_to_tiles.py` and `PidCanvas.computeTileOffsets` (FEATURES #38 gotcha). |
| `linker.py` | `crop_bbox` → `rapidocr` OCR → `rapidfuzz` fuzzy-match to canonical tags (Lev ≤2 match, ≤4 weak, >4 none). Class-prior fallback (port `_yolo_class_to_canonical`) when OCR empty. |
| `tracer.py` | `LineSegment` NamedTuple + `LineTracer` Protocol + `OpenCVLineTracer`: adaptive binarize → mask bbox interiors → `skimage.morphology.skeletonize` → `cv2.connectedComponentsWithStats` → drop `<20px` → RDP simplify (ε=2). `NoopLineTracer` stub returns `[]`. |
| `resolver.py` | Each segment's 2 endpoints → 2 nearest bboxes within proximity (~30px page-coords) → `Edge(source, target, polyline)`; one match → `orphan_lines`; none → discard. |
| `fallback.py` | Gate `len(edges) < 0.3 * len(nodes)` → OpenRouter vision (reuse `extractor` client) with structured prompt for bbox-id pairs → merge as `method="llm_fallback"`. Malformed JSON handled gracefully. |
| `assembler.py` | Build `networkx.MultiGraph`; serialise to `canonical_graph.json` matching predecessor spec §3 exactly. JSON round-trip is identity. |
| `pipeline.py` | `extract_graph(job_id) → JobGraph`; orchestrates loader→linker→tracer→resolver→assembler→fallback; writes the file. |

**Deps added to `requirements.txt`:** `opencv-python-headless`, `scikit-image`, `networkx`. (`rapidocr-onnxruntime`, `rapidfuzz` already present.)

**Coordinate system:** page-pixel throughout (matches `Job.gpu_detections` + full-page canvas → no Studio translation).

Tests (synthetic fixtures, predecessor §8): `test_linker` (3 bboxes link), `test_tracer` (2 rects + 1 line → 1 segment; empty → []), `test_resolver` (correct edge assignment), `test_assembler` (round-trip identity), `test_fallback` (stubbed client merge + malformed-JSON safety).

## 4. Stream 3 — Storage, API, Studio, wiring

### Data model (parallel to canonical_entities)

```
canonical.json        → canonical_entities (read-index)  + entity_overrides   (edits)
canonical_graph.json  → graph_nodes / graph_edges (NEW)   + graph_corrections (edits, exists)
```

**`graph_nodes`** (read-index): `id, job_id FK, node_id, entity_id, tag, node_class, bbox JSON, confidence, sheet_number, created_at, updated_at`; UNIQUE `(job_id, node_id)`.

**`graph_edges`** (read-index): `id, job_id FK, edge_id, source_node, target_node, method, confidence, polyline JSON, tile, sheet_number, created_at, updated_at`; UNIQUE `(job_id, edge_id)`; index `(job_id)`.

Never edited through these tables — they reflect what the extractor emitted. `graph_corrections` remains the user-edit store.

### Sync + backfill
- `webapp/graph/graph_db_index.py:sync_graph_to_db(graph, db)` — upsert nodes+edges; mirrors `canonical_db_index.sync_canonical_to_db`. Idempotent.
- `webapp/scripts/index_graph_to_db.py` — backfill for legacy jobs from on-disk `canonical_graph.json`. Mirrors `index_canonical_to_db.py` (`--from-db|--dry-run|--job-id`).

### Pipeline wiring (`pipeline_runner.py`)
Immediately after the existing `write_canonical_for_job` + `sync_canonical_to_db` block:
```python
try:
    from webapp.graph.pipeline import extract_graph
    from webapp.graph.graph_db_index import sync_graph_to_db
    graph = extract_graph(job_id)
    sync_graph_to_db(graph, db)
except Exception as _g_err:
    print(f"[graph-extract] job {job_id}: {_g_err}", file=sys.stderr)
```
**Non-fatal** — graph failure logs but never rolls back job "done" (same contract as canonical sync).

### API — `webapp/routers/graph.py`
- `GET /api/v1/jobs/{id}/graph` → reads `canonical_graph.json`, overlays `graph_corrections` (apply user_added / user_confirmed / drop user_rejected), returns unified graph. `404 {"error":"no_canonical"}`, `409 {"error":"canonical_required"}` per predecessor §5. Cookie-authed.
- Add-edge already exists via #38's `POST /api/v1/jobs/{id}/edges` (writes `graph_corrections`). No new write endpoint needed.

Watch the **duplicate-route shadow** and **204 quirk** gotchas (CLAUDE.md). Register in `webapp/routers/`, not `main.py`.

### Studio — `GraphLayer.tsx`
SVG layer over the full-page canvas, reusing `PidCanvas` `naturalDimensions` viewBox (same page-pixel space). Nodes = circles at bbox centers; edges = polylines colored by `method` (opencv green solid / llm_fallback yellow dashed / user cyan solid). Right-rail "Graph" toggle; footer chip `N nodes · M edges · K orphans`. Click node → existing `onSelect(entity_id)`. `api.ts:getJobGraph(jobId)` + `types.ts` GraphNode/GraphEdge/JobGraph. Tests: renders N nodes / M edges / correct colors / click fires onSelect.

## 5. Sequencing

Three mergeable commits, each green (tsc + vitest + pytest) before the next:

1. **Stream 1** — annotation finishing (fastest; gives a clean E2E baseline).
2. **Stream 2** — `webapp/graph/` package + unit tests (validated in isolation, no wiring).
3. **Stream 3** — DB tables + sync + backfill + API + Studio layer + pipeline wiring; then real-job run on 47/46/48 + node/edge-recall spot check.

## 6. Error handling (predecessor §9, unchanged)
Per-step results carry `confidence` + `warnings`; failing edges → `orphan_lines` not silent drops. OCR-empty node still created (`tag=null`). No `canonical.json` → 409. Corrupt tile → skipped + warned, other tiles still contribute.

## 7. Risks
| Risk | Mitigation |
|---|---|
| OpenCV tracing brittle on busy drawings | LLM fallback is the net; spot-check gates merge of Stream 3 |
| OCR on small crops unreliable | class-prior fallback; weak-match flag |
| Tile geometry drift between Python + TS | both ends documented; change together in one PR |
| YOLO mAP50≈0.83 caps node ceiling | accepted; detector retrain is a separate track |
| Heavy deps (cv2/skimage) bloat image | `opencv-python-headless` (no GUI libs); shared by web + cpu-worker via one Dockerfile |

## 8. Out of scope (→ later)
Directed/flow-direction edges (v0.5), cross-sheet stitching (v1), signal/interlock auto-tracing (v1), formal `networkx.is_isomorphic` eval (v0.5), CV-CUDA backend (v1, drops in via `LineTracer` protocol).
