import { useState } from "react";
import type { GraphEdge, GraphEdgeMethod, JobGraph } from "./types";

/**
 * GraphLayer — toggleable SVG overlay rendering the auto-extracted process
 * graph (nodes + pipe edges) over the full-page P&ID canvas.
 *
 * IMPORTANT: this component returns SVG `<g>` content and is mounted INSIDE
 * PageWithOverlays' `<svg viewBox="0 0 natural.w natural.h">`. Graph coords are
 * already page-pixel — no tile→page translation (unlike raw detections), so a
 * point [x, y] maps straight to SVG user units.
 *
 * Edges are colored by extraction method:
 *   opencv       → solid green   (var(--ok))
 *   llm_fallback → dashed yellow (var(--warn))
 *   user_added   → solid cyan    (var(--scan-cyan))
 *
 * Extraction *failures* are surfaced too, so users can SEE where the resolver
 * could not connect geometry and draw the missing edges (human-in-the-loop):
 *   orphan_lines   → faint translucent DASHED amber polylines, drawn UNDER the
 *                    connected edges/nodes so real edges stay prominent.
 *   floating nodes → symbols detected but not linked to any edge (node ids in
 *                    graph.floating_nodes, plus nodes with entity_id == null):
 *                    rendered as a hollow amber warning ring instead of cyan.
 */

// Warning color for unconnected geometry (amber, var(--warn) = #F59E0B).
const ORPHAN_COLOR = "var(--warn)";

// Per-method stroke style. Colors resolve to the design tokens; jsdom returns
// the literal string we set inline so tests can assert on it directly.
const METHOD_STYLE: Record<GraphEdgeMethod, { color: string; dashed: boolean }> = {
  opencv: { color: "var(--ok)", dashed: false },
  llm_fallback: { color: "var(--warn)", dashed: true },
  user_added: { color: "var(--scan-cyan)", dashed: false },
};

// Fallback for an unexpected method value (the contract is fixed, but stay safe).
const FALLBACK_STYLE = { color: "var(--info)", dashed: false };

function styleFor(method: string) {
  return METHOD_STYLE[method as GraphEdgeMethod] ?? FALLBACK_STYLE;
}

// Stable marker id per method, e.g. "arrow-opencv". Directed edges reference
// these via markerEnd; undirected edges reference nothing (render as today).
function markerIdFor(method: string): string {
  return `arrow-${method}`;
}

interface Props {
  graph: JobGraph;
  natural: { w: number; h: number };
  visible: boolean;
  onSelect: (entityId: string, entityClass?: string) => void;
}

export default function GraphLayer({ graph, natural, visible, onSelect }: Props) {
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);

  if (!visible || !graph) return null;

  // Match the conventions used by the sibling layers in PidCanvas.
  const sw = Math.max(1, natural.w / 500);
  const edgeWidth = sw * 1.5;
  const nodeRadius = sw * 3;

  const orphanWidth = edgeWidth; // same gauge as edges, but dashed + translucent.

  // Graph coords live in the page-image space the pipeline traced
  // (graph.page_width × page_height). The canvas viewBox is `natural` (a
  // different-resolution render of the same page), so scale graph geometry into
  // the viewBox — otherwise nodes/edges/orphans collapse into a corner. Missing
  // page dims (legacy graphs) → scale 1 (render unscaled, as before).
  const sx = graph.page_width ? natural.w / graph.page_width : 1;
  const sy = graph.page_height ? natural.h / graph.page_height : 1;
  const scaleTransform = sx !== 1 || sy !== 1 ? `scale(${sx},${sy})` : undefined;

  // tag lookup for edge hover titles (source/target tags).
  const tagById = new Map<string, string | null>();
  for (const n of graph.nodes) tagById.set(n.id, n.tag);

  // A node is "unmatched/floating" — detected but not linked to any edge — if
  // the assembler listed it in floating_nodes, or it has no canonical
  // entity_id. Either way it renders as an amber warning ring, not cyan.
  const floatingSet = new Set(graph.floating_nodes ?? []);
  const isUnmatched = (id: string, entityId: string | null) =>
    floatingSet.has(id) || entityId === null;

  // One arrowhead marker per method, colored to match its edge. markerUnits
  // defaults to "strokeWidth" so the arrowhead scales with each edge's
  // strokeWidth/edgeWidth automatically. orient="auto" points it along the
  // polyline's final segment (the target end). refX sits the tip at the
  // endpoint; the 0..10 / 0..10 viewBox is the conventional marker space.
  const markerDefs = (Object.keys(METHOD_STYLE) as GraphEdgeMethod[]).map((method) => (
    <marker
      key={`marker-${method}`}
      id={markerIdFor(method)}
      data-arrow-method={method}
      viewBox="0 0 10 10"
      refX="9"
      refY="5"
      markerWidth="6"
      markerHeight="6"
      orient="auto-start-reverse"
    >
      <path d="M 0 0 L 10 5 L 0 10 z" fill={METHOD_STYLE[method].color} />
    </marker>
  ));

  return (
    <g data-graph-layer="true">
      <defs>{markerDefs}</defs>

      <g data-graph-content="true" transform={scaleTransform}>
      {/* Orphan lines FIRST (lowest layer) — detected pipe segments the
          resolver could not connect to nodes. Faint translucent dashed amber
          so they read as "unconnected / needs a human-drawn edge" without
          competing with the real (green/yellow/cyan) connected edges above. */}
      {(graph.orphan_lines ?? []).map((o, i) => {
        if (!o.polyline || o.polyline.length < 2) return null;
        const points = o.polyline.map((p) => p.join(",")).join(" ");
        return (
          <polyline
            key={`gorphan-${i}`}
            data-orphan={i}
            data-graph-orphan="true"
            points={points}
            fill="none"
            stroke={ORPHAN_COLOR}
            strokeOpacity={0.5}
            strokeWidth={orphanWidth}
            strokeDasharray={`${orphanWidth * 2} ${orphanWidth * 2}`}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ pointerEvents: "none" }}
          >
            <title>{`Unconnected pipe segment — draw an edge to connect${o.reason ? ` (${o.reason})` : ""}`}</title>
          </polyline>
        );
      })}

      {/* Edges next so node circles draw on top of their endpoints. */}
      {graph.edges.map((e: GraphEdge) => {
        const style = styleFor(e.method);
        const points = e.polyline.map((p) => p.join(",")).join(" ");
        const hovered = hoveredEdge === e.id;
        const srcTag = tagById.get(e.source) ?? e.source;
        const tgtTag = tagById.get(e.target) ?? e.target;
        return (
          <polyline
            key={`gedge-${e.id}`}
            data-graph-edge={e.id}
            data-method={e.method}
            points={points}
            fill="none"
            stroke={style.color}
            markerEnd={e.directed ? `url(#${markerIdFor(e.method)})` : undefined}
            strokeWidth={hovered ? edgeWidth * 2 : edgeWidth}
            strokeDasharray={style.dashed ? `${edgeWidth * 4} ${edgeWidth * 3}` : undefined}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ pointerEvents: "stroke", cursor: "default" }}
            onMouseEnter={() => setHoveredEdge(e.id)}
            onMouseLeave={() => setHoveredEdge((h) => (h === e.id ? null : h))}
          >
            <title>{`${srcTag} → ${tgtTag} (${e.method})`}</title>
          </polyline>
        );
      })}

      {/* Nodes — small circles at each node's bbox center; skip null bbox. */}
      {graph.nodes.map((n) => {
        if (!n.bbox || n.bbox.length !== 4) return null;
        const [x1, y1, x2, y2] = n.bbox;
        const cx = (x1 + x2) / 2;
        const cy = (y1 + y2) / 2;
        const clickable = typeof n.entity_id === "string" && n.entity_id.length > 0;
        // Unmatched/floating: symbol detected but not linked to an edge → amber
        // warning ring (hollow) so it reads as "not connected" vs cyan = linked.
        const unmatched = isUnmatched(n.id, n.entity_id);
        return (
          <circle
            key={`gnode-${n.id}`}
            data-graph-node={n.id}
            data-unmatched={unmatched ? "true" : undefined}
            cx={cx}
            cy={cy}
            r={nodeRadius}
            fill={unmatched ? "none" : "var(--scan-cyan)"}
            fillOpacity={unmatched ? undefined : 0.85}
            stroke={unmatched ? ORPHAN_COLOR : "#ffffff"}
            strokeWidth={unmatched ? sw * 1.1 : sw * 0.6}
            strokeOpacity={unmatched ? 0.9 : 0.7}
            style={{
              pointerEvents: clickable ? "auto" : "none",
              cursor: clickable ? "pointer" : "default",
            }}
            onClick={
              clickable
                ? (ev) => {
                    ev.stopPropagation();
                    onSelect(n.entity_id as string, n.class ?? undefined);
                  }
                : undefined
            }
          >
            <title>
              {unmatched
                ? `${n.tag ?? n.class ?? n.id} — detected but not linked to any pipe`
                : (n.tag ?? n.class ?? n.id)}
            </title>
          </circle>
        );
      })}
      </g>
    </g>
  );
}
