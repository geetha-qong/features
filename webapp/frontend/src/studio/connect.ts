import type { JobGraph, GraphNode } from "./types";
import type { LineType } from "./PidCanvas";

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
