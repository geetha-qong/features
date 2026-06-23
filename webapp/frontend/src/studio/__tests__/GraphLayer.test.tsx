import { render, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import GraphLayer from "../GraphLayer";
import type { JobGraph } from "../types";

const natural = { w: 1000, h: 800 };

function makeGraph(overrides: Partial<JobGraph> = {}): JobGraph {
  return {
    version: "0.1",
    job_id: 42,
    page: 1,
    generated_at: "2026-06-13T00:00:00Z",
    stats: { nodes: 3, edges: 3, fallback_used: false, auto_edges: 2, user_edges: 1 },
    nodes: [
      { id: "n_000", entity_id: "ent-a", tag: "BV-1", class: "valve_bv", bbox: [10, 10, 30, 30], tile: "t0", confidence: 0.9 },
      { id: "n_001", entity_id: "ent-b", tag: "FT-1", class: "instrument", bbox: [100, 100, 120, 120], tile: "t0", confidence: 0.8 },
      // null-bbox node — must NOT render a circle.
      { id: "n_002", entity_id: null, tag: null, class: null, bbox: null, tile: "t0", confidence: 0.5 },
    ],
    edges: [
      { id: "e_000", source: "n_000", target: "n_001", polyline: [[20, 20], [110, 110]], tile: "t0", method: "opencv", confidence: 0.7 },
      { id: "e_001", source: "n_001", target: "n_000", polyline: [[110, 110], [20, 20]], tile: "t0", method: "llm_fallback", confidence: 0.6 },
      { id: "e_002", source: "n_000", target: "n_001", polyline: [[20, 20], [110, 110]], tile: "t0", method: "user_added", confidence: 1 },
    ],
    floating_nodes: [],
    orphan_lines: [],
    ...overrides,
  };
}

function renderLayer(props: Partial<React.ComponentProps<typeof GraphLayer>> = {}) {
  const onSelect = props.onSelect ?? vi.fn();
  const { container } = render(
    <svg viewBox={`0 0 ${natural.w} ${natural.h}`}>
      <GraphLayer
        graph={props.graph ?? makeGraph()}
        natural={props.natural ?? natural}
        visible={props.visible ?? true}
        onSelect={onSelect}
      />
    </svg>,
  );
  return { container, onSelect };
}

describe("GraphLayer", () => {
  test("renders one circle per node with a non-null bbox", () => {
    const { container } = renderLayer();
    // 3 nodes total, but n_002 has bbox=null → only 2 circles.
    expect(container.querySelectorAll("[data-graph-node]")).toHaveLength(2);
    expect(container.querySelector('[data-graph-node="n_002"]')).toBeNull();
  });

  test("renders one polyline per edge", () => {
    const { container } = renderLayer();
    expect(container.querySelectorAll("[data-graph-edge]")).toHaveLength(3);
  });

  test("colors edges by method", () => {
    const { container } = renderLayer();
    const opencv = container.querySelector('[data-graph-edge="e_000"]') as SVGElement;
    const fallback = container.querySelector('[data-graph-edge="e_001"]') as SVGElement;
    const user = container.querySelector('[data-graph-edge="e_002"]') as SVGElement;

    expect(opencv.getAttribute("stroke")).toBe("var(--ok)");
    expect(fallback.getAttribute("stroke")).toBe("var(--warn)");
    expect(user.getAttribute("stroke")).toBe("var(--scan-cyan)");

    // llm_fallback is dashed; opencv + user_added are solid (no dasharray).
    expect(fallback.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(opencv.getAttribute("stroke-dasharray")).toBeNull();
    expect(user.getAttribute("stroke-dasharray")).toBeNull();
  });

  test("clicking a node fires onSelect with its entity_id and class", () => {
    const { container, onSelect } = renderLayer();
    const node = container.querySelector('[data-graph-node="n_000"]') as SVGElement;
    fireEvent.click(node);
    expect(onSelect).toHaveBeenCalledWith("ent-a", "valve_bv");
  });

  test("renders a marker-end on a directed edge", () => {
    const graph = makeGraph({
      edges: [
        { id: "e_dir", source: "n_000", target: "n_001", polyline: [[20, 20], [110, 110]], tile: "t0", method: "opencv", confidence: 0.7, directed: true },
      ],
    });
    const { container } = renderLayer({ graph });
    const edge = container.querySelector('[data-graph-edge="e_dir"]') as SVGElement;
    expect(edge.getAttribute("marker-end")).toBe("url(#arrow-opencv)");
  });

  test("renders no marker-end on an undirected edge (directed false or undefined)", () => {
    const graph = makeGraph({
      edges: [
        { id: "e_false", source: "n_000", target: "n_001", polyline: [[20, 20], [110, 110]], tile: "t0", method: "opencv", confidence: 0.7, directed: false },
        { id: "e_undef", source: "n_001", target: "n_000", polyline: [[110, 110], [20, 20]], tile: "t0", method: "user_added", confidence: 1 },
      ],
    });
    const { container } = renderLayer({ graph });
    const eFalse = container.querySelector('[data-graph-edge="e_false"]') as SVGElement;
    const eUndef = container.querySelector('[data-graph-edge="e_undef"]') as SVGElement;
    expect(eFalse.getAttribute("marker-end")).toBeNull();
    expect(eUndef.getAttribute("marker-end")).toBeNull();
  });

  test("arrowhead marker color matches the edge method", () => {
    const graph = makeGraph({
      edges: [
        { id: "e_u", source: "n_000", target: "n_001", polyline: [[20, 20], [110, 110]], tile: "t0", method: "user_added", confidence: 1, directed: true },
      ],
    });
    const { container } = renderLayer({ graph });
    const edge = container.querySelector('[data-graph-edge="e_u"]') as SVGElement;
    // The edge points at the user_added marker...
    expect(edge.getAttribute("marker-end")).toBe("url(#arrow-user_added)");
    // ...and that marker's arrowhead path is filled with the user_added color.
    const marker = container.querySelector('[data-arrow-method="user_added"]') as SVGElement;
    const path = marker.querySelector("path") as SVGElement;
    expect(path.getAttribute("fill")).toBe("var(--scan-cyan)");
  });

  test("renders one dashed amber polyline per orphan line", () => {
    const graph = makeGraph({
      orphan_lines: [
        { polyline: [[0, 0], [50, 50]], tile: "t0", reason: "no_endpoint_node" },
        { polyline: [[200, 200], [260, 200], [260, 280]], tile: "t0", reason: "dead_end" },
      ],
    });
    const { container } = renderLayer({ graph });
    const orphans = container.querySelectorAll("[data-orphan]");
    expect(orphans).toHaveLength(2);
    // Distinguishing style: amber stroke + dashed + translucent + non-clickable.
    const first = orphans[0] as SVGElement;
    expect(first.getAttribute("stroke")).toBe("var(--warn)");
    expect(first.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(first.getAttribute("stroke-opacity")).toBe("0.5");
    // Drawn UNDER the connected edges (lower in document order).
    const firstEdge = container.querySelector("[data-graph-edge]") as Element;
    expect(first.compareDocumentPosition(firstEdge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("renders orphans even when there are 0 connected edges (job-44 case)", () => {
    const graph = makeGraph({
      edges: [],
      orphan_lines: Array.from({ length: 5 }, (_, i) => ({
        polyline: [[i * 10, 0], [i * 10, 100]],
        tile: "t0",
        reason: "unconnected",
      })),
    });
    const { container } = renderLayer({ graph });
    expect(container.querySelectorAll("[data-graph-edge]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-orphan]")).toHaveLength(5);
  });

  test("renders unmatched/floating nodes with the amber warning style", () => {
    const graph = makeGraph({
      // n_000 is linked (cyan); n_001 is listed floating → amber ring.
      floating_nodes: ["n_001"],
    });
    const { container } = renderLayer({ graph });
    const linked = container.querySelector('[data-graph-node="n_000"]') as SVGElement;
    const floating = container.querySelector('[data-graph-node="n_001"]') as SVGElement;
    expect(linked.getAttribute("data-unmatched")).toBeNull();
    expect(linked.getAttribute("fill")).toBe("var(--scan-cyan)");
    expect(floating.getAttribute("data-unmatched")).toBe("true");
    expect(floating.getAttribute("fill")).toBe("none");
    expect(floating.getAttribute("stroke")).toBe("var(--warn)");
  });

  test("a node with null entity_id is treated as unmatched when it has a bbox", () => {
    const graph = makeGraph({
      nodes: [
        { id: "n_x", entity_id: null, tag: "?", class: null, bbox: [5, 5, 25, 25], tile: "t0", confidence: 0.4 },
      ],
      edges: [],
    });
    const { container } = renderLayer({ graph });
    const node = container.querySelector('[data-graph-node="n_x"]') as SVGElement;
    expect(node.getAttribute("data-unmatched")).toBe("true");
    expect(node.getAttribute("stroke")).toBe("var(--warn)");
  });

  test("renders nothing when not visible", () => {
    const { container } = renderLayer({ visible: false });
    expect(container.querySelector("[data-graph-layer]")).toBeNull();
    expect(container.querySelectorAll("[data-graph-node]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-graph-edge]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-orphan]")).toHaveLength(0);
  });

  test("scales graph coords from page_width/height onto the canvas viewBox", () => {
    // Graph traced at 1000x1000; canvas natural is 2000x2000 → scale(2,2).
    const graph = makeGraph({ page_width: 1000, page_height: 1000 });
    const { container } = renderLayer({ graph, natural: { w: 2000, h: 2000 } });
    const content = container.querySelector('[data-graph-content]') as SVGElement;
    expect(content).not.toBeNull();
    expect(content.getAttribute("transform")).toBe("scale(2,2)");
  });

  test("does NOT scale when page dims are absent (legacy graph)", () => {
    // makeGraph() has no page_width/height → scale 1 → no transform attr.
    const { container } = renderLayer();
    const content = container.querySelector('[data-graph-content]') as SVGElement;
    expect(content).not.toBeNull();
    expect(content.getAttribute("transform")).toBeNull();
  });
});
