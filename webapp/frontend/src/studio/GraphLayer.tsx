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
 */

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

  // tag lookup for edge hover titles (source/target tags).
  const tagById = new Map<string, string | null>();
  for (const n of graph.nodes) tagById.set(n.id, n.tag);

  return (
    <g data-graph-layer="true">
      {/* Edges first so node circles draw on top of their endpoints. */}
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
        return (
          <circle
            key={`gnode-${n.id}`}
            data-graph-node={n.id}
            cx={cx}
            cy={cy}
            r={nodeRadius}
            fill="var(--scan-cyan)"
            fillOpacity={0.85}
            stroke="#ffffff"
            strokeWidth={sw * 0.6}
            strokeOpacity={0.7}
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
            <title>{n.tag ?? n.class ?? n.id}</title>
          </circle>
        );
      })}
    </g>
  );
}
