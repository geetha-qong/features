# Graph Drawing UX — draw.io-style connections — Design

**Date:** 2026-06-30
**Status:** Approved (brainstorm), pending implementation plan
**Branch base:** `dev` (branch `feat/graph-drawing-ux`). Independent of the
queued `#138` (OCR gate) and `#139` (tag-override merge) branches — touches
different files. Builds on `#135` (type-B adopt flow) and `#137` (node hit
target), both already on dev.

## Problem (root-caused on dev, job 38)

The team is hand-correcting job 38's graph (91 nodes, 67 still floating) and
hits three blockers when connecting nodes in draw-edge mode:

1. **Nodes don't auto-connect.** `PidCanvas.nodeAtPoint()` (PidCanvas.tsx:805)
   snaps a click to a node **only if the click lands exactly inside the node's
   bbox** — no proximity. Click *near* a node → the endpoint becomes a
   `freepoint:x,y` (a floating, unconnected point), not a connection. Worse, the
   function **skips type-B nodes** (`if (!n.entity_id ...) continue`), so the 33
   unadopted nodes on job 38 cannot be edge endpoints at all.
2. **No draw.io-style connectors.** There are no connection points/ports. The
   only way to connect is the 2-click flow (click source node, click target
   node); nothing reveals where/how to start a connection.
3. **Can't draw over existing lines.** Rendered edges carry click handlers for
   selection; in draw-edge mode they intercept the click before it reaches the
   node/canvas underneath, so an endpoint can't be placed on top of a line.

## Goal

A fluid, draw.io-like connection experience: hover a node → connection anchors
appear → press-and-drag → the target node highlights → release snaps the edge to
it. Works for instruments, valves, equipment, **and type-B nodes** (auto-adopting
them on connect). Existing lines never block drawing. The result is correct
node-to-node topology (the graph-isomorphism metric's currency).

## Design decisions (from brainstorm)

1. **Interaction model:** full draw.io ports — hover reveals anchors; press+drag
   from the node (or an anchor) → rubber-band line → target node highlights →
   release snaps and connects.
2. **Type-B on connect:** **auto-adopt** — dragging an edge to/from an unadopted
   type-B node adopts it first (the `#135` flow, class from its YOLO label),
   then stores the edge entity→entity. One gesture = adopt + connect.
3. **Edge storage:** **node-to-node only** (`GraphCorrection(source_entity_id,
   target_entity_id)` — existing model, NO schema change). Anchors are visual
   grab/release affordances; the exact port is NOT persisted. This is all the
   graph-isomorphism metric needs (topology).
4. **Draw-over-lines:** in draw-edge mode, rendered edges become
   `pointer-events: none` so clicks/drags pass through to nodes/canvas.

## Architecture

Four cooperating pieces, all in the existing Studio canvas stack. No new backend
endpoints — reuse `createAnnotation` (adopt) + the existing `onEdgeDrawn` →
`POST /graph/edges` path.

### 1. Connection anchors on nodes — `GraphLayer.tsx`

- On node hover (mouseenter/leave per node `<g>`, tracked by `hoveredNodeId`
  state), render small anchor handles at the node's 4 cardinal points (N/E/S/W of
  the bbox), plus keep the whole node body as a connect-initiation target. Anchors
  are visual only (they do not change stored data).
- Anchors are sized in screen-constant units like the `#137` hit target
  (`sw`-relative) so they're usable on large drawings; hidden unless the node is
  hovered (or a drag is in progress) to avoid clutter on dense P&IDs.
- Anchors render for ALL node kinds incl. type-B (amber) nodes.

### 2. Drag-to-connect interaction — `PidCanvas.tsx`

Add a press-drag-release flow as the PRIMARY gesture. The existing 2-click flow
(click source, click target) is KEPT working and inherits the same improvements
(proximity snapping §3, type-B endpoints, auto-adopt §4) — both paths funnel
through one shared "resolve endpoint → adopt if type-B → onEdgeDrawn" routine, so
they never diverge:

- **mousedown** on a node/anchor in draw-edge mode → begin a drag:
  `edgeDraft = { sourceEntityId|sourceNodeId, sourcePoint, cursorPoint }`.
- **mousemove** → update `cursorPoint`; run proximity hit-test (see §3) to
  highlight the node currently under/near the cursor as the snap target.
- **mouseup** → if over/near a valid target node distinct from the source,
  resolve both endpoints to entity_ids (auto-adopting type-B endpoints, §4) and
  call `onEdgeDrawn(sourceEntityId, targetEntityId, normPoly, activeLineType)`.
  Otherwise cancel the draft (no `freepoint` edges from a drag — a drag that
  doesn't land on a node is a no-op, not a floating endpoint).
- **Escape** cancels an in-flight drag (existing handler).

### 3. Proximity snapping + type-B endpoints — `PidCanvas.nodeAtPoint()`

- Add a snap radius: when no node's bbox contains the point, return the **nearest
  node whose center is within `SNAP_RADIUS_PX`** (screen-constant, `sw`-relative),
  else null. Bbox-contains still wins when present.
- **Stop skipping type-B nodes:** `nodeAtPoint` returns a result for nodes without
  an `entity_id` too, carrying the node id (`n_xxx`) so the caller can auto-adopt.
  Return shape gains an optional flag/id distinguishing "entity node" (has
  entity_id) from "type-B node" (needs adoption).

### 4. Auto-adopt-on-connect — `PidCanvas` + `Studio.tsx`

- When an endpoint resolves to a type-B node (no entity_id), the connect handler
  first adopts it: reuse the existing `Studio.adoptNode(node)` logic (which calls
  `createAnnotation(...)` and returns a row with `row.entity_id`, class from the
  YOLO label, server-side claim resolution per `#135`). Capture the returned
  `entity_id` and use it as the edge endpoint.
- Adopt is awaited BEFORE `onEdgeDrawn` so the edge always references real
  entity_ids. If BOTH endpoints are type-B, adopt both, then draw.
- Surface adoption via the existing toast; on adopt failure, abort the edge
  (don't store a dangling edge) and toast the error.

### 5. Draw-over-lines — `GraphLayer.tsx` edge rendering

- Edges (auto + user) get `pointer-events: none` whenever `mode === "draw-edge"`
  (a prop already available to GraphLayer / its edge elements). In select mode
  they keep `pointer-events: auto` for edge selection/rejection. Lines visually
  crossing is unaffected; they simply no longer intercept draw clicks.

## Data flow

```
hover node → anchors appear (GraphLayer, visual only)
mousedown on node/anchor → edgeDraft{source}
mousemove → cursorPoint + snap-target highlight (nodeAtPoint w/ radius, incl type-B)
mouseup over target node:
   source type-B?  → adoptNode → entity_id_s     ┐
   target type-B?  → adoptNode → entity_id_t     ┘ (await)
   → onEdgeDrawn(entity_id_s, entity_id_t, normPoly, lineType)
   → POST /graph/edges  (GraphCorrection, entity→entity, unchanged)
   → refreshGraphAndCounts()
mouseup on empty canvas → cancel draft (no freepoint edge)
```

## Error handling

- Adopt failure during connect → abort the edge, toast, leave the type-B node
  un-adopted (no partial state).
- Drag released off any node → silent no-op (cancel draft).
- Source === target (same node) → no-op (existing guard).
- Duplicate edge (same source/target already connected) → rely on existing
  backend/edge behavior; do not special-case in this work.

## Testing

- **vitest (`GraphLayer.test.tsx`):** anchors render on hover for entity AND
  type-B nodes; anchors hidden when not hovered; edges become
  `pointer-events:none` in draw-edge mode and `auto` in select mode.
- **vitest (PidCanvas snapping logic):** extract `nodeAtPoint`/snap as a pure
  helper where feasible and test — bbox-contains hit; nearest-within-radius hit;
  beyond-radius → null; type-B node returned (not skipped); source≠target guard.
- **Playwright on dev (job 58/38):** drag from a node to a nearby instrument →
  edge connects (real `page.mouse` down/move/up); drag to a type-B node →
  auto-adopt + edge; verify a new `GraphCorrection` via authenticated
  `page.evaluate(fetch('/api/v1/jobs/{id}/graph'))`; **clean up** test edges +
  un-adopt afterward. (Per the Playwright gotchas: click/drag real elements, not
  computed coords; re-login per session; close browser when done.)

## Out of scope / phasing

- **Edge re-routing / dragging existing edges, edge-to-edge junctions** (dropping
  an edge onto another line to split it) — not in this pass.
- **Persisting exact ports** — explicitly excluded (decision 3).
- **sub_class display on graph nodes** — separate from this work.
- The team is iterating on OCR/instrument coverage ("see how much it helps, then
  add more"); this UX work is independent of detection completeness — it makes
  whatever nodes exist connectable.

## Files touched

- `webapp/frontend/src/studio/GraphLayer.tsx` — anchors on hover; edge
  `pointer-events` by mode.
- `webapp/frontend/src/studio/PidCanvas.tsx` — drag-to-connect; proximity snap +
  type-B in `nodeAtPoint`; auto-adopt-on-connect wiring.
- `webapp/frontend/src/studio/Studio.tsx` — expose/reuse `adoptNode` returning
  `entity_id` for the connect path.
- `webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx` (+ a PidCanvas
  snap-helper test) — vitest coverage.
- No backend changes (reuses `createAnnotation` + `POST /graph/edges`).
