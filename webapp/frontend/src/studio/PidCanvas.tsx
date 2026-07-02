import { useEffect, useMemo, useRef, useState } from "react";
import type { DetectionItem } from "./api";
import type { GraphNode, JobGraph } from "./types";
import GraphLayer from "./GraphLayer";
import { resolveEndpoint, connectEndpoints, type ResolvedEndpoint } from "./connect";
import { canvasDisplayLabel, displayNameForModelLabel } from "./labelMap";
import { PidGlyphAt, labelToSymKind, subClassToSymKind } from "./PidSymbol";
import { colorForKind, colorForSubClass } from "./paletteColors";

interface PidElement {
  id: string;
  type: "block-valve" | "instrument" | "pump" | "valve" | "exchanger";
  x: number;
  y: number;
  w?: number;
  h?: number;
  r?: number;
  label: string;
  sub?: string;
  warn?: boolean;
}

interface PidEdge {
  from: [number, number];
  to: [number, number];
  kind: "ok" | "warn" | "warn-dashed";
}

const ELEMENTS: PidElement[] = [
  { id: "V-101", type: "block-valve", x: 200, y: 80, w: 60, h: 32, label: "V-101" },
  { id: "FT-101", type: "instrument", x: 410, y: 96, r: 22, label: "FT", sub: "101" },
  { id: "P-101", type: "pump", x: 230, y: 230, r: 26, label: "P-101" },
  { id: "PV-203", type: "valve", x: 380, y: 230, r: 20, label: "PV", sub: "203", warn: true },
  { id: "E-104", type: "exchanger", x: 520, y: 218, w: 70, h: 32, label: "E-104" },
];

const EDGES: PidEdge[] = [
  { from: [260, 96], to: [388, 96], kind: "ok" },
  { from: [200, 96], to: [200, 230], kind: "ok" },
  { from: [200, 230], to: [204, 230], kind: "ok" },
  { from: [256, 230], to: [360, 230], kind: "warn" },
  { from: [400, 230], to: [520, 230], kind: "warn-dashed" },
];

// ── User-annotation + edge types shared with Phase 3+4 overlays ────────────────
// Kept minimal here; Phase 3/4 add api.ts modules with the full shapes. The
// canvas only needs the rendering-relevant fields.

export interface UserAnnotationLite {
  entity_id: string;
  status: "model_found" | "user_added" | "user_confirmed" | "user_rejected";
  source: "model" | "user";
  entity_class: string;
  sub_class: string | null;
  bbox: [number, number, number, number]; // page-pixel coords (POST already translates)
  sheet_number: number;
  placeholder_tag?: string | null;
  tag?: string | null;
}

export type LineType = "process_pipe" | "instrument" | "signal" | "interlock" | "plain_pipe";

export interface EdgeLite {
  edge_id: string;
  source: "opencv" | "llm_fallback" | "user";
  status: "model_found" | "user_added" | "user_confirmed" | "user_rejected";
  line_type: LineType;
  relation_type?: string | null;
  source_entity_id: string;
  target_entity_id: string;
  polyline: Array<[number, number]>;
  sheet_number: number;
  group_id?: string | null;
  directed?: boolean;
}

export type CanvasMode = "select" | "mark-symbol" | "draw-edge";

// ── Theme tokens — keep colors in sync with design/tokens.css ──────────────────
// Status colors for annotation bboxes.
const STATUS_STROKE = {
  model_found: "#3B82F6",     // --info — calm
  user_added: "#FF4DA8",      // --qong-pink — user signal
  user_confirmed: "#10B981",  // --ok — validated
  user_rejected: "#EF4444",   // --error
} as const;

// Per-line-type stroke style (matches the spec's theme mapping table).
// plain_pipe is orange so user-drawn pipes are immediately distinguishable from the P&ID background.
const LINE_STYLE: Record<LineType, { color: string; dash: string; width: number }> = {
  plain_pipe:   { color: "#F97316", dash: "0",       width: 1.6 },  // orange — user-drawn pipe
  process_pipe: { color: "#22D3EE", dash: "0",       width: 2.4 },  // --scan-cyan solid
  instrument:   { color: "#FF4DA8", dash: "8 4",     width: 2.0 },  // --qong-pink dashed
  signal:       { color: "#C73FBE", dash: "14 6",    width: 2.0 },  // --qong-purple long-dash
  interlock:    { color: "#F59E0B", dash: "4 4 1 4", width: 2.0 },  // --warn dash-dot
};

// Constant CSS pixel width for user-drawn edges (same approach as GraphLayer's EDGE_PX).
// vectorEffect="non-scaling-stroke" makes this CSS pixels regardless of SVG zoom.
const USER_EDGE_PX = 2;

// ── Tile geometry — mirrors pdf_to_tiles.py defaults ─────────────────────────
// MUST match pdf_to_tiles.pdf_to_tiles defaults (3x3 grid, 20% overlap). If
// you ever change those defaults, change BOTH ends in the same PR.
const GRID_ROWS = 3;
const GRID_COLS = 3;
const OVERLAP_PCT = 0.20;

interface TileBox { x0: number; y0: number; x1: number; y1: number; }

/**
 * Compute per-tile (x0, y0, x1, y1) offset into the full-page image, given the
 * full-page image's natural dimensions. Mirrors the math in
 * `pdf_to_tiles.pdf_to_tiles`. Keyed by tile filename like "tile_p0_r1_c2.png".
 */
export function computeTileOffsets(
  natural: { w: number; h: number },
  pageIndex: number,
): Map<string, TileBox> {
  const W = natural.w;
  const H = natural.h;
  const tileW = Math.ceil(W / GRID_COLS);
  const tileH = Math.ceil(H / GRID_ROWS);
  const overlapX = Math.floor(tileW * OVERLAP_PCT);
  const overlapY = Math.floor(tileH * OVERLAP_PCT);
  const out = new Map<string, TileBox>();
  for (let r = 0; r < GRID_ROWS; r++) {
    for (let c = 0; c < GRID_COLS; c++) {
      const x0 = Math.max(0, c * tileW - overlapX);
      const y0 = Math.max(0, r * tileH - overlapY);
      const x1 = Math.min(W, (c + 1) * tileW + overlapX);
      const y1 = Math.min(H, (r + 1) * tileH + overlapY);
      out.set(`tile_p${pageIndex}_r${r}_c${c}.png`, { x0, y0, x1, y1 });
    }
  }
  return out;
}

/**
 * Translate a tile-local bbox into page-pixel coords using the tile's offset.
 * Returns null if the tile is unknown.
 */
function tileBboxToPage(
  bbox: number[],
  tileFilename: string,
  offsets: Map<string, TileBox>,
): [number, number, number, number] | null {
  const off = offsets.get(tileFilename);
  if (!off) return null;
  const [x1, y1, x2, y2] = bbox;
  return [x1 + off.x0, y1 + off.y0, x2 + off.x0, y2 + off.y0];
}

interface Props {
  selectedId: string;
  onSelect: (id: string, entityClass?: string) => void;
  zoom: number;
  setZoom: React.Dispatch<React.SetStateAction<number>>;
  pan: { x: number; y: number };
  setPan: React.Dispatch<React.SetStateAction<{ x: number; y: number }>>;
  dark: boolean;
  /** Full-page render of the active sheet (FEATURES #38). When provided, the
   *  canvas renders the whole page and shows ALL detections (no per-tile
   *  filter), translating tile-local bboxes into page-pixel coords. This is
   *  the new default surface; tileImageUrl is kept as a fallback for jobs
   *  that don't have a full-page render yet (legacy / brand-new uploads). */
  pageFullUrl?: string | null;
  /** Page index of the active sheet (0-based). Needed to compute tile-filename
   *  → page-offset mapping correctly for multi-page PDFs. */
  pageIndex?: number;
  /** Legacy: single tile image. Used when pageFullUrl is absent. */
  tileImageUrl?: string | null;
  tileFilename?: string | null;
  detections?: DetectionItem[];
  valveCount?: number;
  valveCountTotal?: number;
  /** Canvas interaction mode. Phase 3+4 wiring lives in subcomponents; for
   *  now this only affects cursor + bbox click affordance. */
  mode?: CanvasMode;
  /** User-placed marks to overlay (Phase 3). Bboxes here are already in
   *  page-pixel coords. */
  userAnnotations?: UserAnnotationLite[];
  /** Edges to overlay (Phase 4). Polylines in page-pixel coords. */
  edges?: EdgeLite[];
  /** Mark drop callback (Phase 3). Bbox is in page-pixel coords. */
  onDropMark?: (bbox: [number, number, number, number], sub_class: string, entity_class: string, bboxNorm?: [number, number, number, number]) => void;
  /** Edge-drawn callback (Phase 4). Polyline in page-pixel coords. */
  onEdgeDrawn?: (
    source_entity_id: string,
    target_entity_id: string,
    polyline: Array<[number, number]>,
    line_type: LineType,
  ) => void;
  /** Selected line type for draw-edge mode (Phase 4). */
  activeLineType?: LineType;
  /** Selected entity class + sub_class for mark-symbol mode (Phase 3). */
  activeMarkClass?: { entity_class: string; sub_class: string } | null;
  /** Auto-extracted process graph (Stream 3). Null when none is available. */
  graph?: JobGraph | null;
  /** Whether the graph overlay layer is toggled on. */
  showGraph?: boolean;
  /** Currently selected graph edge id (for delete highlight). */
  selectedGraphEdgeId?: string | null;
  /** Called when user clicks a graph edge — passes (edgeId, method). */
  onGraphEdgeClick?: (edgeId: string, method: string) => void;
  /** Called when user clicks a graph node — passes node id. */
  onGraphNodeClick?: (nodeId: string) => void;
  /** Currently selected graph node id (for ring highlight). */
  selectedGraphNodeId?: string | null;
  /** Called when user clicks a type-B graph node (entity_id == null) — adopt flow. */
  onAdoptTarget?: (node: GraphNode) => void;
  /** Adopt a type-B node mid-edge-draw; resolves to the new entity_id (or null
   *  on failure). Used by draw-edge auto-adopt-on-connect. */
  onAdoptForConnect?: (node: GraphNode) => Promise<string | null>;
  /** Show ALL element labels at once. Default (false) = labels only on the
   *  hovered/selected element, so dense drawings stay readable. */
  showAllLabels?: boolean;
  /** Resolution the detection tile-coords are in (page_0_full.png). The canvas
   *  renders the page at a different (zoom-dependent) width, so detection coords
   *  must be rescaled by render_w/tilingWidth. Null → no rescale (legacy). */
  tilingWidth?: number | null;
  tilingHeight?: number | null;
  /** Called once when the full-page image loads, providing its natural dimensions.
   *  Studio uses this to compute pan-to coordinates for sidebar → canvas sync. */
  onNaturalSize?: (w: number, h: number) => void;
  /** Job ID — passed to TileWithOverlay so it can fetch topology lines. */
  jobId?: number;
  /** All entity_ids matching the current search query (dim cyan border on canvas). */
  searchHighlightIds?: string[];
  /** The entity_id the user most recently jumped to (sonar-ping ring on canvas). */
  searchActiveId?: string | null;
  /** Increments on every jump to re-trigger the CSS sonar animation. */
  searchJumpKey?: number;
  /** True while the job's sheets/page render are still being fetched. Shows a
   *  loader instead of the legacy prototype P&ID ("sample PID") flash. */
  loading?: boolean;
  /** Called when user clicks a YOLO detection that has an OCR-read tag but no
   *  canonical entity match. Gives the sidebar a chance to show a minimal info
   *  panel rather than silently eating the click. */
  onOrphanSelect?: (tag: string, label: string) => void;
}

export default function PidCanvas({
  selectedId,
  onSelect,
  zoom,
  setZoom,
  pan,
  setPan,
  dark,
  pageFullUrl,
  pageIndex = 0,
  tileImageUrl,
  tileFilename,
  detections,
  valveCount: _valveCount,
  valveCountTotal: _valveCountTotal,
  mode = "select",
  userAnnotations,
  edges,
  onDropMark,
  onEdgeDrawn,
  activeLineType = "process_pipe",
  activeMarkClass,
  graph,
  showGraph,
  showAllLabels,
  selectedGraphEdgeId,
  onGraphEdgeClick,
  onGraphNodeClick,
  selectedGraphNodeId,
  onAdoptTarget,
  onAdoptForConnect,
  tilingWidth,
  tilingHeight,
  onNaturalSize,
  jobId,
  searchHighlightIds,
  searchActiveId,
  searchJumpKey,
  loading,
  onOrphanSelect,
}: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [animated, setAnimated] = useState(true);
  // Single timer ref — cleared on every wheel event so the "animated" class
  // only re-enables once after scrolling truly stops, preventing mid-scroll
  // transitions that make cursor-anchored zoom feel offset.
  const animTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pannedRef = useRef(false);
  // Refs so the wheel handler always sees the latest zoom/pan without
  // re-registering the native event listener on every state change.
  const zoomRef = useRef(zoom);
  const panRef = useRef(pan);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);
  useEffect(() => { panRef.current = pan; }, [pan]);

  // Available canvas size, tracked so PageWithOverlays can size the page at
  // fit×zoom in real CSS pixels (FEATURES #43 v2 — see note below). Zoom used
  // to be a CSS transform:scale() which upscaled a fit-sized raster (~656px)
  // and threw away the hi-DPI source → blur. Sizing the <img> by layout makes
  // the browser sample the full-res source at the zoomed size → crisp.
  const [avail, setAvail] = useState<{ w: number; h: number } | null>(null);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setAvail({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const elFill = dark ? "#0E1024" : "#ffffff";
  const elStroke = dark ? "rgba(255,255,255,0.65)" : "rgba(20,22,42,0.55)";
  const elText = dark ? "#ffffff" : "#14162A";
  const subText = dark ? "#9498AE" : "#6B6F8A";
  const gridStroke = dark ? "#ffffff" : "#14162A";
  const gridOp = dark ? 0.04 : 0.06;
  const legendText = dark ? "#9498AE" : "#6B6F8A";

  function onMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if ((e.target as HTMLElement).closest("g[data-elid]")) return;
    if ((e.target as HTMLElement).closest("[data-canvas-interactive]")) return;
    if (e.button !== 0) return;
    e.preventDefault();
    pannedRef.current = false;
    const startX = e.clientX;
    const startY = e.clientY;
    const start = { ...pan };
    setAnimated(false);
    wrapRef.current?.classList.add("panning");
    const move = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) pannedRef.current = true;
      setPan({ x: start.x + dx, y: start.y + dy });
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      wrapRef.current?.classList.remove("panning");
      setTimeout(() => setAnimated(true), 0);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setAnimated(false);
      // Cancel any pending re-enable timer so the transition doesn't kick in
      // mid-scroll (which would make the cursor-anchored zoom feel offset).
      if (animTimerRef.current !== null) clearTimeout(animTimerRef.current);
      const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
      // Read from refs — but also write back immediately so rapid scroll events
      // (multiple events before React re-renders) compound correctly instead of
      // all reading the same stale value and producing only one zoom step.
      const z = zoomRef.current;
      const p = panRef.current;
      const newZ = Math.max(0.3, Math.min(6, z * factor));
      const realFactor = newZ / z;
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const newPan = { x: cx - (cx - p.x) * realFactor, y: cy - (cy - p.y) * realFactor };
      // Write accumulators back immediately so the next wheel event in the same
      // frame reads the already-updated values, not the pre-render stale ones.
      zoomRef.current = newZ;
      panRef.current = newPan;
      setZoom(newZ);
      setPan(newPan);
      animTimerRef.current = setTimeout(() => setAnimated(true), 200);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setZoom, setPan]);

  const clickGuard = (cb: () => void) => () => {
    if (!pannedRef.current) cb();
  };

  // Mode selection: page-full > tile > prototype SVG. Phase 2 made page-full
  // the new default; tile mode lingers for legacy data.
  const useFullPage = !!pageFullUrl;
  const useTile = !useFullPage && !!tileImageUrl;
  const useProto = !useFullPage && !useTile;

  return (
    <div ref={wrapRef} className="canvas-wrap" onMouseDown={onMouseDown}>
      <div
        ref={innerRef}
        className={`canvas-inner ${animated ? "animated" : ""}`}
        // Full-page mode zooms via layout sizing (crisp — FEATURES #43 v2), so
        // only translate (pan) goes on the transform. Legacy tile/proto modes
        // still zoom via transform:scale.
        style={{ transform: `translate(${pan.x}px, ${pan.y}px)${useFullPage ? "" : ` scale(${zoom})`}` }}
      >
        {useFullPage && (
          <PageWithOverlays
            pageFullUrl={pageFullUrl!}
            zoom={zoom}
            avail={avail}
            pageIndex={pageIndex}
            detections={detections ?? []}
            userAnnotations={userAnnotations ?? []}
            edges={edges ?? []}
            onSelect={onSelect}
            selectedId={selectedId}
            mode={mode}
            onDropMark={onDropMark}
            onEdgeDrawn={onEdgeDrawn}
            activeLineType={activeLineType}
            activeMarkClass={activeMarkClass}
            dark={dark}
            graph={graph ?? null}
            showGraph={!!showGraph}
            showAllLabels={!!showAllLabels}
            selectedGraphEdgeId={selectedGraphEdgeId ?? null}
            onGraphEdgeClick={onGraphEdgeClick}
            onGraphNodeClick={onGraphNodeClick}
            selectedGraphNodeId={selectedGraphNodeId ?? null}
            onAdoptTarget={onAdoptTarget}
            onAdoptForConnect={onAdoptForConnect}
            tilingWidth={tilingWidth ?? null}
            tilingHeight={tilingHeight ?? null}
            onNaturalSize={onNaturalSize}
            searchHighlightIds={searchHighlightIds ?? []}
            searchActiveId={searchActiveId ?? null}
            searchJumpKey={searchJumpKey ?? 0}
            onOrphanSelect={onOrphanSelect}
          />
        )}
        {useTile && (
          <TileWithOverlay
            tileImageUrl={tileImageUrl!}
            tileFilename={tileFilename ?? null}
            detections={detections ?? []}
            onSelect={onSelect}
            selectedId={selectedId}
            jobId={jobId}
            onOrphanSelect={onOrphanSelect}
          />
        )}
        {/* While the job's sheets/page render are loading, show a loader — NOT
            the legacy prototype P&ID below (which flashed as a "sample" drawing
            for ~2s on refresh). The prototype only renders for genuinely empty
            jobs once loading has settled. */}
        {useProto && loading && (
          <div className="canvas-loader" role="status" aria-live="polite">
            <div className="canvas-loader-spinner" />
            <span className="canvas-loader-text">Loading drawing…</span>
          </div>
        )}
        {useProto && !loading && (
          <svg viewBox="0 0 700 360" className="pid-svg">
            <defs>
              <pattern id="canvas-grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke={gridStroke} strokeOpacity={gridOp} strokeWidth="0.6" />
              </pattern>
            </defs>
            <rect x="0" y="0" width="700" height="360" fill="url(#canvas-grid)" />

            {EDGES.map((e, i) => {
              const stroke = e.kind === "ok" ? "#22D3EE" : "#F59E0B";
              const dash = e.kind.includes("dashed") ? "6 4" : "0";
              return (
                <g key={i}>
                  <line
                    x1={e.from[0]}
                    y1={e.from[1]}
                    x2={e.to[0]}
                    y2={e.to[1]}
                    stroke={stroke}
                    strokeWidth="1.8"
                    strokeDasharray={dash}
                  />
                  {e.kind === "ok" && (
                    <polygon
                      points={`${e.to[0]},${e.to[1]} ${e.to[0] - 6},${e.to[1] - 4} ${e.to[0] - 6},${e.to[1] + 4}`}
                      fill={stroke}
                    />
                  )}
                </g>
              );
            })}

            {ELEMENTS.map((el) => {
              const sel = selectedId === el.id;
              const stroke = el.warn ? "#F59E0B" : sel ? "#FF4DA8" : elStroke;
              const ringStroke = sel ? "#FF4DA8" : "transparent";

              if (el.type === "instrument" || el.type === "valve") {
                const r = el.r ?? 20;
                return (
                  <g
                    key={el.id}
                    data-elid={el.id}
                    onMouseUp={clickGuard(() => onSelect(el.id))}
                    style={{ cursor: "pointer" }}
                  >
                    {sel && (
                      <circle cx={el.x} cy={el.y} r={r + 6} fill="none" stroke={ringStroke} strokeWidth="1.3" strokeDasharray="3 3" />
                    )}
                    <circle cx={el.x} cy={el.y} r={r} fill={elFill} stroke={stroke} strokeWidth="1.8" />
                    <line x1={el.x - r * 0.85} y1={el.y} x2={el.x + r * 0.85} y2={el.y} stroke={stroke} strokeWidth="0.8" />
                    <text x={el.x} y={el.y - 2} textAnchor="middle" fontSize="9" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={el.warn ? "#F59E0B" : elText}>{el.label}</text>
                    <text x={el.x} y={el.y + 9} textAnchor="middle" fontSize="9" fontFamily="JetBrains Mono, monospace" fontWeight="500" fill={el.warn ? "#F59E0B" : subText}>{el.sub}</text>
                  </g>
                );
              }

              if (el.type === "pump") {
                const r = el.r ?? 24;
                return (
                  <g key={el.id} data-elid={el.id} onMouseUp={clickGuard(() => onSelect(el.id))} style={{ cursor: "pointer" }}>
                    {sel && (
                      <circle cx={el.x} cy={el.y} r={r + 5} fill="none" stroke={ringStroke} strokeWidth="1.3" strokeDasharray="3 3" />
                    )}
                    <circle cx={el.x} cy={el.y} r={r} fill={elFill} stroke={stroke} strokeWidth="1.8" />
                    <polygon points={`${el.x - r * 0.7},${el.y - r * 0.7} ${el.x + r * 0.7},${el.y} ${el.x - r * 0.7},${el.y + r * 0.7}`} fill="none" stroke={stroke} strokeWidth="1.3" />
                    <text x={el.x} y={el.y + r + 12} textAnchor="middle" fontSize="9" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={subText}>{el.label}</text>
                  </g>
                );
              }

              const w = el.w ?? 60;
              const h = el.h ?? 32;
              return (
                <g key={el.id} data-elid={el.id} onMouseUp={clickGuard(() => onSelect(el.id))} style={{ cursor: "pointer" }}>
                  {sel && (
                    <rect x={el.x - w / 2 - 4} y={el.y - h / 2 - 4} width={w + 8} height={h + 8} fill="none" stroke={ringStroke} strokeWidth="1.3" strokeDasharray="3 3" rx="4" />
                  )}
                  <rect x={el.x - w / 2} y={el.y - h / 2} width={w} height={h} fill={elFill} stroke={stroke} strokeWidth="1.8" rx="2" />
                  {el.type === "exchanger" && (
                    <>
                      <line x1={el.x - w / 2 + 6} y1={el.y - h / 2 + 6} x2={el.x + w / 2 - 6} y2={el.y - h / 2 + 6} stroke={stroke} strokeWidth="0.8" />
                      <line x1={el.x - w / 2 + 6} y1={el.y + h / 2 - 6} x2={el.x + w / 2 - 6} y2={el.y + h / 2 - 6} stroke={stroke} strokeWidth="0.8" />
                    </>
                  )}
                  <text x={el.x} y={el.y + 3} textAnchor="middle" fontSize="9" fontFamily="JetBrains Mono, monospace" fontWeight="700" fill={elText}>{el.label}</text>
                </g>
              );
            })}

            <text x={295} y={218} fontSize="7" fontFamily="JetBrains Mono, monospace" fill="#F59E0B" letterSpacing="0.1em">
              direction unsure
            </text>

            <g transform="translate(180, 320)" fontFamily="Outfit, sans-serif" fontSize="9" fill={legendText}>
              <circle cx="0" cy="0" r="3" fill="#22D3EE" />
              <text x="8" y="3">process line</text>
              <circle cx="78" cy="0" r="3" fill="#F59E0B" />
              <text x="86" y="3">low confidence</text>
              <circle cx="172" cy="0" r="3" fill="#FF4DA8" />
              <text x="180" y="3">selected</text>
              <circle cx="232" cy="0" r="3" fill="#EF4444" />
              <text x="240" y="3">orphan node</text>
            </g>
          </svg>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// PageWithOverlays — full-page render with translated bboxes + edges +
// drag-drop hit area. Foundation for Phase 3 (mark-symbol) and Phase 4
// (draw-edge). Phase 2 ships layers 1 (bg image) + 2 (translated detections).
// ────────────────────────────────────────────────────────────────────────────

function PageWithOverlays({
  pageFullUrl,
  zoom,
  avail,
  pageIndex,
  detections,
  userAnnotations,
  edges,
  onSelect,
  selectedId,
  mode,
  onDropMark,
  onEdgeDrawn,
  activeLineType,
  activeMarkClass,
  dark,
  graph,
  showGraph,
  showAllLabels,
  selectedGraphEdgeId,
  onGraphEdgeClick,
  onGraphNodeClick,
  selectedGraphNodeId,
  onAdoptTarget,
  onAdoptForConnect,
  tilingWidth,
  tilingHeight,
  onNaturalSize,
  searchHighlightIds,
  searchActiveId,
  searchJumpKey,
  onOrphanSelect,
}: {
  pageFullUrl: string;
  zoom: number;
  avail: { w: number; h: number } | null;
  pageIndex: number;
  detections: DetectionItem[];
  userAnnotations: UserAnnotationLite[];
  edges: EdgeLite[];
  onSelect: (id: string, entityClass?: string) => void;
  selectedId: string;
  mode: CanvasMode;
  onDropMark?: (bbox: [number, number, number, number], sub_class: string, entity_class: string, bboxNorm?: [number, number, number, number]) => void;
  onEdgeDrawn?: (
    source_entity_id: string,
    target_entity_id: string,
    polyline: Array<[number, number]>,
    line_type: LineType,
  ) => void;
  activeLineType: LineType;
  activeMarkClass: { entity_class: string; sub_class: string } | null | undefined;
  dark: boolean;
  graph: JobGraph | null;
  showGraph: boolean;
  showAllLabels: boolean;
  selectedGraphEdgeId?: string | null;
  onGraphEdgeClick?: (edgeId: string, method: string) => void;
  onGraphNodeClick?: (nodeId: string) => void;
  selectedGraphNodeId?: string | null;
  onAdoptTarget?: (node: GraphNode) => void;
  onAdoptForConnect?: (node: GraphNode) => Promise<string | null>;
  tilingWidth: number | null;
  tilingHeight: number | null;
  onNaturalSize?: (w: number, h: number) => void;
  searchHighlightIds: string[];
  searchActiveId: string | null;
  searchJumpKey: number;
  onOrphanSelect?: (tag: string, label: string) => void;
}) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  // Reset skeleton on page/sheet change only. Resolution upgrades (?w=10000 vs
  // ?w=8000) keep imgLoaded=true so the old image stays visible while the new
  // higher-res version loads — no blank flash during zoom-in escalation.
  useEffect(() => { setImgLoaded(false); }, [pageIndex]);
  // Which element's label to show on hover (when not showing all labels).
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  // O(1) lookup for search dim-highlights — rebuilt from the string[] prop.
  const searchHighlightSet = useMemo(
    () => new Set(searchHighlightIds),
    [searchHighlightIds],
  );
  const imgRef = useRef<HTMLImageElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // Cached-image guard. A `<img>` served from (immutable) cache is often
  // already `complete` before React attaches `onLoad`, so the handler never
  // fires — leaving `imgLoaded`/`natural` unset and the detection overlay
  // (gated on `imgLoaded && natural`) blank. This made revisited jobs render
  // the page image but NO detections ("not loading"). Re-sync straight from
  // the element after commit and whenever the source changes; `onLoad` still
  // covers the cold (network) path. Only ever sets state on, so it never
  // fights the resolution-swap behavior above.
  useEffect(() => {
    const img = imgRef.current;
    if (!imgLoaded && img && img.complete && img.naturalWidth > 0) {
      setNatural({ w: img.naturalWidth, h: img.naturalHeight });
      onNaturalSize?.(img.naturalWidth, img.naturalHeight);
      setImgLoaded(true);
    }
  }, [pageFullUrl, imgLoaded, onNaturalSize]);

  // FEATURES #43 v2 — layout-based zoom. Fit the page to the available canvas
  // (object-fit:contain math), then multiply by zoom to get the on-screen size
  // in REAL CSS pixels. Sizing the page box this way (vs transform:scale) makes
  // the browser sample the hi-DPI source at the zoomed size → crisp. Invariant
  // to the source resolution (same aspect), so the Studio `?w` escalation only
  // sharpens, never reflows. Falls back to CSS object-fit until measured.
  const display = useMemo(() => {
    if (!natural || !avail || avail.w <= 0 || avail.h <= 0) return null;
    const s = Math.min(avail.w / natural.w, avail.h / natural.h);
    return { w: natural.w * s * zoom, h: natural.h * s * zoom };
  }, [natural, avail, zoom]);

  // Draw-edge in-flight state. A press starts a draft (source endpoint); a
  // release on another node completes it (drag-to-connect). The same draft also
  // supports the click-source / click-target flow — see onEdgeMouseDown/Up.
  const [edgeDraft, setEdgeDraft] = useState<{
    source: ResolvedEndpoint | null;
    sourcePoint: [number, number] | null;
    cursorPoint: [number, number] | null;
  }>({ source: null, sourcePoint: null, cursorPoint: null });


  // FEATURES #41: mark-symbol mode is now drag-to-create instead of
  // click-drops-a-fixed-bbox. The user surfaces a draggable rectangle that
  // fits the symbol they're labelling, matching the draw.io prototype.
  // null when no drag in progress.
  const [markDraft, setMarkDraft] = useState<{
    x0: number; y0: number; x1: number; y1: number;
  } | null>(null);

  // Tile offsets are computed in the TILING SOURCE resolution (the page_0_full
  // .png the tiles were cut from), because detection bboxes are tile-local in
  // THAT space. The canvas renders the page at a different, zoom-dependent width
  // (`natural`), so we scale the resulting page coord by natural/source below.
  // When tilingWidth is absent (legacy jobs), fall back to `natural` → scale 1,
  // i.e. the previous behavior (no regression).
  const tilingSource = useMemo(() => {
    if (tilingWidth && tilingHeight) return { w: tilingWidth, h: tilingHeight };
    return natural;
  }, [tilingWidth, tilingHeight, natural]);

  const offsets = useMemo(() => {
    if (!tilingSource) return new Map<string, TileBox>();
    return computeTileOffsets(tilingSource, pageIndex);
  }, [tilingSource, pageIndex]);

  // Translate detections to page-pixel coords. Drop those whose tile filename
  // doesn't match any computed offset (would indicate a multi-page mismatch).
  const pageDetections = useMemo(() => {
    if (!natural || !tilingSource) return [];
    // Scale source-space page coords → the canvas viewBox (`natural`). 1 when
    // tilingSource === natural (legacy fallback).
    const sx = natural.w / tilingSource.w;
    const sy = natural.h / tilingSource.h;
    // map first (preserves global index), then filter — _origIdx lets the
    // render loop compute the same key that buildElementsForTile assigned.
    return detections
      .map((d, origIdx) => {
        if (!Array.isArray(d.bbox) || d.bbox.length !== 4 || !d.tile) return null;
        const pbSrc = tileBboxToPage(d.bbox as number[], d.tile as string, offsets);
        const pb = pbSrc
          ? ([pbSrc[0] * sx, pbSrc[1] * sy, pbSrc[2] * sx, pbSrc[3] * sy] as [number, number, number, number])
          : null;
        return pb ? { ...d, pageBbox: pb, _origIdx: origIdx } : null;
      })
      .filter((d): d is NonNullable<typeof d> => d !== null);
  }, [detections, offsets, natural, tilingSource]);

  // Map screen click → page-pixel coords (inverse of SVG viewBox transform).
  function clientToPagePixel(clientX: number, clientY: number): [number, number] | null {
    const svg = svgRef.current;
    if (!svg || !natural) return null;
    const rect = svg.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * natural.w;
    const y = ((clientY - rect.top) / rect.height) * natural.h;
    return [x, y];
  }

  // Mark-symbol mode: **drag-to-create** rectangle, matching the draw.io
  // prototype (FEATURES #41). Drag distance < 5 page-pixels falls through to
  // a click-drop with a sensible default size so a quick tap still works.
  function onCanvasMouseDownForMark(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "mark-symbol" || !activeMarkClass || !onDropMark) return;
    e.preventDefault();
    e.stopPropagation();
    const p0 = clientToPagePixel(e.clientX, e.clientY);
    if (!p0) return;
    const [x0, y0] = p0;
    setMarkDraft({ x0, y0, x1: x0, y1: y0 });

    const onMove = (ev: MouseEvent) => {
      const pt = clientToPagePixel(ev.clientX, ev.clientY);
      if (!pt) return;
      setMarkDraft({ x0, y0, x1: pt[0], y1: pt[1] });
    };
    const onUp = (ev: MouseEvent) => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      const pt = clientToPagePixel(ev.clientX, ev.clientY);
      setMarkDraft(null);
      if (!pt) return;
      let bx0 = Math.min(x0, pt[0]);
      let by0 = Math.min(y0, pt[1]);
      let bx1 = Math.max(x0, pt[0]);
      let by1 = Math.max(y0, pt[1]);
      // Quick-tap fallback (no real drag): emit a small but visible box so the
      // user can still resize it later via the standard select-mode handles.
      if (bx1 - bx0 < 5 && by1 - by0 < 5) {
        bx0 = pt[0] - 30; by0 = pt[1] - 20; bx1 = pt[0] + 30; by1 = pt[1] + 20;
      }
      // Normalized drawn box (0..1 of the source page) for at-mark-time OCR —
      // the user frames the tag, so this crop reads far better than the auto
      // symbol box. natural is the render viewBox; normalize against it.
      const nb: [number, number, number, number] | undefined = natural
        ? [bx0 / natural.w, by0 / natural.h, bx1 / natural.w, by1 / natural.h]
        : undefined;
      onDropMark(
        [bx0, by0, bx1, by1],
        activeMarkClass.sub_class,
        activeMarkClass.entity_class,
        nb,
      );
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  // Draw-edge: draw.io-style press-drag-release (also supports click-source /
  // click-target). A press resolves a SOURCE endpoint (snapping to the nearest
  // node within SNAP_RADIUS_PX, incl. type-B nodes); a release resolves a TARGET
  // and connects via connectEndpoints (auto-adopting type-B endpoints). All the
  // logic lives in connect.ts (unit-tested); here we only translate mouse events
  // → page pixels. A gesture that resolves to no node is a no-op (NO freepoint).
  const SNAP_RADIUS_PX = natural ? Math.max(20, (natural.w / 1200) * 18) : 24;

  function sameNode(a: ResolvedEndpoint, b: ResolvedEndpoint): boolean {
    if (a.kind === "entity" && b.kind === "entity") return a.entityId === b.entityId;
    if (a.kind === "typeB" && b.kind === "typeB") return a.node.id === b.node.id;
    return false;
  }

  function onEdgeMouseDown(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "draw-edge" || edgeDraft.source) return; // draft open → release handles target
    const pt = clientToPagePixel(e.clientX, e.clientY);
    if (!pt || !natural) return;
    const src = resolveEndpoint(pt, graph ?? null, natural, SNAP_RADIUS_PX);
    if (src.kind === "none") return;
    setEdgeDraft({ source: src, sourcePoint: src.center, cursorPoint: src.center });
  }

  async function onEdgeMouseUp(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "draw-edge" || !edgeDraft.source || !natural) return;
    const pt = clientToPagePixel(e.clientX, e.clientY);
    const tgt = pt
      ? resolveEndpoint(pt, graph ?? null, natural, SNAP_RADIUS_PX)
      : ({ kind: "none" } as ResolvedEndpoint);
    // Release back on the source node (a click-in-place): keep the draft open so
    // a second click on the target completes it (click-source/click-target flow).
    if (tgt.kind !== "none" && sameNode(edgeDraft.source, tgt)) return;
    const src = edgeDraft.source;
    setEdgeDraft({ source: null, sourcePoint: null, cursorPoint: null });
    if (tgt.kind === "none") return; // released off any node → no-op (no freepoint)
    await connectEndpoints(src, tgt, {
      natural,
      lineType: activeLineType,
      adopt: async (node) => (onAdoptForConnect ? await onAdoptForConnect(node) : null),
      onEdgeDrawn: (s, t, poly, lt) => onEdgeDrawn?.(s, t, poly, lt),
    });
  }

  // GraphLayer suppresses node onClick in draw-edge mode, so node selection /
  // adopt-panel routing only fires in select mode. In draw-edge the svg-level
  // press/release above owns connections; this just forwards the click.
  function handleGraphNodeClick(nodeId: string) {
    onGraphNodeClick?.(nodeId);
  }

  function onCanvasMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "draw-edge" || !edgeDraft.source) return;
    const pt = clientToPagePixel(e.clientX, e.clientY);
    if (!pt) return;
    setEdgeDraft((d) => ({ ...d, cursorPoint: pt }));
  }

  // Escape cancels an in-flight edge draft.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setEdgeDraft({ source: null, sourcePoint: null, cursorPoint: null });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cursor = mode === "mark-symbol" ? "crosshair" : mode === "draw-edge" ? "crosshair" : "default";

  return (
    <div
      data-canvas-interactive={mode !== "select" || undefined}
      style={{
        position: "relative",
        display: "inline-block",
        margin: "0 auto",
        // Layout-based zoom (FEATURES #43 v2): once measured, size the page box
        // to fit×zoom in real CSS px so the browser samples the hi-DPI source
        // at the zoomed size (crisp). Until measured, fall back to the FEATURES
        // #40 object-fit fit so the first paint still fills the canvas column.
        ...(display
          ? { width: `${display.w}px`, height: `${display.h}px` }
          : { maxWidth: "100%", maxHeight: "calc(100vh - 160px)" }),
      }}
    >
      {!imgLoaded && (
        <div
          style={{
            position: display ? "absolute" : "relative",
            inset: 0,
            ...(display ? {} : { width: "100%", height: "calc(100vh - 160px)" }),
            borderRadius: 4,
            background: dark
              ? "linear-gradient(90deg, #1a1d30 25%, #23273f 50%, #1a1d30 75%)"
              : "linear-gradient(90deg, #e8eaf0 25%, #f0f2f8 50%, #e8eaf0 75%)",
            backgroundSize: "200% 100%",
            animation: "pid-shimmer 1.4s ease-in-out infinite",
          }}
        />
      )}
      <img
        ref={imgRef}
        src={pageFullUrl}
        alt="P&ID page"
        onLoad={(e) => {
          const img = e.currentTarget;
          setNatural({ w: img.naturalWidth, h: img.naturalHeight });
          onNaturalSize?.(img.naturalWidth, img.naturalHeight);
          setImgLoaded(true);
        }}
        style={{
          display: "block",
          // When the page box is explicitly sized (display set), fill it so the
          // <img> lays out at fit×zoom px and the source is sampled at that
          // size. Else fall back to the object-fit fit for the first paint.
          ...(display
            ? { width: "100%", height: "100%" }
            : { maxWidth: "100%", maxHeight: "calc(100vh - 160px)", objectFit: "contain" as const }),
          borderRadius: 4,
          boxShadow: dark
            ? "0 2px 14px rgba(0,0,0,0.45)"
            : "0 2px 12px rgba(20,22,42,0.18)",
          userSelect: "none",
          pointerEvents: "none",
          // `high-quality` is the modern CSS standard (Chromium ≥ 113) —
          // best downscale kernel available. Firefox falls back to its
          // default high-quality bicubic. Cast because the TS DOM lib
          // hasn't picked up the new value yet (it's in the spec).
          imageRendering: "high-quality" as React.CSSProperties["imageRendering"],
          background: dark ? "#0E1024" : "#fff",
          opacity: imgLoaded ? 1 : 0,
          transition: "opacity 0.25s ease",
        }}
        draggable={false}
      />
      {imgLoaded && natural && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${natural.w} ${natural.h}`}
          preserveAspectRatio="none"
          onMouseDown={(e) => {
            if (mode === "mark-symbol") onCanvasMouseDownForMark(e);
            else if (mode === "draw-edge") onEdgeMouseDown(e);
          }}
          onMouseUp={(e) => {
            // draw-edge: press-drag-release (and click-source/click-target) —
            // the release resolves the target node and connects.
            if (mode === "draw-edge") void onEdgeMouseUp(e);
          }}
          onMouseMove={onCanvasMouseMove}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            cursor,
          }}
        >
          {/* Layer 1: model detections (translated to page-pixel coords).
              FEATURES #40 fixes:
                - Render human names ("Field Instrument"), not raw codes ("inst_field").
                - Suppress crowded labels: skip rendering if another label is
                  already within ~labelMinGap page-pixels (post-rendered above).
              The collision filter runs in a stable iteration order so the
              survivor is deterministic. */}
          {(() => {
            const labelMinGap = Math.max(60, natural.w / 22);
            const placed: Array<{ x: number; y: number }> = [];
            return pageDetections.map((d, i) => {
              const [x1, y1, x2, y2] = d.pageBbox;
              // Only matched detections (entity_id set) have a panelElements entry.
              const detKey = (d.entity_id as string | undefined) ?? null;
              // Clickable only when in select mode AND matched to a canonical entity.
              const clickable = mode === "select" && detKey !== null;
              const isSelected = detKey !== null && detKey === selectedId;
              const sw = Math.max(1, natural.w / 500);
              const kind = labelToSymKind(d.label);       // YOLO label -> glyph
              // Prefer engineering tag (e.g. "62-BV-151062") over generic YOLO name.
              const entityTag = (d as { entity_tag?: string | null }).entity_tag;
              // OCR read a tag but entity not in canonical — still show it, colored.
              const hasTag = !!entityTag && !detKey;
              // Stable hover key for OCR-tagged non-canonical bboxes (index-based, unique per render).
              const hoverKey = detKey ?? (entityTag ? `ocr-${i}` : null);
              const klass = (clickable || hasTag) ? colorForKind(kind) : "#999";
              const human = entityTag || displayNameForModelLabel(d.label);
              const isHovered = hoverKey !== null && hoveredKey === hoverKey;
              // Show label on hover/select/showAllLabels only — never auto-show for OCR tags.
              let showLabel = !!human && (isSelected || isHovered || !!showAllLabels);
              if (showLabel && showAllLabels && !isSelected && !isHovered) {
                for (const p of placed) {
                  if (Math.abs(p.x - x1) < labelMinGap && Math.abs(p.y - y1) < labelMinGap) {
                    showLabel = false;
                    break;
                  }
                }
              }
              if (showLabel && showAllLabels) placed.push({ x: x1, y: y1 });
              const w = x2 - x1;
              const h = y2 - y1;
              return (
                <g key={`det-${i}`}>
                  {/* class-colored P&ID glyph — hidden when graph overlay is on */}
                  {!showGraph && <PidGlyphAt kind={kind} x={x1} y={y1} w={w} h={h} color={klass} />}
                  {/* bbox outline: solid+bright for matched (clickable), dimmed for unmatched */}
                  <rect
                    x={x1}
                    y={y1}
                    width={w}
                    height={h}
                    fill="none"
                    stroke={klass}
                    vectorEffect="non-scaling-stroke"
                    strokeWidth={clickable ? 1.5 : (hasTag ? 1.2 : 0.8)}
                    strokeDasharray={clickable ? undefined : (hasTag ? "5 2" : "3 3")}
                    opacity={showGraph ? 0.2 : (clickable ? 0.75 : (hasTag ? 0.65 : 0.35))}
                    style={{ pointerEvents: "none" }}
                  />
                  {/* invisible hit-target for click/hover */}
                  <rect
                    x={x1}
                    y={y1}
                    width={w}
                    height={h}
                    fill="transparent"
                    style={{
                      pointerEvents: (hoverKey || (hasTag && !!onOrphanSelect)) ? "auto" : "none",
                      cursor: clickable ? "pointer" : (hasTag && onOrphanSelect ? "pointer" : cursor),
                    }}
                    onMouseEnter={() => hoverKey && setHoveredKey(hoverKey)}
                    onMouseLeave={() => hoverKey && setHoveredKey((h) => (h === hoverKey ? null : h))}
                    onClick={
                      clickable
                        ? (ev) => {
                            ev.stopPropagation();
                            onSelect(detKey!, d.entity_class);
                          }
                        : hasTag && onOrphanSelect
                        ? (ev) => {
                            ev.stopPropagation();
                            onOrphanSelect(entityTag!, d.label ?? "");
                          }
                        : undefined
                    }
                  >
                    {clickable && <title>{human} — click to select</title>}
                    {hasTag && <title>{human} — detected, not in extracted document</title>}
                  </rect>
                  {/* search dim highlight (cyan) — all matched entities */}
                  {!isSelected && detKey && searchHighlightSet.has(detKey) && (
                    <rect
                      x={x1}
                      y={y1}
                      width={w}
                      height={h}
                      fill="rgba(255,20,147,0.08)"
                      stroke="#FF1493"
                      vectorEffect="non-scaling-stroke"
                      strokeWidth={1.5}
                      strokeOpacity={0.5}
                      style={{ pointerEvents: "none" }}
                    />
                  )}
                  {/* selection highlight (pink) */}
                  {isSelected && (
                    <rect
                      x={x1}
                      y={y1}
                      width={w}
                      height={h}
                      fill="rgba(255,77,168,0.12)"
                      stroke={STATUS_STROKE.user_added}
                      vectorEffect="non-scaling-stroke"
                      strokeWidth={2.5}
                      style={{ pointerEvents: "none" }}
                    />
                  )}
                  {showLabel && (
                    <text
                      x={x1}
                      y={y1 - sw * 2}
                      fontSize={Math.max(8, natural.w / 140)}
                      fontFamily="JetBrains Mono, Outfit, monospace"
                      fontWeight="700"
                      fill={klass}
                      style={{ pointerEvents: "none", paintOrder: "stroke" }}
                      stroke="#ffffff"
                      strokeWidth={sw * 0.8}
                      strokeOpacity={0.85}
                    >
                      {human}
                    </text>
                  )}
                </g>
              );
            });
          })()}

          {/* Layer 2: user annotations (Phase 3) */}
          {userAnnotations.map((a, i) => {
            const [x1, y1, x2, y2] = a.bbox;
            const sw = Math.max(1, natural.w / 500);
            const isSelected = a.entity_id === selectedId;
            const kind = subClassToSymKind(a.entity_class ?? undefined, a.sub_class ?? undefined);
            const klass = colorForSubClass(a.entity_class ?? undefined, a.sub_class ?? undefined);
            const w = x2 - x1;
            const h = y2 - y1;
            return (
              <g key={`ann-${i}`}>
                {/* class-colored glyph; scales with zoom */}
                <PidGlyphAt kind={kind} x={x1} y={y1} w={w} h={h} color={klass} />
                {/* manually-added = DASHED outline in the class color */}
                <rect
                  x={x1}
                  y={y1}
                  width={w}
                  height={h}
                  fill="none"
                  stroke={klass}
                  strokeDasharray="4 3"
                  vectorEffect="non-scaling-stroke"
                  strokeWidth={1.2}
                  opacity={0.75}
                  style={{ pointerEvents: "none" }}
                />
                {/* invisible hit-target preserves click/select + tooltip */}
                <rect
                  x={x1}
                  y={y1}
                  width={w}
                  height={h}
                  fill="transparent"
                  style={{
                    pointerEvents: mode === "select" ? "auto" : "none",
                    cursor: mode === "select" ? "pointer" : cursor,
                  }}
                  onMouseEnter={() => setHoveredKey(a.entity_id)}
                  onMouseLeave={() => setHoveredKey((h) => (h === a.entity_id ? null : h))}
                  onClick={
                    mode === "select"
                      ? (ev) => {
                          ev.stopPropagation();
                          onSelect(a.entity_id, a.entity_class);
                        }
                      : undefined
                  }
                >
                  <title>
                    {(a.tag ?? a.placeholder_tag ?? a.entity_id) + " — " + a.status}
                  </title>
                </rect>
                {/* selection highlight (pink) */}
                {isSelected && (
                  <rect
                    x={x1}
                    y={y1}
                    width={w}
                    height={h}
                    fill="rgba(255,77,168,0.18)"
                    stroke={STATUS_STROKE.user_added}
                    vectorEffect="non-scaling-stroke"
                    strokeWidth={2.5}
                    style={{ pointerEvents: "none" }}
                  />
                )}
                {(isSelected || hoveredKey === a.entity_id || showAllLabels) && (
                  <text
                    x={x1}
                    y={y1 - sw * 2}
                    fontSize={Math.max(8, natural.w / 140)}
                    fontFamily="Outfit, sans-serif"
                    fontWeight="600"
                    fill={klass}
                    style={{ pointerEvents: "none", paintOrder: "stroke" }}
                    stroke="#ffffff"
                    strokeWidth={sw * 0.8}
                    strokeOpacity={0.85}
                  >
                    {canvasDisplayLabel({
                      tag: a.tag,
                      placeholder_tag: a.placeholder_tag,
                      sub_class: a.sub_class,
                    })}
                  </text>
                )}
              </g>
            );
          })}

          {/* Layer 3: user-drawn edges — only shown when Graph overlay is active.
              Polylines are stored normalized (0..1); scale to natural.w/h on render
              so they stay position-correct across refresh and zoom changes.
              Legacy edges stored in raw page-pixel space (max coord > 2) are
              rendered as-is for backward compatibility. */}
          {showGraph && edges.map((e, i) => {
            const style = LINE_STYLE[e.line_type];
            const isNorm = e.polyline.length > 0 && Math.max(...e.polyline.flat()) <= 2;
            const pts: Array<[number, number]> = isNorm
              ? e.polyline.map(([x, y]) => [x * natural.w, y * natural.h] as [number, number])
              : e.polyline.map(([x, y]) => [x, y] as [number, number]);
            const points = pts.map((p) => p.join(",")).join(" ");
            return (
              <g key={`edge-${i}`}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={style.color}
                  strokeWidth={USER_EDGE_PX}
                  vectorEffect="non-scaling-stroke"
                  strokeDasharray={style.dash === "0" ? undefined : style.dash}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{ pointerEvents: "none" }}
                />
                {/* Arrowhead at terminus for process_pipe and signal lines */}
                {(e.line_type === "process_pipe" || e.line_type === "signal") && pts.length >= 2 && (
                  <Arrowhead
                    from={pts[pts.length - 2]}
                    to={pts[pts.length - 1]}
                    color={style.color}
                    size={USER_EDGE_PX * 4}
                  />
                )}
              </g>
            );
          })}

          {/* Layer 4a: in-flight mark-symbol drag preview (FEATURES #41).
              Renders a dashed pink rectangle as the user drags, so they can
              see the box they're about to create instead of guessing. */}
          {markDraft && (() => {
            const dx = markDraft.x1 - markDraft.x0;
            const dy = markDraft.y1 - markDraft.y0;
            const x = Math.min(markDraft.x0, markDraft.x1);
            const y = Math.min(markDraft.y0, markDraft.y1);
            const w = Math.abs(dx);
            const h = Math.abs(dy);
            const sw = Math.max(1.4, natural.w / 500);
            return (
              <g style={{ pointerEvents: "none" }}>
                <rect
                  x={x} y={y} width={w} height={h}
                  fill="rgba(255,77,168,0.12)"
                  stroke="#FF4DA8"
                  strokeWidth={sw * 1.4}
                  strokeDasharray={`${sw * 3} ${sw * 2}`}
                />
              </g>
            );
          })()}

          {/* Layer 4: draw-edge snap highlight + in-flight edge preview (Phase 4) */}

          {edgeDraft.sourcePoint && edgeDraft.cursorPoint && (
            <g style={{ pointerEvents: "none" }}>
              {/* Preview line from source to cursor — same constant-pixel rendering as committed edges */}
              <line
                x1={edgeDraft.sourcePoint[0]}
                y1={edgeDraft.sourcePoint[1]}
                x2={edgeDraft.cursorPoint[0]}
                y2={edgeDraft.cursorPoint[1]}
                stroke={LINE_STYLE[activeLineType].color}
                strokeWidth={USER_EDGE_PX}
                vectorEffect="non-scaling-stroke"
                strokeDasharray={LINE_STYLE[activeLineType].dash === "0" ? "6 6" : LINE_STYLE[activeLineType].dash}
                opacity={0.7}
              />
              {/* Source-confirmed ring: large dashed circle shows "source is locked".
                  Stays visible while the user moves toward the target so they know
                  click 1 was registered. */}
              <circle
                cx={edgeDraft.sourcePoint[0]}
                cy={edgeDraft.sourcePoint[1]}
                r={Math.max(10, natural.w / 90)}
                fill="none"
                stroke={LINE_STYLE[activeLineType].color}
                strokeWidth={Math.max(1.5, natural.w / 2000)}
                strokeDasharray={`${Math.max(5, natural.w / 500)} ${Math.max(3, natural.w / 700)}`}
                opacity={0.85}
              />
              {/* Source anchor solid dot */}
              <circle
                cx={edgeDraft.sourcePoint[0]}
                cy={edgeDraft.sourcePoint[1]}
                r={Math.max(3, natural.w / 250)}
                fill={LINE_STYLE[activeLineType].color}
              />
              {/* Target cursor dot */}
              <circle
                cx={edgeDraft.cursorPoint[0]}
                cy={edgeDraft.cursorPoint[1]}
                r={Math.max(3, natural.w / 300)}
                fill={LINE_STYLE[activeLineType].color}
                opacity={0.8}
              />
            </g>
          )}

          {/* Layer 5: process-graph overlay (Stream 3). Drawn on top of the
              detection / annotation / edge layers; coords are already
              page-pixel so they share the same viewBox with zero translation. */}
          {graph && (
            <GraphLayer
              graph={graph}
              natural={natural}
              visible={showGraph}
              onSelect={onSelect}
              selectedEdgeId={selectedGraphEdgeId ?? null}
              onEdgeClick={mode === "select" ? onGraphEdgeClick : undefined}
              showLabels={showAllLabels}
              onNodeClick={handleGraphNodeClick}
              selectedNodeId={selectedGraphNodeId ?? null}
              onAdoptTarget={onAdoptTarget}
              mode={mode}
            />
          )}

          {/* Layer 6: search sonar-ping ring — animated cyan pulse on the
              actively jumped-to entity. Keyed on searchJumpKey so the CSS
              animation resets every time the user jumps to a new result.
              Fades out in 3 s, non-looping (animation-iteration-count: 1). */}
          {(() => {
            if (!searchActiveId || !natural) return null;
            const det = pageDetections.find(
              (d) => (d.entity_id as string | undefined) === searchActiveId,
            );
            if (!det) return null;
            const [sx1, sy1, sx2, sy2] = det.pageBbox;
            const sw = sx2 - sx1;
            const sh = sy2 - sy1;
            const pad = Math.max(sw, sh) * 0.5;
            return (
              <g key={searchJumpKey} style={{ pointerEvents: "none" }}>
                <style>{`
                  @keyframes sonar-ping {
                    0%   { opacity: 0.9; }
                    100% { opacity: 0; }
                  }
                  @keyframes sonar-expand {
                    0% {
                      x: ${sx1}px; y: ${sy1}px;
                      width: ${sw}px; height: ${sh}px;
                    }
                    100% {
                      x: ${sx1 - pad}px; y: ${sy1 - pad}px;
                      width: ${sw + pad * 2}px; height: ${sh + pad * 2}px;
                    }
                  }
                `}</style>
                {/* Persistent thin outline on the active entity */}
                <rect
                  x={sx1}
                  y={sy1}
                  width={sw}
                  height={sh}
                  fill="rgba(255,20,147,0.12)"
                  stroke="#FF1493"
                  vectorEffect="non-scaling-stroke"
                  strokeWidth={2}
                />
                {/* Expanding pulse ring */}
                <rect
                  x={sx1}
                  y={sy1}
                  width={sw}
                  height={sh}
                  fill="none"
                  stroke="#FF1493"
                  vectorEffect="non-scaling-stroke"
                  strokeWidth={1.5}
                  style={{
                    animation: "sonar-ping 3s ease-out 1 forwards",
                    transformBox: "fill-box",
                    transformOrigin: "center",
                  }}
                >
                  <animate
                    attributeName="x"
                    from={sx1}
                    to={sx1 - pad}
                    dur="3s"
                    fill="freeze"
                  />
                  <animate
                    attributeName="y"
                    from={sy1}
                    to={sy1 - pad}
                    dur="3s"
                    fill="freeze"
                  />
                  <animate
                    attributeName="width"
                    from={sw}
                    to={sw + pad * 2}
                    dur="3s"
                    fill="freeze"
                  />
                  <animate
                    attributeName="height"
                    from={sh}
                    to={sh + pad * 2}
                    dur="3s"
                    fill="freeze"
                  />
                  <animate
                    attributeName="opacity"
                    from="0.9"
                    to="0"
                    dur="3s"
                    fill="freeze"
                  />
                </rect>
              </g>
            );
          })()}
        </svg>
      )}
    </div>
  );
}

function Arrowhead({
  from,
  to,
  color,
  size,
}: {
  from: [number, number];
  to: [number, number];
  color: string;
  size: number;
}) {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const back = size;
  const side = size * 0.55;
  const baseX = to[0] - ux * back;
  const baseY = to[1] - uy * back;
  const leftX = baseX + uy * side;
  const leftY = baseY - ux * side;
  const rightX = baseX - uy * side;
  const rightY = baseY + ux * side;
  return (
    <polygon
      points={`${to[0]},${to[1]} ${leftX},${leftY} ${rightX},${rightY}`}
      fill={color}
    />
  );
}

function tileIdFromFilename(filename: string | null): string | null {
  if (!filename) return null;
  const m = filename.match(/(?:overlay_)?tile_p(\d+)_r(\d+)_c(\d+)\.png/);
  if (!m) return null;
  return `${m[1]}_${parseInt(m[2], 10) * 3 + parseInt(m[3], 10)}`;
}

interface TopoLine { x1: number; y1: number; x2: number; y2: number }

function TileWithOverlay({
  tileImageUrl,
  tileFilename,
  detections,
  onSelect,
  selectedId,
  jobId,
  onOrphanSelect,
}: {
  tileImageUrl: string;
  tileFilename: string | null;
  detections: DetectionItem[];
  onSelect: (id: string, entityClass?: string) => void;
  selectedId: string;
  jobId?: number;
  onOrphanSelect?: (tag: string, label: string) => void;
}) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [topoLines, setTopoLines] = useState<TopoLine[]>([]);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const tileId = tileIdFromFilename(tileFilename);

  // Cached-image guard (see PageWithOverlays): a cached tile may already be
  // `complete` before React wires `onLoad`, leaving `natural` null and the
  // overlay (`showSvg = natural && …`) blank. Re-sync from the element.
  useEffect(() => {
    const img = imgRef.current;
    if (!natural && img && img.complete && img.naturalWidth > 0) {
      setNatural({ w: img.naturalWidth, h: img.naturalHeight });
    }
  }, [tileImageUrl, natural]);

  // Fetch detected topology lines for this tile from line_detector output
  useEffect(() => {
    if (!jobId || !tileId) {
      setTopoLines([]);
      return;
    }
    setTopoLines([]);
    fetch(`/api/v1/jobs/${jobId}/tiles/${tileId}/summary`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const lines = data?.entities?.lines ?? [];
        setTopoLines(
          lines.map((l: Record<string, number>) => ({
            x1: Number(l.start_x),
            y1: Number(l.start_y),
            x2: Number(l.end_x),
            y2: Number(l.end_y),
          }))
        );
      })
      .catch(() => {});
  }, [jobId, tileId]);

  const tileDets = tileFilename
    ? detections.filter(
        (d) => Array.isArray(d.bbox) && d.bbox.length === 4 && d.tile === tileFilename,
      )
    : [];

  const showSvg = natural && (tileDets.length > 0 || topoLines.length > 0);

  return (
    <div
      style={{
        position: "relative",
        display: "inline-block",
        maxWidth: "min(100%, 1200px)",
        maxHeight: "70vh",
        margin: "0 auto",
      }}
    >
      <img
        ref={imgRef}
        src={tileImageUrl}
        alt="P&ID tile"
        onLoad={(e) => {
          const img = e.currentTarget;
          setNatural({ w: img.naturalWidth, h: img.naturalHeight });
        }}
        style={{
          display: "block",
          maxWidth: "min(100%, 1200px)",
          maxHeight: "70vh",
          objectFit: "contain",
          borderRadius: 4,
          boxShadow: "0 2px 8px rgba(0,0,0,0.18)",
          userSelect: "none",
          pointerEvents: "none",
          imageRendering: "auto",
        }}
        draggable={false}
      />
      {showSvg && (
        <svg
          viewBox={`0 0 ${natural.w} ${natural.h}`}
          preserveAspectRatio="none"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
          }}
        >
          {/* Topology lines detected by line_detector.py */}
          {topoLines.map((l, i) => (
            <line
              key={`topo_${i}`}
              x1={l.x1}
              y1={l.y1}
              x2={l.x2}
              y2={l.y2}
              stroke="cyan"
              strokeWidth={Math.max(0.5, natural.w / 800)}
              strokeOpacity={0.7}
              style={{ pointerEvents: "none" }}
            />
          ))}
          {/* YOLO detection bboxes */}
          {tileDets.map((d, i) => {
            const [x1, y1, x2, y2] = d.bbox!;
            const clickable = typeof d.entity_id === "string" && d.entity_id.length > 0;
            const entityTag = (d as { entity_tag?: string | null }).entity_tag;
            const orphan = !clickable && !!entityTag && !!onOrphanSelect;
            const isSelected = clickable && d.entity_id === selectedId;
            const sw = Math.max(1, natural.w / 400);
            const stroke = clickable ? "#FF4DA8" : (orphan ? "#F59E0B" : "#888");
            return (
              <g key={i}>
                <rect
                  x={x1}
                  y={y1}
                  width={x2 - x1}
                  height={y2 - y1}
                  fill={isSelected ? "rgba(255,77,168,0.15)" : "none"}
                  stroke={stroke}
                  strokeWidth={isSelected ? sw * 2 : sw}
                  strokeDasharray={isSelected ? undefined : `${sw * 2} ${sw * 2}`}
                  style={{
                    pointerEvents: (clickable || orphan) ? "auto" : "none",
                    cursor: (clickable || orphan) ? "pointer" : "default",
                  }}
                  onClick={
                    clickable
                      ? () => onSelect(d.entity_id as string, d.entity_class)
                      : orphan
                      ? () => onOrphanSelect!(entityTag!, d.label ?? "")
                      : undefined
                  }
                >
                  {clickable && <title>{d.entity_tag ?? d.label} — click to view</title>}
                  {orphan && <title>{entityTag} — detected, not in extracted document</title>}
                </rect>
                {(d.entity_tag ?? d.label) && (
                  <text
                    x={x1}
                    y={y1 - sw * 2}
                    fontSize={Math.max(8, natural.w / 100)}
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="700"
                    fill={stroke}
                    style={{
                      pointerEvents: (clickable || orphan) ? "auto" : "none",
                      cursor: (clickable || orphan) ? "pointer" : "default",
                    }}
                    onClick={
                      clickable
                        ? () => onSelect(d.entity_id as string, d.entity_class)
                        : orphan
                        ? () => onOrphanSelect!(entityTag!, d.label ?? "")
                        : undefined
                    }
                  >
                    {d.entity_tag ?? d.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

export { ELEMENTS as DEMO_ELEMENTS };
