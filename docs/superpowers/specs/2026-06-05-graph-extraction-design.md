# P&ID Graph Extraction v0 — Design

**Status:** Draft → Approved 2026-06-05
**Track:** Experimental (`dt/main` branch, `experiments/digital_twin/` folder)
**Owner:** Lead + Claude Code
**Timeline:** 4 weeks (by 2026-07-03)
**Successor doc:** v0.5 will define formal isomorphism evaluation and broader-sheet labelling.

## 0. Context

Qong's existing pipeline extracts a **list** of valves/instruments/equipment per P&ID page (`canonical.json`). The digital-twin platform needs the **connectivity** between those entities — the process-pipe graph. This document specifies a 4-week v0 that ships an interactive graph in Qong Studio, served from a new `canonical_graph.json` artefact built on top of existing pipeline outputs.

This work lives on a separate branch family (`dt/*`) and folder (`experiments/digital_twin/`) inside the same repository as the team's production codebase. Rationale: team is ramping up on basics; lead races ahead with Claude Code; one PR hands off the result. See the "Experimental track" section of `CLAUDE.md` for branch/folder/memory conventions.

## 1. Goal & Success Criteria

**Goal:** extract a NetworkX graph from a single-page P&ID where nodes are entities from `canonical.json` (valves, instruments, equipment) and edges are process pipes, and render it as an interactive panel in Qong Studio.

**Scope locks:**
- Single page only (no cross-sheet stitching via OPC connectors)
- Process pipes only (no DCS signal lines, no interlock arrows)
- Read-only graph in Studio first; user corrections (add-edge) added in Week 4

**Success criteria:**
- **80% node recall** on 5 hand-curated test sheets (every entity in canonical.json that has a YOLO bbox shows up as a node)
- **60% edge recall** on those same sheets (every clearly-drawn process pipe shows up as an edge between the right two nodes)
- Graph renders in Studio in <2 seconds after job completes
- One JSON serialisation (`canonical_graph.json`) sits next to `canonical.json` in `job_outputs/{org_id}/{job_id}/`

Formal `networkx.is_isomorphic` evaluation is deferred to v0.5 (requires ground-truth labelling effort).

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                Existing pipeline (untouched)                        │
│  PDF → tiles → YOLO (bboxes+class) → OpenRouter (canonical.json)    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                NEW — Graph builder (experiments/digital_twin/)      │
│                                                                     │
│  Step C: Bbox→tag linker                                            │
│    └─ OCR each YOLO bbox crop → fuzzy-match into canonical.json     │
│       → produces {bbox, class, entity_id, tag}                      │
│                                                                     │
│  Step D: Line tracer (LineTracer protocol)                          │
│    ├─ OpenCVLineTracer (v0): binarize → mask bboxes → skeletonize   │
│    │  → find line segments via Hough or connected components        │
│    └─ CVCUDALineTracer (v1, deferred to DGX Spark)                  │
│                                                                     │
│  Step E: Edge resolver                                              │
│    └─ For each line segment, find 2 nearest bboxes within           │
│       proximity-threshold → create edge (node_A, node_B, segment)   │
│                                                                     │
│  Step F: Graph assembler                                            │
│    └─ Build NetworkX MultiGraph; serialise to canonical_graph.json  │
│                                                                     │
│  Step G: LLM fallback (graceful degradation)                        │
│    └─ If edges < 0.3 × nodes, call OpenRouter with tile+bboxes      │
│       → ask for edge list → merge with CV output                    │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│         NEW — Backend (added in Week 3, on port 9100)               │
│  GET  /api/v1/jobs/{id}/graph         → canonical_graph.json        │
│  POST /api/v1/jobs/{id}/graph/edges   → user-added edges            │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  NEW — Qong Studio panel (Week 4)                   │
│  Right-rail "Graph" toggle. Renders graph on Konva (reuses canvas). │
│  Click node → highlight bbox on tile. Click edge → highlight pipe.  │
└─────────────────────────────────────────────────────────────────────┘
```

The `LineTracer` protocol is the swap-point for the v1 sovereign-CV migration. When the DGX Spark hardware arrives and we ship a UNet-based pipe-segmentation model, a `CVCUDALineTracer` implementation drops in without touching graph-assembly, API, or UI code. See §4 for the protocol shape.

## 3. Data Model

`canonical_graph.json` shape (sits next to `canonical.json`):

```json
{
  "version": "0.1",
  "job_id": 42,
  "page": 1,
  "generated_at": "2026-06-05T11:23:45Z",
  "stats": {"nodes": 87, "edges": 64, "fallback_used": false},
  "nodes": [
    {
      "id": "n_001",
      "entity_id": "ent_abc123",
      "tag": "62-BF-151031",
      "class": "valve_bf",
      "bbox": [123, 456, 178, 511],
      "tile": "tile_1_1.png",
      "confidence": 0.87
    }
  ],
  "edges": [
    {
      "id": "e_001",
      "source": "n_001",
      "target": "n_042",
      "polyline": [[150, 480], [150, 600], [320, 600]],
      "tile": "tile_1_1.png",
      "method": "opencv",
      "confidence": 0.72
    }
  ],
  "floating_nodes": ["n_017"],
  "orphan_lines": [
    {"polyline": [[700, 100], [700, 200]], "tile": "tile_1_1.png", "reason": "no_bbox_within_proximity"}
  ]
}
```

**Why MultiGraph (NetworkX), not DiGraph:** process pipes don't carry direction information at this stage (flow direction is a v1 problem). Multiple parallel pipes between the same two pieces of equipment must be representable — that requires a MultiGraph.

**Coordinate system:** all bbox / polyline coordinates are in **page-pixel** space (the same space `canonical.json` and `Job.gpu_detections` use today). Tile-local coordinates are converted at ingest time inside `loader.py`. Studio's Konva layer reads page-pixel directly.

**`method` values:**
- `opencv` — primary CV tracer
- `llm_fallback` — emitted by the OpenRouter fallback
- `user_added` — created via POST endpoint from Studio's add-edge mode
- (`cvcuda` reserved for v1)

## 4. Component Layout

Inside `experiments/digital_twin/`:

```
experiments/digital_twin/
├── pyproject.toml                       (already scaffolded)
├── notebooks/
│   ├── 00-load-job.ipynb                load tiles + canonical.json + YOLO bboxes
│   ├── 01-bbox-ocr-linker.ipynb         step C exploration
│   ├── 02-line-tracing-opencv.ipynb     step D exploration (highest uncertainty)
│   ├── 03-edge-resolver.ipynb           step E
│   ├── 04-end-to-end.ipynb              stitch C+D+E+F into one run
│   └── 05-llm-fallback.ipynb            step G
├── src/dt/                              installable package via pyproject.toml
│   ├── __init__.py
│   ├── loader.py                        read tiles, canonical.json, gpu_detections
│   ├── linker.py                        step C
│   ├── tracer.py                        step D + LineTracer protocol
│   ├── resolver.py                      step E
│   ├── assembler.py                     step F (NetworkX build + JSON serialise)
│   ├── fallback.py                      step G (LLM)
│   └── pipeline.py                      orchestrates C→D→E→F→G
├── backend/                             FastAPI service, added Week 3 (port 9100)
│   ├── main.py
│   └── routes.py
├── tests/
│   ├── test_linker.py
│   ├── test_tracer.py
│   ├── test_resolver.py
│   └── fixtures/                        small synthetic tiles + canonical.json
├── data/                                gitignored; symlinks to ../../job_outputs/
└── docs/
    ├── notes.md                         experiment journal
    └── eval-v0.md                       5-sheet evaluation report (Week 4)
```

**Key interface — `tracer.py`:**

```python
from typing import Protocol, List
import numpy as np

class LineSegment(NamedTuple):
    polyline: List[Tuple[int, int]]   # page-pixel coords
    tile: str
    confidence: float

class LineTracer(Protocol):
    def trace(self, tile_png: bytes, bbox_mask: np.ndarray) -> List[LineSegment]: ...

class OpenCVLineTracer:                  # v0 implementation
    def __init__(self, *, min_length_px: int = 20, dilate_iters: int = 1): ...
    def trace(self, tile_png, bbox_mask): ...

# CVCUDALineTracer: stub class with NotImplementedError, replaced in v1.
```

This protocol is the **architectural seam** that makes the CV-CUDA migration cheap when DGX Spark lands.

## 5. API Surface

Two endpoints, added in Week 3 once notebooks stabilise. They live in the experimental backend (`experiments/digital_twin/backend/`) on port 9100. The team's `webapp/` is untouched. On handover, the endpoints move into `webapp/routers/graph.py`.

```
GET  /api/v1/jobs/{job_id}/graph
     → 200 canonical_graph.json (computed on first request, cached on disk)
     → 202 {"status": "computing", "eta_seconds": N}    first-touch case
     → 404 {"error": "no_canonical"}                    pipeline hasn't run yet
     → 409 {"error": "canonical_required", "action": "run_pipeline_first"}

POST /api/v1/jobs/{job_id}/graph/edges
     body: {"source": "n_001", "target": "n_042", "polyline": [[x,y],...]}
     → 201 {"id": "e_087", "method": "user_added"}
     → also writes a row into ModelCorrection table for future training data
     → 400 if source/target ids don't exist in current graph
```

**Auth:** uses the parent webapp's existing session cookie (Studio is loading the panel inside an already-authed page). The experimental backend trusts the cookie via a shared-secret middleware in Week 3; tighter SSO ties happen at handover.

## 6. Studio Panel (interaction sketch)

- Right-rail toggle: a new `Graph` button alongside `Properties` and `Datasheet` tabs.
- Graph renders on a **second Konva layer over the existing tile canvas** — same coordinate system, so clicking a node visually highlights its bbox on the underlying tile.
- Hover edge → highlight its polyline path in cyan over the tile.
- Click node → opens the existing `DatasheetDrawer`, pre-filtered to that entity. Reuses infrastructure from FEATURES #26.
- Footer chip: `87 nodes, 64 edges, 3 orphan lines — Add edge`. Clicking "Add edge" enters a 2-click mode (pick node A, pick node B) → POSTs to the corrections endpoint.
- Edges drawn with `method="llm_fallback"` get a distinct visual treatment (dashed yellow vs solid green for `opencv`) so engineers see at a glance which edges to trust.

Frontend changes ride on a dedicated `dt/feat-studio-panel` branch and merge into `dev` as one isolated PR at the end of Week 4 — separate from the algorithm code that stays inside `experiments/`.

## 7. Build Sequence — 4 weeks

| Week | Deliverable | Files | Risk |
|---|---|---|---|
| **1** (Jun 6-12) | Notebook 00 + 01 working on one real job. Bbox-OCR linker ≥70% match rate. | `notebooks/00-`, `01-`, `src/dt/loader.py`, `src/dt/linker.py`, `tests/test_linker.py` | OCR quality on small bbox crops |
| **2** (Jun 13-19) | Notebook 02 + 03 produce reasonable edge guesses on the same job. `OpenCVLineTracer` implemented. | `02-`, `03-`, `src/dt/tracer.py`, `src/dt/resolver.py`, `tests/test_tracer.py`, `tests/test_resolver.py` | Pixel-level line tracing tuning |
| **3** (Jun 20-26) | Notebook 04 end-to-end. FastAPI backend at port 9100 serialises `canonical_graph.json`. LLM fallback (notebook 05) wired. | `backend/`, `src/dt/assembler.py`, `src/dt/fallback.py`, `src/dt/pipeline.py` | Integration |
| **4** (Jun 27-Jul 3) | Studio panel with Konva graph layer; click-through to bbox; add-edge mode. 5-sheet evaluation report committed. | Studio changes on `dt/feat-studio-panel`; `experiments/digital_twin/docs/eval-v0.md` | Konva layer complexity |

**Hard gate at end of Week 2:** if `OpenCVLineTracer` edge recall is below 30% on the test job, Week 3 pivots — the **LLM fallback becomes the primary engine**, and the CV pipeline becomes the fallback. Same architecture, opposite primary. Decision recorded in `FEATURES.md [DT]`.

## 8. Testing & Evaluation

**Unit tests** (in `experiments/digital_twin/tests/`):

- `test_linker.py` — fixture: a tile with 3 known bboxes + `canonical.json` with 3 entities; assert all 3 link correctly.
- `test_tracer.py` — fixture: a synthetic black-on-white image with 2 rectangles connected by a line; assert tracer returns exactly 1 line segment with the correct endpoints.
- `test_resolver.py` — fixture: a list of bboxes + a list of line segments; assert correct edge assignment.

**5-sheet integration evaluation** (no formal isomorphism in v0):

- 5 real customer P&ID pages selected from existing `job_outputs/`.
- For each sheet: hand-count true nodes (`N_true`) and true edges (`E_true`).
- Compute `node_recall = nodes_found / N_true` and `edge_recall = edges_found / E_true`.
- Targets: 80% node recall, 60% edge recall (per §1).
- Output: markdown report at `experiments/digital_twin/docs/eval-v0.md`, committed at end of Week 4.

**v0.5 isomorphism eval** (after v0 ships): label 3 sheets manually as NetworkX JSON, run `networkx.is_isomorphic` with node-attr matching on `(class, tag-prefix)`. Target: 1 of 3 isomorphic.

## 9. Error Handling & Graceful Degradation

- **Per-step failure:** each step (C, D, E, F, G) returns a result object with a `confidence` and `warnings` list. The graph still gets built; failing edges go into `orphan_lines` instead of being dropped silently.
- **LLM fallback gate:** triggered only when `edges < 0.3 × nodes`. Fallback adds edges with `method="llm_fallback"` so the Studio panel can render them distinctly.
- **OCR returns empty/illegible:** node is still created, `tag` is `null`, `entity_id` is `null`. Studio shows it as a grey unlabelled node — still clickable for manual labelling later.
- **Job has no `canonical.json`:** API returns 409 `{"error": "canonical_required"}`. We never produce a partial graph from raw YOLO alone — the entity layer is non-negotiable.
- **Tile not found / corrupted:** the tile's contribution is skipped, surfaced as `warnings: ["tile_X_Y.png unreadable"]`. Other tiles still produce graph fragments.

## 10. Risks & Open Questions

| Risk | Mitigation |
|---|---|
| OCR on 50×50 px bbox crops is unreliable | Use EasyOCR for v0; if recall <50%, add a class-based prior (a `valve_bf` bbox almost always has a tag matching `XX-BF-XXXXXX`). |
| Line tracer is brittle on busy drawings (annotations, hatching, dashed lines) | LLM fallback covers this — it's the explicit safety net. Hard gate at end of Week 2 forces a re-prioritisation if classical CV underperforms. |
| 5-sheet evaluation is not statistically meaningful | True. v0 is a proof-of-life; broader eval (50 sheets) lands in v0.5 alongside ground-truth labelling. |
| YOLO mAP50 = 0.404 limits node ceiling | Documented limit. Improving the detector is FEATURES #28's separate track; graph extraction has to live with current bboxes. |
| Studio integration touches `webapp/frontend/` (team code) | Frontend work on a dedicated `dt/feat-studio-panel` branch; merges into `dev` as one isolated PR in Week 4. |
| Auth across two backends (port 8000 webapp + port 9100 dt) | Shared-secret middleware for Week 3; tightened to full session-share at handover. Documented as TODO in Week 3 deliverable. |

## 11. Handover plan (end of Week 4)

When v0 hits acceptance:

1. Merge `dt/feat-studio-panel` into `dev` (Studio panel only — frontend changes).
2. Move `experiments/digital_twin/src/dt/` into `webapp/graph/` on `dev`.
3. Move backend endpoints from `experiments/digital_twin/backend/routes.py` into `webapp/routers/graph.py`.
4. Add an entry to FEATURES.md (not `[DT]` tagged — this is the real thing now): `## NN — Graph extraction v0 in production`.
5. Move `canonical_graph.json` generation into `pipeline_runner.py` so it runs automatically post-pipeline.
6. Archive `experiments/digital_twin/` with a `MERGED.md` pointing at the merge commit; keep it for reference / future v1 sandbox.

At that point the team owns it; their basics will have caught up (target: by end of June they've worked through enough of the existing `webapp/` codebase to operate graph extraction).
