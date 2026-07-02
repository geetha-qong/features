import { useState } from "react";
import type { GraphEdge, GraphEdgeMethod, GraphNode, JobGraph } from "./types";

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

// Dot color by entity class — small solid circles, no rings.
// Always colors by class; opacity (set on the circle) signals matched vs unmatched.
// Actual class values from canonical_graph.json: valve_bv, valve_ncbv,
// valve_relief_safety, valve_ck, inst_field, Pump/Dwg Pump, Motor, …
function nodeColorFor(entityClass: string | null | undefined): string {
  const c = (entityClass ?? "").toLowerCase();
  if (c.includes("valve")) return "#22C55E";          // green — valves
  if (c.includes("inst") || c.includes("transmit") || c.includes("sensor")) return "#60A5FA"; // blue — instruments
  if (c.includes("pump") || c.includes("equip") || c.includes("tank") || c.includes("vessel") || c.includes("motor")) return "#A78BFA"; // purple — rotating/equipment
  if (c.includes("symbol") || c.includes("fit")) return "#F472B6"; // pink — misc symbols
  return "#F59E0B"; // amber — unknown class
}

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
  selectedEdgeId?: string | null;
  onEdgeClick?: (edgeId: string, method: string) => void;
  showLabels?: boolean;
  onNodeClick?: (nodeId: string) => void;
  selectedNodeId?: string | null;
  /** Called when user clicks a type-B node (entity_id == null). */
  onAdoptTarget?: (node: GraphNode) => void;
  /** Canvas interaction mode — when "draw-edge", edge hit-targets are non-interactive
   *  so click events pass through to the SVG surface for drawing new edges. */
  mode?: "select" | "mark-symbol" | "draw-edge";
}

export default function GraphLayer({ graph, natural, visible, onSelect, selectedEdgeId, onEdgeClick, showLabels, onNodeClick, selectedNodeId, onAdoptTarget, mode }: Props) {
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  if (!visible || !graph) return null;

  // Stroke widths scaled to page resolution so lines look like the original P&ID
  // line weight (≈1–1.5px on screen) rather than a bold overlay.
  // sw ≈ 6.7 at natural.w=8000 → edgeWidth ≈ 6.7 SVG units ≈ 1px at 1200px display.
  // Fixed screen-pixel widths — used with vectorEffect="non-scaling-stroke" so
  // lines stay visible at full-page zoom-out (without it, sw/natural.w ≈ 0.7 CSS px
  // at zoom=1, which is invisible). Nodes use SVG-space radius so they scale with
  // zoom (bigger = easier to click when zoomed in).
  const EDGE_PX = 1.5;          // screen pixels, constant regardless of zoom
  const ORPHAN_PX = 1.5;
  const sw = Math.max(0.5, natural.w / 1200);
  const nodeRadius = sw * 2.2;  // still SVG-space so nodes grow when zooming in
  // Clickable target — decoupled from the visible dot. On a large drawing the
  // visible node renders ~2-3px on screen at fit-zoom (too small to click, so
  // type-B nodes can't be reached for adoption). A transparent hit circle gives
  // a usable target. sw = natural.w/1200, so an sw-relative radius cancels
  // natural.w → the hit area is a roughly CONSTANT on-screen size across jobs
  // regardless of page resolution (~14px diameter at a ~900px-wide canvas).
  const hitRadius = Math.max(nodeRadius, sw * 12);

  // Graph coords live in the page-image space the pipeline traced
  // (graph.page_width × page_height). The canvas viewBox is `natural` (a
  // different-resolution render of the same page), so scale graph geometry into
  // the viewBox — otherwise nodes/edges/orphans collapse into a corner. Missing
  // page dims (legacy graphs) → scale 1 (render unscaled, as before).
  const sx = graph.page_width ? natural.w / graph.page_width : 1;
  const sy = graph.page_height ? natural.h / graph.page_height : 1;
  const scaleTransform = sx !== 1 || sy !== 1 ? `scale(${sx},${sy})` : undefined;

  // tag and line-number lookups for edge labels/titles.
  const tagById = new Map<string, string | null>();
  const lineByNodeId = new Map<string, string>();
  for (const n of graph.nodes) {
    tagById.set(n.id, n.tag);
    if (n.line) lineByNodeId.set(n.id, n.line);
  }

  // node lookup for degenerate-polyline fallback (bbox center → straight line).
  const nodeById = new Map<string, (typeof graph.nodes)[0]>();
  for (const n of graph.nodes) nodeById.set(n.id, n);

  // When a node is selected, compute which edges/nodes are connected to it.
  // Connected edges get highlighted; everything else is dimmed to 15% opacity
  // — same behaviour as the digital twin view.
  const connectedEdgeIds = new Set<string>();
  const connectedNodeIds = new Set<string>();
  if (selectedNodeId) {
    for (const e of graph.edges) {
      if (e.source === selectedNodeId || e.target === selectedNodeId) {
        connectedEdgeIds.add(e.id);
        connectedNodeIds.add(e.source);
        connectedNodeIds.add(e.target);
      }
    }
  }

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

  // Split edges: auto edges are in page_width space → need scaleTransform.
  // User-drawn edges are stored in natural.w space (captured from SVG viewBox
  // at draw time) → must NOT be scaled, or they appear displaced by ~12%.
  const autoEdges = graph.edges.filter((e) => e.method !== "user_added");
  const userEdges = graph.edges.filter((e) => e.method === "user_added");

  function renderEdge(e: GraphEdge) {
    const style = styleFor(e.method);
    // User edges are stored normalized (0..1); denormalize to natural.w/h on render.
    // Legacy user edges (raw px, max coord > 2) render as-is for backward compat.
    const isNormUser = e.method === "user_added" && e.polyline.length > 0
      && Math.max(...e.polyline.flat()) <= 2;
    const rawPts = isNormUser
      ? e.polyline.map(([x, y]) => [x * natural.w, y * natural.h])
      : e.polyline;

    // Degenerate polyline: bad data from pipe tracer that could not find a valid path.
    // Do NOT draw these — a straight bbox-center fallback would show false connections
    // between symbols that have no actual pipe between them in the drawing.
    const isDegenerate = rawPts.length < 2 ||
      rawPts.every((p) => p[0] === rawPts[0][0] && p[1] === rawPts[0][1]);
    if (isDegenerate) return null;

    const points = rawPts.map((p) => p.join(",")).join(" ");
    const hovered = hoveredEdge === e.id;
    const isSelected = selectedEdgeId === e.id;
    const srcTag = tagById.get(e.source) ?? e.source;
    const tgtTag = tagById.get(e.target) ?? e.target;
    const edgeHandlers = onEdgeClick ? {
      onMouseEnter: () => setHoveredEdge(e.id),
      onMouseLeave: () => setHoveredEdge((h: string | null) => (h === e.id ? null : h)),
      onClick: (ev: React.MouseEvent) => { ev.stopPropagation(); onEdgeClick(e.id, e.method); },
    } : {};

    // Node-selection highlight: connected edges bright cyan, others dimmed to 12%.
    // Use cyan (#00d4ff) not white — white is invisible on light P&ID backgrounds.
    const nodeSelActive = !!selectedNodeId;
    const isConnected = nodeSelActive && connectedEdgeIds.has(e.id);
    const edgeOpacity = nodeSelActive ? (isConnected ? 1 : 0.12) : 1;
    const edgeStroke = isSelected ? "#ffffff" : isConnected ? "#00d4ff" : style.color;
    const edgeWidth = isSelected ? EDGE_PX * 3 : isConnected ? EDGE_PX * 3 : hovered ? EDGE_PX * 2 : EDGE_PX;

    // Line label: prefer source node's line number, fall back to target's.
    const lineLabel = lineByNodeId.get(e.source) ?? lineByNodeId.get(e.target) ?? null;
    const mid = rawPts.length > 0 ? rawPts[Math.floor(rawPts.length / 2)] : null;

    return (
      <g key={`gedge-${e.id}`} opacity={edgeOpacity}>
        <polyline
          data-graph-edge={e.id}
          data-method={e.method}
          points={points}
          fill="none"
          stroke={edgeStroke}
          markerEnd={e.directed ? `url(#${markerIdFor(e.method)})` : undefined}
          strokeWidth={edgeWidth}
          vectorEffect="non-scaling-stroke"
          strokeDasharray={style.dashed ? `${EDGE_PX * 4} ${EDGE_PX * 3}` : undefined}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ pointerEvents: "none" }}
        >
          <title>{`${srcTag} → ${tgtTag} (${e.method})`}</title>
        </polyline>
        {/* Wide invisible hit area — only active in select mode (onEdgeClick defined).
            pointer-events:none when onEdgeClick is absent so draw-edge clicks
            pass through to the SVG without being intercepted. */}
        <polyline
          data-graph-edge-hit={e.id}
          points={points}
          fill="none"
          stroke="transparent"
          strokeWidth={EDGE_PX * 5}
          vectorEffect="non-scaling-stroke"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ pointerEvents: mode === "draw-edge" ? "none" : (onEdgeClick ? "stroke" : "none"), cursor: mode === "draw-edge" ? "crosshair" : (onEdgeClick ? "pointer" : "default") }}
          {...edgeHandlers}
        />
        {lineLabel && mid && (
          <text
            x={mid[0]}
            y={mid[1] - EDGE_PX * 1.5}
            fontSize={EDGE_PX * 3.5}
            fill={edgeStroke}
            fillOpacity={0.85}
            stroke="rgba(0,0,0,0.55)"
            strokeWidth={EDGE_PX * 0.5}
            paintOrder="stroke"
            textAnchor="middle"
            vectorEffect="non-scaling-stroke"
            style={{ pointerEvents: "none", userSelect: "none" }}
          >
            {lineLabel}
          </text>
        )}
      </g>
    );
  }

  return (
    <g data-graph-layer="true">
      <defs>{markerDefs}</defs>

      {/* Auto-detected content: orphan lines + auto edges + nodes.
          These coords live in page_width space → apply scaleTransform. */}
      <g data-graph-content="true" transform={scaleTransform}>
      {/* Orphan lines FIRST (lowest layer).
          Solid orphans (from graph resolver) → amber dashed.
          Dashed orphans (from line_detector is_dashed=true) → purple dashed
          to visually distinguish instrument/signal lines from pipe segments. */}
      {!selectedNodeId && (graph.orphan_lines ?? []).map((o, i) => {
        if (!o.polyline || o.polyline.length < 2) return null;
        // Skip degenerate / near-zero-length segments (< 20px in page space).
        // topology.json contains many 1-5px stub artifacts from HoughLinesP
        // noise; rendering them as sub-pixel dots adds clutter, not information.
        const p0 = o.polyline[0], pN = o.polyline[o.polyline.length - 1];
        const segLen = Math.sqrt((pN[0]-p0[0])**2 + (pN[1]-p0[1])**2);
        if (segLen < 20) return null;
        const points = o.polyline.map((p) => p.join(",")).join(" ");
        const isDashed = o.is_dashed === true;
        const strokeColor = isDashed ? "var(--qong-purple, #C73FBE)" : ORPHAN_COLOR;
        const dash = isDashed
          ? `${ORPHAN_PX * 3} ${ORPHAN_PX * 2}`
          : `${ORPHAN_PX * 2} ${ORPHAN_PX * 2}`;
        return (
          <polyline
            key={`gorphan-${i}`}
            data-orphan={i}
            data-graph-orphan="true"
            data-is-dashed={isDashed ? "true" : undefined}
            points={points}
            fill="none"
            stroke={strokeColor}
            strokeOpacity={0.65}
            strokeWidth={ORPHAN_PX}
            vectorEffect="non-scaling-stroke"
            strokeDasharray={dash}
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ pointerEvents: "none" }}
          >
            <title>{isDashed
              ? `Dashed line (instrument/signal) — detected pipe segment`
              : `Unconnected pipe segment — draw an edge to connect${o.reason ? ` (${o.reason})` : ""}`}
            </title>
          </polyline>
        );
      })}

      {/* Auto edges (opencv / llm_fallback) — in page_width space, scaled. */}
      {autoEdges.map(renderEdge)}

      {/* Nodes — small solid colored dots at each node's bbox center.
          Color by entity class: valve=green, instrument=blue, equipment=purple,
          symbol=pink, unmatched=amber, unknown=slate. No hollow rings. */}
      {graph.nodes.map((n) => {
        if (!n.bbox || n.bbox.length !== 4) return null;
        const [x1, y1, x2, y2] = n.bbox;
        const cx = (x1 + x2) / 2;
        const cy = (y1 + y2) / 2;
        const pw = graph.page_width || natural.w;
        const ph = graph.page_height || natural.h;
        if (cy / ph < 0.08 || cx / pw < 0.07) return null;
        const unmatched = isUnmatched(n.id, n.entity_id);
        const dotColor = nodeColorFor(n.class);
        const isSelectedNode = selectedNodeId === n.id;
        const label = n.tag ?? n.class ?? n.id;
        const fontSize = sw * 3.5;
        // Node-corrections (2026-06-28): rejected nodes are NOT hidden — they
        // render ghosted (low opacity + a red "removed" cross) so the soft-reject
        // is visible and reversible via the Properties-panel Restore action.
        const rejected = n.rejected === true;
        // User-added nodes get a dashed ring so they read as user-authored,
        // matching the dashed outline used for user annotations on the canvas.
        const userAdded = n.source === "user";
        // Dim nodes not connected to the selected node (mirrors digital twin behaviour).
        const baseOpacity = selectedNodeId
          ? (isSelectedNode || connectedNodeIds.has(n.id) ? 1 : 0.12)
          : 1;
        const nodeOpacity = rejected ? Math.min(baseOpacity, 0.35) : baseOpacity;
        return (
          <g
            key={`gnode-${n.id}`}
            opacity={nodeOpacity}
            style={{ pointerEvents: "auto", cursor: "pointer" }}
            onMouseEnter={() => setHoveredNodeId(n.id)}
            onMouseLeave={() => setHoveredNodeId((h) => (h === n.id ? null : h))}
            onClick={(ev) => {
              ev.stopPropagation();
              // In draw-edge mode the svg-level press/release owns connections
              // (drag-to-connect, with auto-adopt); a node click must NOT select
              // or open the adopt panel, or it would fight the draw gesture.
              if (mode === "draw-edge") return;
              if (onNodeClick) onNodeClick(n.id);
              if (n.entity_id) {
                onSelect(n.entity_id as string, n.class ?? undefined);
              } else if (onAdoptTarget) {
                // type-B node: no entity_id — route to adopt flow
                onAdoptTarget(n);
              }
            }}
          >
            {/* Transparent enlarged hit target so tiny on-screen nodes (large
                drawings render dots ~2-3px at fit-zoom) stay clickable. Behind
                the visible dot; same onClick on the parent <g> handles it. */}
            <circle
              cx={cx}
              cy={cy}
              r={hitRadius}
              fill="transparent"
              stroke="none"
              style={{ pointerEvents: "auto" }}
            />
            <circle
              data-graph-node={n.id}
              data-unmatched={unmatched ? "true" : undefined}
              data-node-source={n.source ?? "auto"}
              data-rejected={rejected ? "true" : undefined}
              cx={cx}
              cy={cy}
              r={nodeRadius}
              fill={rejected ? "#9CA3AF" : dotColor}
              fillOpacity={rejected ? 0.4 : unmatched ? 0.55 : 0.92}
              stroke={userAdded && !rejected ? "var(--qong-pink, #FF4DA8)" : "#000000"}
              strokeWidth={userAdded && !rejected ? sw * 0.7 : sw * 0.3}
              strokeOpacity={userAdded && !rejected ? 0.9 : 0.25}
              strokeDasharray={userAdded && !rejected ? `${sw} ${sw * 0.8}` : undefined}
            >
              <title>
                {rejected
                  ? `${label} — removed (click, then Restore to undo)`
                  : userAdded
                    ? `${label} — added by you`
                    : unmatched
                      ? `${label} — detected but not linked to any pipe`
                      : label}
              </title>
            </circle>
            {/* "removed" cross over rejected nodes (red X), so the ghosting reads
                as an explicit removal rather than just a dimmed dot. */}
            {rejected && (
              <g style={{ pointerEvents: "none" }} stroke="#EF4444" strokeWidth={sw * 0.8} strokeLinecap="round">
                <line x1={cx - nodeRadius} y1={cy - nodeRadius} x2={cx + nodeRadius} y2={cy + nodeRadius} />
                <line x1={cx - nodeRadius} y1={cy + nodeRadius} x2={cx + nodeRadius} y2={cy - nodeRadius} />
              </g>
            )}
            {/* Tag label */}
            {showLabels && (
              <text
                x={cx + nodeRadius * 1.4}
                y={cy + fontSize * 0.35}
                fontSize={fontSize}
                fill="#ffffff"
                stroke="#000000"
                strokeWidth={sw * 0.6}
                paintOrder="stroke"
                fontFamily="monospace"
                style={{ pointerEvents: "none", userSelect: "none" }}
              >
                {label.length > 14 ? label.slice(0, 13) + "…" : label}
              </text>
            )}
            {/* Cardinal connection anchors — draw.io-style, visible only on hover. */}
            {hoveredNodeId === n.id && (
              [[cx, y1], [x2, cy], [cx, y2], [x1, cy]].map(([ax, ay], i) => (
                <circle
                  key={`anchor-${n.id}-${i}`}
                  data-anchor={n.id}
                  cx={ax}
                  cy={ay}
                  r={sw * 2.5}
                  fill="#fff"
                  stroke="#2563eb"
                  strokeWidth={sw * 0.6}
                  style={{ pointerEvents: "auto", cursor: "crosshair" }}
                />
              ))
            )}
          </g>
        );
      })}
      </g>

      {/* User-drawn edges — stored in natural.w SVG space, NO scaleTransform.
          Rendering them inside the scaleTransform group would displace them by
          (natural.w / page_width - 1) × coord, e.g. 12% for 8000/7146. */}
      {userEdges.map(renderEdge)}
    </g>
  );
}
