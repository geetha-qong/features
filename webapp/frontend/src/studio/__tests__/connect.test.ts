import { test, expect } from "vitest";
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
