import { useEffect, useRef, useState } from "react";
import type { DetectionItem } from "./api";

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

interface Props {
  selectedId: string;
  onSelect: (id: string) => void;
  zoom: number;
  setZoom: React.Dispatch<React.SetStateAction<number>>;
  pan: { x: number; y: number };
  setPan: React.Dispatch<React.SetStateAction<{ x: number; y: number }>>;
  dark: boolean;
  /**
   * Real PDF tile image for the active sheet. When provided, it's drawn as the
   * canvas background and prototype SVG elements are hidden. Detections (if
   * any) are overlaid as rectangles in the same coordinate space.
   */
  tileImageUrl?: string | null;
  /** Backend-supplied valve / instrument detections to overlay on the tile. */
  detections?: DetectionItem[];
  /** Number of structured valve rows in the DB — shown in the canvas footer. */
  valveCount?: number;
  /** valve_count stored on the Job row (may be > rows if data not yet seeded). */
  valveCountTotal?: number;
}

export default function PidCanvas({
  selectedId,
  onSelect,
  zoom,
  setZoom,
  pan,
  setPan,
  dark,
  tileImageUrl,
  detections,
  valveCount,
  valveCountTotal,
}: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [animated, setAnimated] = useState(true);
  const pannedRef = useRef(false);

  const elFill = dark ? "#0E1024" : "#ffffff";
  const elStroke = dark ? "rgba(255,255,255,0.65)" : "rgba(20,22,42,0.55)";
  const elText = dark ? "#ffffff" : "#14162A";
  const subText = dark ? "#9498AE" : "#6B6F8A";
  const gridStroke = dark ? "#ffffff" : "#14162A";
  const gridOp = dark ? 0.04 : 0.06;
  const legendText = dark ? "#9498AE" : "#6B6F8A";

  function onMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if ((e.target as HTMLElement).closest("g[data-elid]")) return;
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
      setZoom((z) => Math.max(0.3, Math.min(4, z * factor)));
      setTimeout(() => setAnimated(true), 200);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setZoom]);

  const clickGuard = (cb: () => void) => () => {
    if (!pannedRef.current) cb();
  };

  // When a real tile is available, show it + detection overlay. Prototype SVG
  // elements (V-101, FT-101, …) are hidden so customers see their real data.
  const useReal = !!tileImageUrl;

  return (
    <div ref={wrapRef} className="canvas-wrap" onMouseDown={onMouseDown}>
      <div
        ref={innerRef}
        className={`canvas-inner ${animated ? "animated" : ""}`}
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
      >
        {useReal && (
          <img
            src={tileImageUrl!}
            alt="P&ID tile"
            style={{
              maxWidth: "min(100%, 1200px)",
              maxHeight: "70vh",
              objectFit: "contain",
              display: "block",
              margin: "0 auto",
              borderRadius: 4,
              boxShadow: "0 2px 8px rgba(0,0,0,0.18)",
              userSelect: "none",
              pointerEvents: "none",
            }}
            draggable={false}
          />
        )}
        {useReal && detections && detections.length > 0 && (
          <DetectionOverlay detections={detections} onSelect={onSelect} selectedId={selectedId} />
        )}
        {!useReal && (
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
                    <circle
                      cx={el.x}
                      cy={el.y}
                      r={r + 6}
                      fill="none"
                      stroke={ringStroke}
                      strokeWidth="1.3"
                      strokeDasharray="3 3"
                    />
                  )}
                  <circle cx={el.x} cy={el.y} r={r} fill={elFill} stroke={stroke} strokeWidth="1.8" />
                  <line x1={el.x - r * 0.85} y1={el.y} x2={el.x + r * 0.85} y2={el.y} stroke={stroke} strokeWidth="0.8" />
                  <text
                    x={el.x}
                    y={el.y - 2}
                    textAnchor="middle"
                    fontSize="9"
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="700"
                    fill={el.warn ? "#F59E0B" : elText}
                  >
                    {el.label}
                  </text>
                  <text
                    x={el.x}
                    y={el.y + 9}
                    textAnchor="middle"
                    fontSize="9"
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="500"
                    fill={el.warn ? "#F59E0B" : subText}
                  >
                    {el.sub}
                  </text>
                </g>
              );
            }

            if (el.type === "pump") {
              const r = el.r ?? 24;
              return (
                <g
                  key={el.id}
                  data-elid={el.id}
                  onMouseUp={clickGuard(() => onSelect(el.id))}
                  style={{ cursor: "pointer" }}
                >
                  {sel && (
                    <circle
                      cx={el.x}
                      cy={el.y}
                      r={r + 5}
                      fill="none"
                      stroke={ringStroke}
                      strokeWidth="1.3"
                      strokeDasharray="3 3"
                    />
                  )}
                  <circle cx={el.x} cy={el.y} r={r} fill={elFill} stroke={stroke} strokeWidth="1.8" />
                  <polygon
                    points={`${el.x - r * 0.7},${el.y - r * 0.7} ${el.x + r * 0.7},${el.y} ${el.x - r * 0.7},${el.y + r * 0.7}`}
                    fill="none"
                    stroke={stroke}
                    strokeWidth="1.3"
                  />
                  <text
                    x={el.x}
                    y={el.y + r + 12}
                    textAnchor="middle"
                    fontSize="9"
                    fontFamily="JetBrains Mono, monospace"
                    fontWeight="700"
                    fill={subText}
                  >
                    {el.label}
                  </text>
                </g>
              );
            }

            // block-valve, exchanger (rectangular)
            const w = el.w ?? 60;
            const h = el.h ?? 32;
            return (
              <g
                key={el.id}
                data-elid={el.id}
                onMouseUp={clickGuard(() => onSelect(el.id))}
                style={{ cursor: "pointer" }}
              >
                {sel && (
                  <rect
                    x={el.x - w / 2 - 4}
                    y={el.y - h / 2 - 4}
                    width={w + 8}
                    height={h + 8}
                    fill="none"
                    stroke={ringStroke}
                    strokeWidth="1.3"
                    strokeDasharray="3 3"
                    rx="4"
                  />
                )}
                <rect
                  x={el.x - w / 2}
                  y={el.y - h / 2}
                  width={w}
                  height={h}
                  fill={elFill}
                  stroke={stroke}
                  strokeWidth="1.8"
                  rx="2"
                />
                {el.type === "exchanger" && (
                  <>
                    <line
                      x1={el.x - w / 2 + 6}
                      y1={el.y - h / 2 + 6}
                      x2={el.x + w / 2 - 6}
                      y2={el.y - h / 2 + 6}
                      stroke={stroke}
                      strokeWidth="0.8"
                    />
                    <line
                      x1={el.x - w / 2 + 6}
                      y1={el.y + h / 2 - 6}
                      x2={el.x + w / 2 - 6}
                      y2={el.y + h / 2 - 6}
                      stroke={stroke}
                      strokeWidth="0.8"
                    />
                  </>
                )}
                <text
                  x={el.x}
                  y={el.y + 3}
                  textAnchor="middle"
                  fontSize="9"
                  fontFamily="JetBrains Mono, monospace"
                  fontWeight="700"
                  fill={elText}
                >
                  {el.label}
                </text>
              </g>
            );
          })}

          <text
            x={295}
            y={218}
            fontSize="7"
            fontFamily="JetBrains Mono, monospace"
            fill="#F59E0B"
            letterSpacing="0.1em"
          >
            direction unsure
          </text>

          <g transform="translate(180, 320)" fontFamily="Outfit, sans-serif" fontSize="9" fill={legendText}>
            <circle cx="0" cy="0" r="3" fill="#22D3EE" />
            <text x="8" y="3">
              process line
            </text>
            <circle cx="78" cy="0" r="3" fill="#F59E0B" />
            <text x="86" y="3">
              low confidence
            </text>
            <circle cx="172" cy="0" r="3" fill="#FF4DA8" />
            <text x="180" y="3">
              selected
            </text>
            <circle cx="232" cy="0" r="3" fill="#EF4444" />
            <text x="240" y="3">
              orphan node
            </text>
          </g>
        </svg>
        )}
        {useReal && (
          <div
            style={{
              marginTop: 12,
              padding: "8px 14px",
              fontSize: 12,
              color: dark ? "#9498AE" : "#6B6F8A",
              fontFamily: "JetBrains Mono, monospace",
              textAlign: "center",
            }}
          >
            {valveCount !== undefined && valveCount > 0
              ? `${valveCount} valves on this sheet`
              : valveCountTotal && valveCountTotal > 0
                ? `${valveCountTotal} valves total — detection coords not yet available`
                : "Valve list not yet generated for this job"}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Renders detection rectangles on top of the tile image. Coords are expected
 * to be in the tile's pixel space (the same image used as the canvas
 * background), so we render the SVG with `viewBox` set to the bbox extent of
 * the detections and absolutely position it over the image.
 *
 * If the detection shapes are absent or unrecognizable, we silently render
 * nothing — never crash the canvas because the GPU worker hasn't called back.
 */
function DetectionOverlay({
  detections,
  onSelect,
  selectedId,
}: {
  detections: DetectionItem[];
  onSelect: (id: string) => void;
  selectedId: string;
}) {
  const valid = detections.filter((d) => Array.isArray(d.bbox) && d.bbox.length === 4);
  if (valid.length === 0) return null;

  const xs = valid.flatMap((d) => [d.bbox![0], d.bbox![2]]);
  const ys = valid.flatMap((d) => [d.bbox![1], d.bbox![3]]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  const w = Math.max(1, maxX - minX);
  const h = Math.max(1, maxY - minY);

  return (
    <svg
      viewBox={`${minX} ${minY} ${w} ${h}`}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        margin: "auto",
        maxWidth: "min(100%, 1200px)",
        maxHeight: "70vh",
        // pointerEvents handled per-rect — only entity-linked detections capture clicks
      }}
      preserveAspectRatio="xMidYMid meet"
    >
      {valid.map((d, i) => {
        const [x1, y1, x2, y2] = d.bbox!;
        const clickable = typeof d.entity_id === "string" && d.entity_id.length > 0;
        const isSelected = clickable && d.entity_id === selectedId;
        return (
          <g key={i}>
            <rect
              x={x1}
              y={y1}
              width={x2 - x1}
              height={y2 - y1}
              fill={isSelected ? "rgba(255,77,168,0.15)" : "none"}
              stroke={isSelected ? "#FF4DA8" : "#FF4DA8"}
              strokeWidth={isSelected ? Math.max(2, w / 250) : Math.max(1, w / 400)}
              strokeDasharray={isSelected ? undefined : Math.max(2, w / 200) + " " + Math.max(2, w / 200)}
              style={{
                pointerEvents: clickable ? "auto" : "none",
                cursor: clickable ? "pointer" : "default",
              }}
              onClick={clickable ? () => onSelect(d.entity_id as string) : undefined}
            >
              {clickable && <title>{d.label} — click to edit</title>}
            </rect>
            {d.label && (
              <text
                x={x1}
                y={y1 - Math.max(2, h / 100)}
                fontSize={Math.max(8, w / 100)}
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
  );
}

export { ELEMENTS as DEMO_ELEMENTS };
