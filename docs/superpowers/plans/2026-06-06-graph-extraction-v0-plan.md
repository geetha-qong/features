# Graph Extraction v0 — Implementation Plan

**Spec:** [`docs/superpowers/specs/2026-06-05-graph-extraction-design.md`](../specs/2026-06-05-graph-extraction-design.md)
**Branch:** `dt/main` (experimental track — does not deploy)
**Folder:** `experiments/digital_twin/`
**Timeline:** 4 weeks (target end 2026-07-03)
**Engineer:** Lead with Claude Code

## How to use this plan

Each phase below maps to a tracked TaskCreate task when work begins. Steps within a phase are sequential unless flagged `(parallel-ok)`. Each step has a clear definition-of-done (DoD) so it's mergeable in isolation.

Hard gate at end of Week 2 (see Phase E.3) — if the OpenCV line tracer's edge recall is below 30% on the test job, swap the LLM fallback to the primary engine and the CV pipeline becomes the fallback. Same architecture, opposite primary.

## Phase A — Foundations (Week 1, Days 1-2)

**Goal:** notebook environment + data loader + one real job loaded end-to-end.

### A.1 — Set up package + venv
- Create `experiments/digital_twin/src/dt/__init__.py`
- `pip install -e experiments/digital_twin/` from repo root
- Verify `import dt` works in `experiments/digital_twin/notebooks/`
- **DoD:** `python -c "import dt; print(dt.__file__)"` succeeds

### A.2 — Loader (`src/dt/loader.py`)
Build the data-access layer. Returns one Python object per job with:
- tiles (list of `Path` + PIL.Image lazy-load)
- canonical entities (parsed from `canonical.json`)
- YOLO detections (parsed from `Job.gpu_detections` JSON in webapp DB)
- tile-grid metadata (rows, cols, original PDF size)

Reads from `../../job_outputs/{org_id}/{job_id}/` (or flat for jobs ≤39 per CLAUDE.md). Job DB access via the webapp's `SessionLocal` to avoid duplicating SQLAlchemy models.

Tests:
- `tests/test_loader.py` — happy-path fixture: 1 tile + 2 entities + 3 detections
- Edge case: missing canonical.json → returns `entities=[]`
- Edge case: missing detections → returns `detections=[]`

**DoD:** unit tests pass; notebook `notebooks/00-load-job.ipynb` displays tile images + canonical entity tags + detection bbox overlays as matplotlib plots, sourced from a real job (e.g. 41 or 9).

### A.3 — Symlink real job data into experiments/
- `mkdir -p experiments/digital_twin/data/jobs/`
- `ln -s ../../../../job_outputs/13/41 experiments/digital_twin/data/jobs/41`
- Symlinks gitignored (already in `.gitignore`)
- **DoD:** loader can read job 41 via the symlink path

## Phase B — Bbox → tag linker (Week 1, Days 3-5)

**Goal:** assign an OCR-derived tag string to each YOLO bbox, then fuzzy-match it to canonical entity tags. Without spatial info on canonical entities this gives us a stronger key than today's class-only matching.

### B.1 — OCR-on-crop module (`src/dt/linker.py`)
- `crop_bbox(tile_image, bbox) → PIL.Image`
- `ocr_crop(crop) → str | None` using EasyOCR (already in pyproject.toml)
- Tunable: padding around bbox, min confidence cut-off, character whitelist

Tests:
- `tests/test_linker.py::test_ocr_simple_tag` — fixture image with hand-drawn `"PV-101"` → returns `"PV-101"`
- `tests/test_linker.py::test_ocr_returns_none_on_empty_crop` — black/white crop with no text

**DoD:** unit tests pass; notebook `01-bbox-ocr-linker.ipynb` shows OCR'd tag overlay next to each detection bbox on a real tile.

### B.2 — Fuzzy match (`src/dt/linker.py:link_to_canonical`)
- Levenshtein distance between OCR'd tag and `canonical_entity.tag`
- Threshold: Lev ≤ 2 → match; ≤ 4 → "weak match" (returned with flag); > 4 → no match
- Class-prior fallback: if OCR fails, fall back to today's class-based matching (port from `webapp/routers/api_v1.py::_yolo_class_to_canonical`)

Tests:
- Exact match: OCR returns `"62-BV-11059"`, canonical has `"62-BV-11059"` → match
- Close match: OCR returns `"62-8V-11059"` (8 vs B confusion) → weak match
- Class fallback: OCR returns `""`, but detection class is `valve_bv` → class-based match

**DoD:** notebook `01-` shows per-bbox match outcomes (matched / weak / class-fallback / unmatched) with counts; combined match rate ≥70% on job 41.

## Phase C — Line tracer protocol + OpenCV implementation (Week 2)

**Goal:** for each tile image, return a list of `LineSegment` polylines representing process pipes between bboxes.

### C.1 — Tracer protocol (`src/dt/tracer.py`)
```python
class LineSegment(NamedTuple):
    polyline: List[Tuple[int, int]]   # page-pixel coords
    tile: str
    confidence: float

class LineTracer(Protocol):
    def trace(self, tile_png: bytes, bbox_mask: np.ndarray) -> List[LineSegment]: ...
```

**DoD:** type-check passes; one stub implementation `NoopLineTracer` returns `[]` for any input.

### C.2 — OpenCV implementation (`src/dt/tracer.py:OpenCVLineTracer`)

Pipeline per tile:
1. **Binarize** — adaptive threshold on grayscale (`cv2.adaptiveThreshold`)
2. **Mask out bboxes** — fill bbox interiors with background so symbols don't trace as lines
3. **Skeleton** — `skimage.morphology.skeletonize` to get 1-pixel-wide line representation
4. **Connected components** — `cv2.connectedComponentsWithStats` to group pixels into lines
5. **Filter** — drop components with `min_length_px < 20` (text, hatching noise)
6. **Polyline extraction** — walk each component to produce ordered point sequences (RDP/Douglas-Peucker simplification with epsilon=2)

Tests (`tests/test_tracer.py`):
- Synthetic fixture: black-on-white image with 2 rectangles + 1 line connecting them → returns 1 segment with endpoints near both rects
- Empty input → `[]`
- All-bbox input (no lines) → `[]`

**DoD:** tests pass; notebook `02-line-tracing-opencv.ipynb` overlays traced segments on a real tile; visual inspection of job 41 tile_p0_r0_c0.png shows reasonable line coverage (≥50% of obvious pipes traced).

## Phase D — Edge resolver + graph assembler (Week 3, Days 1-3)

**Goal:** turn line segments + linked bboxes into a `NetworkX.MultiGraph`.

### D.1 — Edge resolver (`src/dt/resolver.py:resolve_edges`)

For each `LineSegment` (polyline endpoints E1, E2):
- Find the two nearest bboxes (one to E1, one to E2) within proximity threshold (e.g. 30px in page coords)
- If both found within threshold → emit `Edge(source=bbox_A.entity_id, target=bbox_B.entity_id, polyline)`
- If only one → `orphan_lines` list
- If none → discard

Tests (`tests/test_resolver.py`):
- 2 bboxes + 1 line between them → 1 edge
- 2 bboxes + line too far from either → 0 edges, 1 orphan
- 3 bboxes + 1 line touching 2 of them → 1 edge between correct pair

**DoD:** tests pass; resolver runs on real job 41 line segments + bboxes.

### D.2 — Graph assembler (`src/dt/assembler.py`)

`assemble(nodes, edges) → JobGraph`
- Build `networkx.MultiGraph()`
- Add nodes with attributes from linker output (entity_id, tag, class, bbox)
- Add edges with attributes (polyline, method=`opencv`, confidence)
- Serialize to `canonical_graph.json` matching the spec's data model exactly (§3)

Tests (`tests/test_assembler.py`):
- 2 nodes + 1 edge → graph has 2 nodes, 1 edge, correct attrs
- JSON round-trip: `assemble → to_json → from_json` is identity

**DoD:** tests pass; notebook `03-edge-resolver.ipynb` shows the assembled graph rendered with `networkx.draw_networkx` on top of the tile image. Job 41 yields ≥1 edge (the pipe between the 2 known valve_bv entities, if a pipe exists between them on the sheet).

## Phase E — End-to-end pipeline + LLM fallback + hard gate (Week 3, Days 4-5)

### E.1 — Pipeline orchestrator (`src/dt/pipeline.py`)
- `extract_graph(job_id: int) → JobGraph`
- Orchestrates C → D → E → F: loader → linker → tracer → resolver → assembler
- Returns the assembled `JobGraph` and writes `canonical_graph.json` to job dir

**DoD:** `notebooks/04-end-to-end.ipynb` runs the full pipeline on job 41 in <60 seconds and produces a `canonical_graph.json` file alongside `canonical.json`.

### E.2 — LLM fallback (`src/dt/fallback.py`)

Trigger when `len(edges) < 0.3 * len(nodes)`. Send tile + bboxes to OpenRouter with a structured prompt:
> "Given this tile image and these labeled bboxes, list every process pipe connection as JSON pairs of bbox IDs."

Merge LLM-emitted edges with CV edges; mark `method="llm_fallback"`.

Tests (`tests/test_fallback.py`):
- Stub the OpenRouter client to return a fixed edge list; assert merged graph contains both CV + LLM edges
- LLM returns malformed JSON → handled gracefully (no edges added, warning logged)

**DoD:** notebook `05-llm-fallback.ipynb` triggers the fallback on a synthetic edge-sparse case and shows yellow-dashed edges in the rendered graph.

### E.3 — Hard gate (Week 2 end)

Run the 5-sheet evaluation on hand-curated test sheets. If `OpenCVLineTracer` edge recall < 30%:
- Decision: pivot E.2's LLM fallback to **primary** engine
- Record decision in FEATURES.md with `[DT]` prefix and rationale
- Otherwise: continue with CV as primary

**DoD:** decision recorded in FEATURES.md; the file `experiments/digital_twin/docs/week-2-gate-decision.md` captures the recall numbers and the chosen path.

## Phase F — Backend service (Week 4, Days 1-2)

### F.1 — FastAPI backend (`experiments/digital_twin/backend/`)
- New service on port 9100, separate from the team's webapp
- `GET /api/v1/jobs/{id}/graph` returns `canonical_graph.json`
- `POST /api/v1/jobs/{id}/graph/edges` records user-added edges (writes to `ModelCorrection` table via the webapp's DB)
- Shared-secret middleware for auth (Studio sends a cookie + a token header)
- `docker-compose.yml` in the experimental folder, port 9100

Tests (`tests/test_backend.py`):
- 200 with canonical_graph.json (after pipeline runs)
- 404 with `{"error": "no_canonical"}` when pipeline hasn't run
- 409 with `{"error": "canonical_required"}` when canonical.json present but graph never computed
- POST creates a `user_added` edge

**DoD:** local `docker compose up` in `experiments/digital_twin/` brings up the backend, accessible at `http://localhost:9100/api/v1/jobs/41/graph`.

## Phase G — Studio panel (Week 4, Days 3-5)

**Goal:** interactive graph layer in Qong Studio canvas. Frontend work on a separate `dt/feat-studio-panel` branch so it can merge into `dev` as one isolated PR at handover.

### G.1 — Type definitions
- `webapp/frontend/src/studio/types.ts` — add `GraphNode`, `GraphEdge`, `JobGraph` interfaces matching the backend response
- `webapp/frontend/src/studio/api.ts` — `getJobGraph(jobId)` returning `JobGraph`

**DoD:** TypeScript compiles cleanly via `npx tsc --noEmit`.

### G.2 — Graph layer (`webapp/frontend/src/studio/GraphLayer.tsx`)

New SVG layer rendered above the tile canvas, in the same coordinate system. Reuses `PidCanvas`'s `naturalDimensions` viewBox.

- Render nodes as small circles at entity bbox centers
- Render edges as polyline paths (different stroke per `method`: opencv=solid green, llm_fallback=dashed yellow, user_added=solid cyan)
- Hover edge → highlight + tooltip showing tag pair
- Click node → call existing `onSelect(entity_id)` (reuses the post-D1.5 wiring)

Tests (`webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx`):
- Renders N nodes for N graph nodes
- Renders M paths for M edges with correct colors
- Click node fires `onSelect` with right entity_id

**DoD:** vitest passes; visual check in Studio shows the graph layer alongside detection bboxes.

### G.3 — Footer chip + add-edge mode

In `Studio.tsx`:
- Right-rail toggle: "Graph" button
- Footer chip: `87 nodes, 64 edges, 3 orphan lines — Add edge`
- Add-edge mode: 2 clicks (pick node A, pick node B) → POST `/edges` → optimistic insert

**DoD:** add-edge flow works end-to-end on dev; new edges persist (DB row + reload shows them).

## Phase H — Evaluation + handover (Week 4, Day 5)

### H.1 — 5-sheet evaluation
- Hand-pick 5 P&IDs from existing customer jobs
- For each: hand-count true nodes (`N_true`) and edges (`E_true`)
- Compute `node_recall = nodes_found / N_true`, `edge_recall = edges_found / E_true`
- Target: 80% node recall, 60% edge recall
- Output: `experiments/digital_twin/docs/eval-v0.md` with markdown table

**DoD:** eval doc committed; numbers meet targets (or hard-gate triggered per E.3).

### H.2 — Handover PR
- Merge `dt/feat-studio-panel` → `dev` (frontend only)
- Move `src/dt/` → `webapp/graph/` on a separate commit
- Move backend routes from `experiments/digital_twin/backend/routes.py` → `webapp/routers/graph.py`
- Add FEATURES.md entry **without** `[DT]` prefix — this is production now
- Wire graph generation into `webapp/pipeline_runner.py` so `canonical_graph.json` is produced post-pipeline automatically
- Archive `experiments/digital_twin/` with a `MERGED.md` pointing at the merge commit

**DoD:** dev.qongsystems.com renders the graph panel for any new job. Team owns the codebase.

## Risk register (mirror of spec §10)

| Risk | When it matters | Mitigation |
|---|---|---|
| OCR on small bbox crops unreliable | Phase B | Class-prior fallback in B.2; weak-match threshold tunable |
| Line tracer brittle on busy drawings | Phase C+E | LLM fallback is the safety net; hard gate at E.3 |
| 5-sheet eval not statistically meaningful | Phase H | Documented as v0 proof-of-life; v0.5 does 50-sheet eval |
| YOLO mAP50=0.83 (v1-10) still limits node ceiling | Phase D | Accepted; better detection is a separate retraining track (FEATURES #30) |
| Studio integration touches team's frontend | Phase G | Done on `dt/feat-studio-panel` branch; merges as one isolated PR |
| Auth across two backends | Phase F | Shared-secret middleware for v0; SSO-tied at handover |

## Out of scope for v0

- Multi-page graphs / cross-sheet OPC connector stitching → v1
- DCS signal lines / interlock arrows / instrument loop tracing → v1
- Directed edges (flow direction) → v0.5 (now feasible since v1-10 detects arrows)
- Formal `networkx.is_isomorphic` evaluation → v0.5 (needs hand-labeled ground truth first)
- CV-CUDA backend → v1 (drops in via the LineTracer protocol when DGX Spark arrives)
