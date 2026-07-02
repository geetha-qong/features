# Graph Drawing UX (draw.io-style connections) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make connecting graph nodes in Studio feel like draw.io — hover reveals connection anchors, press-drag-release snaps an edge to the target node (incl. type-B nodes, auto-adopted on connect), with proximity snapping and no interference from existing lines.

**Architecture:** Frontend-only, in the existing Studio canvas (React + SVG, NOT Konva). Extract the connect *logic* into pure, unit-testable helpers (`webapp/frontend/src/studio/connect.ts`); wire drag event handlers and hover-anchors into the existing `PidCanvas.tsx` / `GraphLayer.tsx`; reuse the `#135` adopt path and the existing `onEdgeDrawn → POST /graph/edges` route. No backend or schema change.

**Tech Stack:** React + TypeScript + Vite SPA, SVG canvas, vitest (`npx vitest run`), `npx tsc --noEmit` for type-check. Playwright-on-dev for the drag E2E.

## Global Constraints

- **Edges stay node-to-node** (`onEdgeDrawn(source_entity_id, target_entity_id, polyline, line_type)` and `GraphCorrection(source_entity_id, target_entity_id)`) — NO schema change, NO port persistence. Anchors are visual only.
- **Auto-adopt type-B on connect:** reuse `Studio.adoptNode` (the `#135` flow); it must return the new `entity_id`. Edges must always reference real entity_ids — adopt is awaited before `onEdgeDrawn`.
- **A drag/click that doesn't land on a node is a no-op** — never create a `freepoint:x,y` endpoint from the new drag flow.
- **Screen-constant sizing:** anchors and the snap radius use `sw = natural.w / 1200`-relative units (cancels page resolution, like the `#137` hit target).
- Use `npx tsc --noEmit` from `webapp/frontend/` (NOT `npm run lint`), and `npx vitest run` for tests. `GraphLayer.test.tsx` has **5 PRE-EXISTING failures** (a `cy/ph<0.08` margin-guard excludes old fixtures) — do not "fix" them; just don't ADD failures.
- Local frontend iteration: host `npx vite build` to refresh the served `dist` (override mounts `./webapp`); a docker build is only needed for repo-root `*.py`. (Not needed for unit tests.)
- The canvas is SVG; detection/graph elements are nested `<svg>`/`<g>`. Tests render `<GraphLayer/>` inside an `<svg viewBox>` (see existing `GraphLayer.test.tsx` harness).

---

### Task 1: Edges never block drawing — `pointer-events` by mode (GraphLayer)

**Files:**
- Modify: `webapp/frontend/src/studio/GraphLayer.tsx` (Props + `renderEdge` ~172-243, default export signature line 24)
- Modify: `webapp/frontend/src/studio/PidCanvas.tsx` (pass `mode` to `<GraphLayer>` ~1342-1354)
- Test: `webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx`

**Interfaces:**
- Produces: `GraphLayer` accepts a new optional prop `mode?: "select" | "mark-symbol" | "draw-edge"`. When `mode === "draw-edge"`, BOTH edge polylines render `pointerEvents: "none"`.

- [ ] **Step 1: Write the failing test**

Add to `GraphLayer.test.tsx` (place a node away from the top-left margin guard — `cx/pw ≥ 0.07, cy/ph ≥ 0.08`; the default fixture edge `e_000` runs between n_000 and n_001):

```tsx
test("edge hit-target is non-interactive in draw-edge mode", () => {
  const { container } = renderLayer({ mode: "draw-edge", onEdgeClick: () => {} });
  const hit = container.querySelector('[data-graph-edge-hit="e_000"]') as SVGElement;
  expect(hit).not.toBeNull();
  expect(hit.style.pointerEvents).toBe("none");
});

test("edge hit-target is interactive in select mode", () => {
  const { container } = renderLayer({ mode: "select", onEdgeClick: () => {} });
  const hit = container.querySelector('[data-graph-edge-hit="e_000"]') as SVGElement;
  expect(hit.style.pointerEvents).toBe("stroke");
});
```

(`renderLayer` already spreads props onto `<GraphLayer>`; pass `mode`/`onEdgeClick` through it — extend the helper's prop type if needed.)

- [ ] **Step 2: Run, verify FAIL**

Run: `cd webapp/frontend && npx vitest run -t "draw-edge mode" -t "select mode"`
Expected: FAIL — `mode` unhandled, hit polyline still keys only on `onEdgeClick`.

- [ ] **Step 3: Implement**

In `GraphLayer.tsx`: add `mode` to `interface Props` and the destructured params (line 24). In `renderEdge`, change the hit polyline's style (currently line ~242 `pointerEvents: onEdgeClick ? "stroke" : "none"`) to force non-interactive while drawing:

```tsx
// hit polyline style:
style={{
  pointerEvents: mode === "draw-edge" ? "none" : (onEdgeClick ? "stroke" : "none"),
  cursor: mode === "draw-edge" ? "crosshair" : (onEdgeClick ? "pointer" : "default"),
}}
```

In `PidCanvas.tsx` `<GraphLayer ...>` (line ~1343), add the prop: `mode={mode}`.

- [ ] **Step 4: Run, verify PASS** — `npx vitest run -t "draw-edge mode" -t "select mode"` → PASS. Also `npx vitest run src/studio/__tests__/GraphLayer.test.tsx` shows no NEW failures beyond the 5 pre-existing.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/GraphLayer.tsx webapp/frontend/src/studio/PidCanvas.tsx webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx
git commit -m "feat(graph-ux): edges non-interactive in draw-edge mode (draw over lines)"
```

---

### Task 2: Proximity snapping + type-B endpoints — pure `connect.ts` helper

**Files:**
- Create: `webapp/frontend/src/studio/connect.ts`
- Test: `webapp/frontend/src/studio/__tests__/connect.test.ts`

**Interfaces:**
- Produces (consumed by Tasks 3 & 6):
  - `type ResolvedEndpoint = { kind: "entity"; entityId: string; center: [number, number] } | { kind: "typeB"; node: GraphNode; center: [number, number] } | { kind: "none" }`
  - `function resolveEndpoint(pt: [number, number], graph: JobGraph | null, natural: {w:number;h:number}, snapRadiusPx: number): ResolvedEndpoint`
  - It mirrors today's `PidCanvas.nodeAtPoint` (bbox-contains, page→natural scaling via `graph.page_width/height`) but: (a) if no bbox contains `pt`, returns the **nearest node whose center is within `snapRadiusPx`**; (b) **does NOT skip type-B nodes** — returns `kind:"typeB"` for nodes without `entity_id`; (c) returns `kind:"none"` when nothing is in range.

- [ ] **Step 1: Write the failing test**

Create `__tests__/connect.test.ts`:

```ts
import { describe, test, expect } from "vitest";
import { resolveEndpoint } from "../connect";
import type { JobGraph } from "../types";

const natural = { w: 1000, h: 1000 };
const graph = {
  version: "0.1", job_id: 1, page: 1,
  page_width: 1000, page_height: 1000,
  stats: { nodes: 2, edges: 0, fallback_used: false },
  nodes: [
    { id: "n_a", entity_id: "EA", tag: "BV-1", class: "valve_bv", bbox: [100, 100, 140, 140], tile: "t", confidence: 1 },
    { id: "n_b", entity_id: null, tag: null, class: "valve_bv", bbox: [500, 500, 540, 540], tile: "t", confidence: 1 },
  ],
  edges: [], floating_nodes: [], orphan_lines: [],
} as unknown as JobGraph;

test("bbox-contains returns the entity endpoint", () => {
  const r = resolveEndpoint([120, 120], graph, natural, 30);
  expect(r.kind).toBe("entity");
  if (r.kind === "entity") expect(r.entityId).toBe("EA");
});

test("near a node within radius snaps to it", () => {
  // node n_a center is (120,120); click at (150,120) is 30px away
  const r = resolveEndpoint([150, 120], graph, natural, 40);
  expect(r.kind).toBe("entity");
});

test("beyond the snap radius returns none", () => {
  const r = resolveEndpoint([300, 300], graph, natural, 40);
  expect(r.kind).toBe("none");
});

test("type-B node (no entity_id) is returned, not skipped", () => {
  const r = resolveEndpoint([520, 520], graph, natural, 30);
  expect(r.kind).toBe("typeB");
  if (r.kind === "typeB") expect(r.node.id).toBe("n_b");
});
```

- [ ] **Step 2: Run, verify FAIL** — `cd webapp/frontend && npx vitest run src/studio/__tests__/connect.test.ts` → FAIL (module missing).

- [ ] **Step 3: Implement `connect.ts`**

```ts
import type { JobGraph, GraphNode } from "./types";

export type ResolvedEndpoint =
  | { kind: "entity"; entityId: string; center: [number, number] }
  | { kind: "typeB"; node: GraphNode; center: [number, number] }
  | { kind: "none" };

/** Resolve a page-pixel point to a graph node for edge drawing.
 *  bbox-contains wins; else nearest node center within snapRadiusPx; else none.
 *  Type-B nodes (no entity_id) ARE returned (kind:"typeB") so callers can adopt. */
export function resolveEndpoint(
  pt: [number, number],
  graph: JobGraph | null,
  natural: { w: number; h: number },
  snapRadiusPx: number,
): ResolvedEndpoint {
  if (!graph || !graph.page_width || !graph.page_height) return { kind: "none" };
  const sx = natural.w / graph.page_width;
  const sy = natural.h / graph.page_height;
  let best: { node: GraphNode; center: [number, number]; dist: number } | null = null;
  for (const n of graph.nodes) {
    if (!n.bbox) continue;
    const b = [n.bbox[0] * sx, n.bbox[1] * sy, n.bbox[2] * sx, n.bbox[3] * sy];
    const center: [number, number] = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
    const inside = pt[0] >= b[0] && pt[0] <= b[2] && pt[1] >= b[1] && pt[1] <= b[3];
    const dist = Math.hypot(pt[0] - center[0], pt[1] - center[1]);
    if (inside) return mk(n, center);
    if (dist <= snapRadiusPx && (!best || dist < best.dist)) best = { node: n, center, dist };
  }
  return best ? mk(best.node, best.center) : { kind: "none" };
}

function mk(n: GraphNode, center: [number, number]): ResolvedEndpoint {
  return n.entity_id
    ? { kind: "entity", entityId: n.entity_id, center }
    : { kind: "typeB", node: n, center };
}
```

- [ ] **Step 4: Run, verify PASS** — `npx vitest run src/studio/__tests__/connect.test.ts` → 4 PASS. `npx tsc --noEmit` clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/connect.ts webapp/frontend/src/studio/__tests__/connect.test.ts
git commit -m "feat(graph-ux): resolveEndpoint — proximity snapping + type-B endpoints"
```

---

### Task 3: `adoptNode` returns the new entity_id (Studio)

**Files:**
- Modify: `webapp/frontend/src/studio/Studio.tsx` (`adoptNode` ~605-650)
- Test: `webapp/frontend/src/studio/__tests__/connect.test.ts` is not applicable — this is a thin return-value change verified by tsc + the existing adopt E2E. Add no new unit test; verify by type + the Task 6 Playwright run.

**Interfaces:**
- Produces (consumed by Task 4/6): `adoptNode(node: GraphNode): Promise<string | null>` — returns the adopted `entity_id` (from `createAnnotation`'s `row.entity_id`) on success, `null` on any early-bail/failure. Existing callers that ignore the return are unaffected.

- [ ] **Step 1: Change the signature + return values**

In `Studio.tsx` `adoptNode`: change to return `string | null`. Each early `return;` (no bbox; unknown class) becomes `return null;`. After a successful `createAnnotation` (`if (row) { ... }`), keep the OCR/refresh/toast side-effects, then `return row.entity_id;`. If `row` is falsy, `return null;`.

```tsx
async function adoptNode(node: GraphNode): Promise<string | null> {
  if (!node.bbox) { showToast("Cannot adopt: node has no bounding box"); return null; }
  const [entity_class, sub_raw] = (node.class ?? "").split("_");
  if (entity_class !== "valve" && entity_class !== "instrument" && entity_class !== "equipment") {
    showToast("Cannot adopt: unknown class"); return null;
  }
  const sub_class = (sub_raw ?? "").toUpperCase();
  const bbox = node.bbox as [number, number, number, number];
  const row = await createAnnotation({
    entity_class: entity_class as "valve" | "instrument" | "equipment",
    sub_class, bbox, sheet_number: activeSheetNumber, linked_detection_index: null,
  });
  if (!row) return null;
  try {
    const pw = graph?.page_width ?? naturalSize?.w ?? 0;
    const ph = graph?.page_height ?? naturalSize?.h ?? 0;
    if (pw > 0 && ph > 0) {
      const [bx1, by1, bx2, by2] = bbox;
      const norm: [number, number, number, number] = [bx1 / pw, by1 / ph, bx2 / pw, by2 / ph];
      const r = await ocrBbox(project.id, norm);
      if (r.found && r.text) await patchAnnotation(row.entity_id, { tag: r.text });
    }
  } catch { /* OCR is a bonus — never break adopt */ }
  setAdoptTarget(null);
  await refreshGraphAndCounts();
  showToast(`Adopted as ${sub_class}`);
  return row.entity_id;
}
```

- [ ] **Step 2: Type-check** — `cd webapp/frontend && npx tsc --noEmit` → clean (the existing `onClick={() => onAdopt?.(adoptTarget)}` caller ignores the Promise return; confirm no new TS error).

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/studio/Studio.tsx
git commit -m "feat(graph-ux): adoptNode returns new entity_id for connect-time adoption"
```

---

### Task 4: Connect orchestrator — adopt-if-type-B then draw (pure logic)

**Files:**
- Modify: `webapp/frontend/src/studio/connect.ts` (add `connectEndpoints`)
- Test: `webapp/frontend/src/studio/__tests__/connect.test.ts`

**Interfaces:**
- Consumes: `ResolvedEndpoint` (Task 2); an injected `adopt(node) => Promise<string|null>` (Task 3's `adoptNode`); an injected `onEdgeDrawn(src, tgt, polyline, lineType)`.
- Produces: `async function connectEndpoints(src: ResolvedEndpoint, tgt: ResolvedEndpoint, deps: {...}): Promise<boolean>` — resolves both endpoints to entity_ids (adopting type-B ones), then calls `onEdgeDrawn` with a 2-point normalized polyline (centers ÷ natural). Returns false (no-op) when either endpoint is `none`, when adoption fails, or when source === target.

- [ ] **Step 1: Write the failing test**

Append to `connect.test.ts`:

```ts
import { connectEndpoints } from "../connect";

const deps = (over = {}) => ({
  natural: { w: 1000, h: 1000 },
  lineType: "process_pipe" as const,
  adopt: async (_n: any) => "ADOPTED",
  onEdgeDrawn: () => {},
  ...over,
});

test("entity→entity calls onEdgeDrawn with entity ids", async () => {
  const calls: any[] = [];
  const ok = await connectEndpoints(
    { kind: "entity", entityId: "EA", center: [100, 100] },
    { kind: "entity", entityId: "EB", center: [200, 200] },
    deps({ onEdgeDrawn: (s: string, t: string) => calls.push([s, t]) }),
  );
  expect(ok).toBe(true);
  expect(calls[0]).toEqual(["EA", "EB"]);
});

test("type-B endpoint is adopted, then drawn with the new id", async () => {
  const calls: any[] = [];
  const ok = await connectEndpoints(
    { kind: "entity", entityId: "EA", center: [100, 100] },
    { kind: "typeB", node: { id: "n_b" } as any, center: [200, 200] },
    deps({ adopt: async () => "NEW", onEdgeDrawn: (s: string, t: string) => calls.push([s, t]) }),
  );
  expect(ok).toBe(true);
  expect(calls[0]).toEqual(["EA", "NEW"]);
});

test("adopt failure aborts (no edge drawn)", async () => {
  const calls: any[] = [];
  const ok = await connectEndpoints(
    { kind: "entity", entityId: "EA", center: [100, 100] },
    { kind: "typeB", node: { id: "n_b" } as any, center: [200, 200] },
    deps({ adopt: async () => null, onEdgeDrawn: () => calls.push(1) }),
  );
  expect(ok).toBe(false);
  expect(calls.length).toBe(0);
});

test("none endpoint or same-node is a no-op", async () => {
  const calls: any[] = [];
  const d = deps({ onEdgeDrawn: () => calls.push(1) });
  expect(await connectEndpoints({ kind: "none" }, { kind: "entity", entityId: "EB", center: [0,0] }, d)).toBe(false);
  expect(await connectEndpoints({ kind: "entity", entityId: "EA", center: [1,1] }, { kind: "entity", entityId: "EA", center: [2,2] }, d)).toBe(false);
  expect(calls.length).toBe(0);
});
```

- [ ] **Step 2: Run, verify FAIL** — `npx vitest run src/studio/__tests__/connect.test.ts -t connectEndpoints` (or the new test names) → FAIL (not exported).

- [ ] **Step 3: Implement `connectEndpoints` in `connect.ts`**

```ts
// connect.ts already imports GraphNode/JobGraph from "./types" (Task 2). Also
// import the real LineType — it is exported from "./PidCanvas" (line 60), NOT
// "./types". Use a TYPE-ONLY import so there is no runtime import cycle
// (PidCanvas imports connect.ts at runtime; `import type` is erased by TS):
//   import type { LineType } from "./PidCanvas";
// Do NOT redefine LineType as `string` — that breaks assignment to onEdgeDrawn's
// literal-union parameter.

export interface ConnectDeps {
  natural: { w: number; h: number };
  lineType: LineType;
  adopt: (node: GraphNode) => Promise<string | null>;
  onEdgeDrawn: (src: string, tgt: string, poly: Array<[number, number]>, lt: LineType) => void;
}

async function toEntityId(e: ResolvedEndpoint, adopt: ConnectDeps["adopt"]): Promise<string | null> {
  if (e.kind === "entity") return e.entityId;
  if (e.kind === "typeB") return await adopt(e.node);
  return null;
}

/** Adopt any type-B endpoints, then emit a node-to-node edge. No-op (returns
 *  false) on a none endpoint, an adopt failure, or source===target. */
export async function connectEndpoints(
  src: ResolvedEndpoint, tgt: ResolvedEndpoint, deps: ConnectDeps,
): Promise<boolean> {
  if (src.kind === "none" || tgt.kind === "none") return false;
  const sc = "center" in src ? src.center : null;
  const tc = "center" in tgt ? tgt.center : null;
  const sId = await toEntityId(src, deps.adopt);
  const tId = await toEntityId(tgt, deps.adopt);
  if (!sId || !tId || sId === tId) return false;
  const { w, h } = deps.natural;
  const poly: Array<[number, number]> = sc && tc
    ? [[sc[0] / w, sc[1] / h], [tc[0] / w, tc[1] / h]]
    : [[0, 0], [0, 0]];
  deps.onEdgeDrawn(sId, tId, poly, deps.lineType);
  return true;
}
```

- [ ] **Step 4: Run, verify PASS** — `npx vitest run src/studio/__tests__/connect.test.ts` → all PASS. `npx tsc --noEmit` clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/connect.ts webapp/frontend/src/studio/__tests__/connect.test.ts
git commit -m "feat(graph-ux): connectEndpoints — adopt type-B endpoints then draw node-to-node edge"
```

---

### Task 5: Connection anchors on node hover (GraphLayer)

**Files:**
- Modify: `webapp/frontend/src/studio/GraphLayer.tsx` (node `<g>` render ~340-420; add hover state)
- Test: `webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx`

**Interfaces:**
- Produces: on hover (or while a connect drag is active), each node renders 4 cardinal anchor handles (`data-anchor` circles) at its bbox N/E/S/W, sized `sw`-relative, `pointerEvents:"auto"`. Anchors render for entity AND type-B nodes. Hidden when not hovered.

- [ ] **Step 1: Write the failing test**

Add to `GraphLayer.test.tsx` (node placed safely; simulate hover with `fireEvent.mouseEnter` on the node `<g>`):

```tsx
import { fireEvent } from "@testing-library/react";

test("hovering a node reveals 4 connection anchors", () => {
  const graph = makeGraph({
    nodes: [{ id: "n_h", entity_id: "E", tag: "T", class: "valve_bv", bbox: [200,200,240,240], tile: "t", confidence: 1 }],
    edges: [], floating_nodes: [],
  });
  const { container } = renderLayer({ graph });
  expect(container.querySelectorAll("[data-anchor]").length).toBe(0); // hidden initially
  const g = container.querySelector('[data-graph-node="n_h"]')!.closest("g")!;
  fireEvent.mouseEnter(g);
  expect(container.querySelectorAll("[data-anchor]").length).toBe(4);
});

test("anchors appear for type-B nodes too", () => {
  const graph = makeGraph({
    nodes: [{ id: "n_tb", entity_id: null, tag: null, class: "valve_bv", bbox: [200,200,240,240], tile: "t", confidence: 1 }],
    edges: [], floating_nodes: [],
  });
  const { container } = renderLayer({ graph });
  const g = container.querySelector('[data-graph-node="n_tb"]')!.closest("g")!;
  fireEvent.mouseEnter(g);
  expect(container.querySelectorAll("[data-anchor]").length).toBe(4);
});
```

- [ ] **Step 2: Run, verify FAIL** — `npx vitest run -t "connection anchors" -t "type-B nodes too"` → FAIL.

- [ ] **Step 3: Implement**

In `GraphLayer.tsx`: add `const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);` (import `useState`). On each node `<g>`, add `onMouseEnter={() => setHoveredNodeId(n.id)}` and `onMouseLeave={() => setHoveredNodeId((h) => (h === n.id ? null : h))}`. Inside the node `<g>`, when `hoveredNodeId === n.id`, render 4 anchor circles at the bbox cardinal midpoints (page→natural scaled like the visible dot), each:

```tsx
{hoveredNodeId === n.id && [
  [cx, b[1]], [b[2], cy], [cx, b[3]], [b[0], cy], // N, E, S, W (scaled coords already in cx/cy/b space)
].map(([ax, ay], i) => (
  <circle key={`anchor-${n.id}-${i}`} data-anchor={n.id}
    cx={ax} cy={ay} r={sw * 2.5} fill="#fff" stroke="#2563eb" strokeWidth={sw * 0.6}
    style={{ pointerEvents: "auto", cursor: "crosshair" }} />
))}
```

(Use the same `cx/cy` and scaled bbox `b` the node already computes; if the node currently uses `nodeRadius`-based coords, compute `b = [x1*sx, y1*sy, x2*sx, y2*sy]` consistent with §2.)

- [ ] **Step 4: Run, verify PASS** — `npx vitest run src/studio/__tests__/GraphLayer.test.tsx` → new tests PASS, no NEW failures beyond the 5 pre-existing. `npx tsc --noEmit` clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/GraphLayer.tsx webapp/frontend/src/studio/__tests__/GraphLayer.test.tsx
git commit -m "feat(graph-ux): hover-revealed connection anchors on graph nodes"
```

---

### Task 6: Drag-to-connect wiring + integration (PidCanvas + Studio) — controller-verified on dev

**Files:**
- Modify: `webapp/frontend/src/studio/PidCanvas.tsx` (draw-edge handlers ~827-896, mouse handlers ~983-988, edgeDraft)
- Modify: `webapp/frontend/src/studio/Studio.tsx` (pass `adoptNode` to PidCanvas as a connect dep)

**Interfaces:**
- Consumes: `resolveEndpoint`, `connectEndpoints` (connect.ts), `adoptNode` (Studio, Promise<string|null>), existing `onEdgeDrawn`, `activeLineType`, `graph`, `natural`.

**This task's logic lives in the Task 2/4 helpers (unit-tested). This task is the event wiring, which is verified on dev with Playwright (drag gestures can't be meaningfully unit-tested in jsdom) — the controller runs that verification, not a subagent.**

- [ ] **Step 1: Add a snap-radius constant + wire press-drag-release**

In `PidCanvas.tsx`: define `const SNAP_RADIUS_PX = sw-relative` (e.g. derive a page-pixel radius `≈ 18 * (natural.w/1200)` consistent with the `#137` hit target; compute where `natural` is available). On the canvas SVG in draw-edge mode:
- `onMouseDown`: `const r = resolveEndpoint(clientToPagePixel(...), graph, natural, SNAP_RADIUS_PX)`. If `r.kind !== "none"`, start a draft `{ source: r, sourcePoint: r.center, cursorPoint: r.center }`. (A node's GraphLayer `<g>` click no longer needs to special-case draw-edge; the SVG-level down handles it because anchors/nodes are under the cursor — but keep `handleGraphNodeClick`'s draw-edge branch working for the 2-click fallback via the same `resolveEndpoint`/`connectEndpoints` path.)
- `onMouseMove`: update `cursorPoint`; compute a live snap-target via `resolveEndpoint` and pass its node id to GraphLayer to highlight (reuse `selectedGraphNodeId`-style highlight or a new `snapTargetId` prop — minimal: highlight via existing hover).
- `onMouseUp`: `const tgt = resolveEndpoint(pt, graph, natural, SNAP_RADIUS_PX)`. Call `await connectEndpoints(draft.source, tgt, { natural, lineType: activeLineType, adopt: onAdoptForConnect, onEdgeDrawn })`. Clear the draft regardless. **No freepoint fallback.**

- [ ] **Step 2: Replace the freepoint path**

Delete/disable the `freepoint:${x},${y}` branch in `onCanvasClickForEdge` (line ~834): a click/drag that resolves to `kind:"none"` is a no-op (clear draft), NOT a floating endpoint. Route the 2-click flow through `resolveEndpoint` + `connectEndpoints` too (shared routine — Global Constraint).

- [ ] **Step 3: Pass `adoptNode` down**

In `Studio.tsx`, pass a connect-adopt callback to `<PidCanvas>` (new optional prop `onAdoptForConnect={adoptNode}`); thread it through PidCanvas's outer→inner component props (mirror how `onAdoptTarget` is threaded, lines 210/268/422/594/630).

- [ ] **Step 4: Type-check + build**

Run: `cd webapp/frontend && npx tsc --noEmit` → clean. Then `npx vitest run` → the full suite shows only the 5 pre-existing GraphLayer failures (Tasks 1/2/4/5 green).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/PidCanvas.tsx webapp/frontend/src/studio/Studio.tsx
git commit -m "feat(graph-ux): drag-to-connect with snapping + auto-adopt (wires resolveEndpoint/connectEndpoints)"
```

- [ ] **Step 6: Controller verification on dev (Playwright)** — NOT a subagent step.

After deploy to dev: log in, open job 38 review, Select mode + Graph layer on. Verify with real `page.mouse.down/move/up`:
  1. Drag from an entity node to a nearby entity node → a new `GraphCorrection` appears (`page.evaluate(fetch('/api/v1/jobs/38/graph'))` shows the user edge).
  2. Drag to a type-B node → it auto-adopts (becomes a `source:"user"` node) AND the edge connects.
  3. Dragging over an existing line does not block the gesture.
  4. **Clean up** every test edge + un-adopt the test node (local AND dev). Close the browser when done.

---

## Notes for the executor

- "Draw over lines" (Task 1) may already be partially handled (the edge hit polyline is `pointerEvents:none` when `onEdgeClick` is undefined, which is the case in draw-edge mode). Task 1 makes it explicit + mode-driven; the real proof is Task 6 step 6.3 on dev.
- The big risk is Task 6's event wiring (React + SVG coords + zoom). Keep ALL connect logic in `connect.ts` (tested); PidCanvas only translates mouse events → page pixels → `resolveEndpoint`/`connectEndpoints`.
