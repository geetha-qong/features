# Graph Directions — design & contract (2026-06-17)

**Goal (today):** make process-graph edges **directed** — store and render flow
direction for nodes (valves/instruments/equipment) connected by edges. Two
sources of direction, converging on one directed-edge store:

1. **Model path (best-effort):** use the v1-11 detector's `arrow_*` (flow
   direction) and `connector_in/out` (start/end) detections — currently SKIPPED
   by `webapp/graph/pipeline.py` + treated undirected by `assembler.py` — to
   orient auto-extracted edges.
2. **User path (reliable, training data):** user-drawn edges are already
   `source_entity_id → target_entity_id` (directed by click order). Make that
   direction **visible** (arrowheads) and confirm it persists + flows to the
   training export (`webapp/scripts/export_graph_for_training.py`). User
   corrections are the self-learning signal.

## What already exists (do NOT rebuild)

- `webapp/graph/{loader,linker,tracer,resolver,assembler,fallback,pipeline,graph_db_index}.py` — CV+LLM extraction → `canonical_graph.json` (job 1: 96 nodes/83 edges live on dev).
- `GET /api/v1/jobs/{id}/graph` (`webapp/routers/graph.py`) merges canonical_graph.json + user edges.
- `GET/POST/PATCH/DELETE /api/v1/jobs/{id}/edges` (`webapp/routers/edges.py`), `GraphCorrection` + `GraphNode` tables (`webapp/models.py`).
- Frontend `GraphLayer.tsx` (renders nodes + edges, colored by method), `showGraph` toggle + footer chip in `Studio.tsx`, draw-edge mode + `EdgeMetadataDrawer` + `useEdges` (FEATURES #38), `GraphLayer.test.tsx` (5 tests).
- Training export `webapp/scripts/export_graph_for_training.py` (+ test).

## Contract: the `directed` field

A graph edge gains an explicit direction flag. **`source` is upstream/from,
`target` is downstream/to** (already true for user edges).

- **Backend response** (`graph.py` GraphEdge dict + `edges.py` EdgeRow):
  add `directed: bool`.
  - User edges: `directed = true` (the user asserted source→target).
  - Auto edges: `directed = true` iff an arrow oriented it; else `false`
    (undirected, awaiting user confirmation).
- **`canonical_graph.json` edges:** add `"directed": bool`. Back-compat: a
  missing key reads as `false` (legacy graphs render as today, undirected).
- **DB:** `GraphCorrection` — add nullable `directed` column (default true for
  user edges) via the `run_migrations()` `new_columns` pattern (NO Alembic).
- **Orientation (model path), `webapp/graph`:** for each traced edge, find
  `arrow_*` detections whose centroid lies within a small distance of the edge
  polyline; if found, orient source→target by the arrow vector and set
  `directed=true`. `connector_in`→source side, `connector_out`→target side. No
  arrow nearby → leave undirected. Keep it best-effort and well-tested; do not
  regress node/edge counts.

## Frontend: render direction

`GraphLayer.tsx`:
- Define one SVG `<marker>` arrowhead per method color (reuse `METHOD_STYLE`),
  in a `<defs>` block; apply `markerEnd` to edges where `directed === true`.
- Undirected edges render exactly as today (no marker).
- Add a `directed?: boolean` to the `GraphEdge` type (`types.ts`); user edges
  surfaced through the graph carry `directed=true`.
- Tests (`GraphLayer.test.tsx`): a directed edge renders with `marker-end`; an
  undirected edge renders without; arrowhead color matches method.

## User path: direction is editable

- draw-edge already sets source→target; ensure the created edge surfaces
  `directed=true` and renders an arrowhead immediately (optimistic insert).
- `EdgeMetadataDrawer`: it already captures `relation_type`/`line_type`; if cheap,
  add a "flip direction" affordance (swap source/target). Stretch — not required
  for DoD.

## Definition of Done

- Auto graphs show arrowheads on arrow-oriented edges; user-drawn edges always
  show an arrowhead; undirected legacy edges unchanged.
- `directed` persists (DB + canonical_graph.json) and appears in the training
  export.
- Backend + frontend tests green; security audit of the edge endpoints clean;
  verified on dev (graph renders with directions; add-edge persists with
  direction; reload shows it).

## Roles (multi-agent)

- **Backend impl:** orientation in `webapp/graph` + `directed` in
  `graph.py`/`edges.py`/`models.py` + migration. Files: `webapp/graph/*.py`,
  `webapp/routers/graph.py`, `webapp/routers/edges.py`, `webapp/models.py`,
  `webapp/database.py`.
- **Frontend impl:** arrowheads + `directed` type + tests. Files:
  `webapp/frontend/src/studio/GraphLayer.tsx`, `types.ts`,
  `__tests__/GraphLayer.test.tsx` (+ minimal `Studio.tsx`/`PidCanvas.tsx` wiring
  if needed for `directed` passthrough).
- **Test:** backend orientation + edge `directed` persistence + export tests.
- **Security audit:** `edges.py` create/patch/delete (auth, ownership, input
  validation, the new `directed` input) + graph.py.

Disjoint file sets ⇒ backend and frontend run in parallel.
