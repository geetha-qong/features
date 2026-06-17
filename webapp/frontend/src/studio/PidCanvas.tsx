import { useEffect, useMemo, useRef, useState } from "react";
import type { DetectionItem } from "./api";
import type { JobGraph } from "./types";
import GraphLayer from "./GraphLayer";
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

export type LineType = "process_pipe" | "instrument" | "signal" | "interlock";

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
const LINE_STYLE: Record<LineType, { color: string; dash: string; width: number }> = {
  process_pipe: { color: "#22D3EE", dash: "0",      width: 2.4 },  // --scan-cyan solid
  instrument:   { color: "#FF4DA8", dash: "8 4",    width: 2.0 },  // --qong-pink dashed
  signal:       { color: "#C73FBE", dash: "14 6",   width: 2.0 },  // --qong-purple long-dash
  interlock:    { color: "#F59E0B", dash: "4 4 1 4", width: 2.0 }, // --warn dash-dot
};

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
  onDropMark?: (bbox: [number, number, number, number], sub_class: string, entity_class: string) => void;
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
  /** Show ALL element labels at once. Default (false) = labels only on the
   *  hovered/selected element, so dense drawings stay readable. */
  showAllLabels?: boolean;
  /** Called once when the full-page image loads, providing its natural dimensions.
   *  Studio uses this to compute pan-to coordinates for sidebar → canvas sync. */
  onNaturalSize?: (w: number, h: number) => void;
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
  onNaturalSize,
}: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [animated, setAnimated] = useState(true);
  const pannedRef = useRef(false);

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
      const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
      setZoom((z) => Math.max(0.3, Math.min(6, z * factor)));
      setTimeout(() => setAnimated(true), 200);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setZoom]);

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
            onNaturalSize={onNaturalSize}
          />
        )}
        {useTile && (
          <TileWithOverlay
            tileImageUrl={tileImageUrl!}
            tileFilename={tileFilename ?? null}
            detections={detections ?? []}
            onSelect={onSelect}
            selectedId={selectedId}
          />
        )}
        {useProto && (
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
  onNaturalSize,
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
  onDropMark?: (bbox: [number, number, number, number], sub_class: string, entity_class: string) => void;
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
  onNaturalSize?: (w: number, h: number) => void;
}) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  // Which element's label to show on hover (when not showing all labels).
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

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

  // Phase 4: in-flight edge draw state. First click captures source point;
  // second click captures target + flushes via onEdgeDrawn.
  const [edgeDraft, setEdgeDraft] = useState<{
    sourcePoint: [number, number] | null;
    sourceEntityId: string | null;
    cursorPoint: [number, number] | null;
  }>({ sourcePoint: null, sourceEntityId: null, cursorPoint: null });

  // FEATURES #41: mark-symbol mode is now drag-to-create instead of
  // click-drops-a-fixed-bbox. The user surfaces a draggable rectangle that
  // fits the symbol they're labelling, matching the draw.io prototype.
  // null when no drag in progress.
  const [markDraft, setMarkDraft] = useState<{
    x0: number; y0: number; x1: number; y1: number;
  } | null>(null);

  const offsets = useMemo(() => {
    if (!natural) return new Map<string, TileBox>();
    return computeTileOffsets(natural, pageIndex);
  }, [natural, pageIndex]);

  // Translate detections to page-pixel coords. Drop those whose tile filename
  // doesn't match any computed offset (would indicate a multi-page mismatch).
  const pageDetections = useMemo(() => {
    if (!natural) return [];
    // map first (preserves global index), then filter — _origIdx lets the
    // render loop compute the same key that buildElementsForTile assigned.
    return detections
      .map((d, origIdx) => {
        if (!Array.isArray(d.bbox) || d.bbox.length !== 4 || !d.tile) return null;
        const pb = tileBboxToPage(d.bbox as number[], d.tile as string, offsets);
        return pb ? { ...d, pageBbox: pb, _origIdx: origIdx } : null;
      })
      .filter((d): d is NonNullable<typeof d> => d !== null);
  }, [detections, offsets, natural]);

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
      onDropMark(
        [bx0, by0, bx1, by1],
        activeMarkClass.sub_class,
        activeMarkClass.entity_class,
      );
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  // Draw-edge mode: 2-click flow. Track cursor between clicks for live preview.
  function onCanvasClickForEdge(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "draw-edge") return;
    const pt = clientToPagePixel(e.clientX, e.clientY);
    if (!pt) return;
    // Snap to nearest entity center if within 24 px.
    const allPoints: Array<{ id: string; cx: number; cy: number }> = [];
    pageDetections.forEach((d) => {
      if (!d.entity_id) return;
      const [x1, y1, x2, y2] = d.pageBbox;
      allPoints.push({ id: d.entity_id as string, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2 });
    });
    userAnnotations.forEach((a) => {
      const [x1, y1, x2, y2] = a.bbox;
      allPoints.push({ id: a.entity_id, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2 });
    });
    let snapId: string | null = null;
    let snapPoint = pt;
    let bestDist = Infinity;
    for (const p of allPoints) {
      const dx = pt[0] - p.cx;
      const dy = pt[1] - p.cy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < bestDist && dist < 28) {
        bestDist = dist;
        snapId = p.id;
        snapPoint = [p.cx, p.cy];
      }
    }
    if (!snapId) return; // edges only between entities

    if (!edgeDraft.sourcePoint) {
      setEdgeDraft({ sourcePoint: snapPoint, sourceEntityId: snapId, cursorPoint: snapPoint });
    } else if (edgeDraft.sourceEntityId !== snapId) {
      // Commit
      onEdgeDrawn?.(
        edgeDraft.sourceEntityId!,
        snapId,
        [edgeDraft.sourcePoint, snapPoint],
        activeLineType,
      );
      setEdgeDraft({ sourcePoint: null, sourceEntityId: null, cursorPoint: null });
    }
  }

  function onCanvasMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (mode !== "draw-edge" || !edgeDraft.sourcePoint) return;
    const pt = clientToPagePixel(e.clientX, e.clientY);
    if (pt) setEdgeDraft((d) => ({ ...d, cursorPoint: pt }));
  }

  // Escape cancels in-flight edge.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setEdgeDraft({ sourcePoint: null, sourceEntityId: null, cursorPoint: null });
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
      <img
        ref={imgRef}
        src={pageFullUrl}
        alt="P&ID page"
        onLoad={(e) => {
          const img = e.currentTarget;
          setNatural({ w: img.naturalWidth, h: img.naturalHeight });
          onNaturalSize?.(img.naturalWidth, img.naturalHeight);
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
        }}
        draggable={false}
      />
      {natural && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${natural.w} ${natural.h}`}
          preserveAspectRatio="none"
          onMouseDown={(e) => {
            if (mode === "mark-symbol") onCanvasMouseDownForMark(e);
          }}
          onClick={(e) => {
            // draw-edge stays click-based (2-click flow); mark-symbol commits
            // via the mouseup inside onCanvasMouseDownForMark above.
            if (mode === "draw-edge") onCanvasClickForEdge(e);
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
              // detKey mirrors the key buildElementsForTile assigns this detection.
              // Matched detections use entity_id (UUID); unmatched use _det_<origIdx>.
              const detKey = (d.entity_id as string | undefined) || `_det_${d._origIdx}`;
              const clickable = mode === "select"; // all detections selectable in select mode
              const isSelected = detKey === selectedId;
              const sw = Math.max(1, natural.w / 500);
              const kind = labelToSymKind(d.label);       // YOLO label -> glyph
              const klass = colorForKind(kind);            // per-class palette color (LS-style)
              const human = displayNameForModelLabel(d.label);
              const isHovered = hoveredKey === detKey;
              // Default: labels only for the selected/hovered element, so dense
              // drawings stay readable and labels don't overlap the symbols.
              // "Show all labels" mode renders every label, suppressing ones too
              // close to an already-placed label (deterministic collision filter).
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
                  {/* class-colored P&ID glyph (currentColor); scales with zoom */}
                  <PidGlyphAt kind={kind} x={x1} y={y1} w={w} h={h} color={klass} />
                  {/* model = SOLID thin outline in the class color */}
                  <rect
                    x={x1}
                    y={y1}
                    width={w}
                    height={h}
                    fill="none"
                    stroke={klass}
                    vectorEffect="non-scaling-stroke"
                    strokeWidth={1}
                    opacity={0.55}
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
                      pointerEvents: clickable ? "auto" : "none",
                      cursor: clickable ? "pointer" : cursor,
                    }}
                    onMouseEnter={() => setHoveredKey(detKey)}
                    onMouseLeave={() => setHoveredKey((h) => (h === detKey ? null : h))}
                    onClick={
                      clickable
                        ? (ev) => {
                            ev.stopPropagation();
                            onSelect(detKey, d.entity_class);
                          }
                        : undefined
                    }
                  >
                    {clickable && <title>{human || d.label || "Detection"} — click to select</title>}
                  </rect>
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
                      fontFamily="Outfit, sans-serif"
                      fontWeight="600"
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

          {/* Layer 3: edges (Phase 4) */}
          {edges.map((e, i) => {
            const style = LINE_STYLE[e.line_type];
            const sw = Math.max(1.2, (natural.w / 800) * style.width);
            const points = e.polyline.map((p) => p.join(",")).join(" ");
            return (
              <g key={`edge-${i}`}>
                <polyline
                  points={points}
                  fill="none"
                  stroke={style.color}
                  strokeWidth={sw}
                  strokeDasharray={style.dash === "0" ? undefined : style.dash}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{ pointerEvents: "none" }}
                />
                {/* Arrowhead at terminus for process_pipe and signal lines */}
                {(e.line_type === "process_pipe" || e.line_type === "signal") && e.polyline.length >= 2 && (
                  <Arrowhead
                    from={e.polyline[e.polyline.length - 2]}
                    to={e.polyline[e.polyline.length - 1]}
                    color={style.color}
                    size={sw * 4}
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

          {/* Layer 4: in-flight edge preview (Phase 4) */}
          {edgeDraft.sourcePoint && edgeDraft.cursorPoint && (
            <g style={{ pointerEvents: "none" }}>
              <line
                x1={edgeDraft.sourcePoint[0]}
                y1={edgeDraft.sourcePoint[1]}
                x2={edgeDraft.cursorPoint[0]}
                y2={edgeDraft.cursorPoint[1]}
                stroke={LINE_STYLE[activeLineType].color}
                strokeWidth={Math.max(1.2, (natural.w / 800) * 2)}
                strokeDasharray={LINE_STYLE[activeLineType].dash === "0" ? "6 6" : LINE_STYLE[activeLineType].dash}
                opacity={0.7}
              />
              <circle
                cx={edgeDraft.sourcePoint[0]}
                cy={edgeDraft.sourcePoint[1]}
                r={Math.max(3, natural.w / 250)}
                fill={LINE_STYLE[activeLineType].color}
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
            />
          )}
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

function TileWithOverlay({
  tileImageUrl,
  tileFilename,
  detections,
  onSelect,
  selectedId,
}: {
  tileImageUrl: string;
  tileFilename: string | null;
  detections: DetectionItem[];
  onSelect: (id: string, entityClass?: string) => void;
  selectedId: string;
}) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  const tileDets = tileFilename
    ? detections.filter(
        (d) => Array.isArray(d.bbox) && d.bbox.length === 4 && d.tile === tileFilename,
      )
    : [];

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
      {natural && tileDets.length > 0 && (
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
          {tileDets.map((d, i) => {
            const [x1, y1, x2, y2] = d.bbox!;
            const clickable = typeof d.entity_id === "string" && d.entity_id.length > 0;
            const isSelected = clickable && d.entity_id === selectedId;
            const sw = Math.max(1, natural.w / 400);
            return (
              <g key={i}>
                <rect
                  x={x1}
                  y={y1}
                  width={x2 - x1}
                  height={y2 - y1}
                  fill={isSelected ? "rgba(255,77,168,0.15)" : "none"}
                  stroke="#FF4DA8"
                  strokeWidth={isSelected ? sw * 2 : sw}
                  strokeDasharray={isSelected ? undefined : `${sw * 2} ${sw * 2}`}
                  style={{
                    pointerEvents: clickable ? "auto" : "none",
                    cursor: clickable ? "pointer" : "default",
                  }}
                  onClick={
                    clickable
                      ? () => onSelect(d.entity_id as string, d.entity_class)
                      : undefined
                  }
                >
                  {clickable && <title>{d.label} — click to edit</title>}
                </rect>
                {d.label && (
                  <text
                    x={x1}
                    y={y1 - sw * 2}
                    fontSize={Math.max(8, natural.w / 100)}
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="700"
                    fill="#FF4DA8"
                    style={{ pointerEvents: "none" }}
                  >
                    {d.label}
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
