/**
 * PidSymbol — inline SVG P&ID glyph renderer.
 *
 * Faithful TypeScript port of the design handoff's `Sym({ kind, sw })`
 * component (drawio-symbols.jsx, viewBox "0 0 30 26"). Each `kind` maps to a
 * P&ID symbol drawn with the shared `sym-line` / `sym-fill` / `sym-acc` shape
 * classes so it inherits `color` from its container and themes via the CSS
 * tokens (see design/studio.css → "P&ID symbol glyphs (design v4)").
 *
 * Unknown kinds fall back to the generic valve glyph (`valve_gen`) so a new
 * sub_class never renders an empty box.
 *
 * Frontend-only. The canonical taxonomy lives in the backend; this is purely a
 * presentation layer. `subClassToSymKind` is the shared mapping other surfaces
 * (palette, element rows) use so the glyph for a given class is consistent.
 */
import type { ReactNode } from "react";

interface PidSymbolProps {
  kind: string;
  className?: string;
  /** Stroke width in viewBox units (default 1.5, matching the design). */
  strokeWidth?: number;
}

/** Render the glyph body (the shapes inside the <svg>) for a given kind. */
function glyphBody(kind: string, sw: number): ReactNode {
  // Shape style presets — mirror the design's S / T / A / FILL objects.
  const S = {
    fill: "none",
    strokeWidth: sw,
    strokeLinejoin: "round" as const,
    strokeLinecap: "round" as const,
    className: "sym-line",
  };
  const T = {
    fill: "none",
    strokeWidth: sw * 0.78,
    strokeLinejoin: "round" as const,
    strokeLinecap: "round" as const,
    className: "sym-line",
  };
  const A = {
    fill: "none",
    strokeWidth: sw,
    strokeLinejoin: "round" as const,
    strokeLinecap: "round" as const,
    className: "sym-acc",
  };
  const FILL = { className: "sym-fill" };

  // valve body = bowtie of two triangles meeting at centre (15,13)
  const bowtie = (
    <>
      <polygon points="3,5 14,13 3,21" {...S} />
      <polygon points="27,5 16,13 27,21" {...S} />
    </>
  );
  // filled bowtie = normally-closed
  const bowtieNC = (
    <>
      <polygon points="3,5 14,13 3,21" className="sym-fill" strokeWidth={sw} strokeLinejoin="round" />
      <polygon points="27,5 16,13 27,21" className="sym-fill" strokeWidth={sw} strokeLinejoin="round" />
    </>
  );
  const lead = (
    <>
      <line x1="0" y1="13" x2="3" y2="13" {...S} />
      <line x1="27" y1="13" x2="30" y2="13" {...S} />
    </>
  );
  const txt = (s: string, x = 15, y = 16, fs = 9): ReactNode => (
    <text
      x={x}
      y={y}
      textAnchor="middle"
      fontSize={fs}
      fontFamily="monospace"
      fontWeight="700"
      className="sym-fill"
    >
      {s}
    </text>
  );

  switch (kind) {
    /* ---------- VALVES ---------- */
    case "valve_gen":
      return <>{lead}{bowtie}</>;
    case "valve_gt":
      return <>{lead}{bowtie}<line x1="15" y1="6" x2="15" y2="20" {...T} /></>;
    case "valve_bf":
      return (
        <>
          {lead}
          <circle cx="15" cy="13" r="6.6" {...S} />
          <line x1="10.4" y1="8.4" x2="19.6" y2="17.6" {...A} />
        </>
      );
    case "valve_bv":
      return <>{lead}{bowtie}<circle cx="15" cy="13" r="3.1" {...S} /></>;
    case "valve_ncbv":
      return <>{lead}{bowtieNC}<circle cx="15" cy="13" r="3.1" {...S} /></>;
    case "valve_db":
      return (
        <>
          {lead}
          {bowtie}
          <path d="M9 7 Q15 1.5 21 7" {...A} />
          <line x1="15" y1="7" x2="15" y2="3.5" {...A} />
        </>
      );
    case "valve_ck":
      return (
        <>
          <line x1="0" y1="13" x2="14" y2="13" {...S} />
          <circle cx="14" cy="13" r="1.7" {...FILL} />
          <line x1="14" y1="13" x2="24" y2="5" {...S} />
          <line x1="24" y1="13" x2="30" y2="13" {...S} />
          <line x1="24" y1="6" x2="24" y2="20" {...T} />
        </>
      );
    case "valve_gl":
      return <>{lead}{bowtie}<circle cx="15" cy="13" r="2.6" {...FILL} /></>;
    case "valve_cv":
      return (
        <>
          {lead}
          {bowtie}
          <line x1="15" y1="13" x2="15" y2="6" {...A} />
          <path d="M8 6 A7 4 0 0 1 22 6" {...A} />
        </>
      );
    case "valve_pneuctrl":
      return (
        <>
          {lead}
          {bowtie}
          <line x1="15" y1="13" x2="15" y2="8" {...A} />
          <rect x="8" y="2.5" width="14" height="5.5" rx="1" {...A} />
        </>
      );
    case "valve_relief_safety":
      return (
        <>
          <line x1="4" y1="22" x2="11" y2="22" {...S} />
          <polygon points="11,22 19,22 15,14" {...S} />
          <line x1="15" y1="14" x2="15" y2="11" {...A} />
          <path d="M11 11 l8 -2 -8 -2 8 -2 -8 -2 8 -2" {...A} />
        </>
      );
    case "valve_3way":
      return (
        <>
          {lead}
          {bowtie}
          <polygon points="15,13 11,22 19,22" {...S} />
          <line x1="15" y1="22" x2="15" y2="25" {...S} />
        </>
      );
    case "valve_3way_relief":
      return (
        <>
          {lead}
          {bowtie}
          <polygon points="15,13 11,22 19,22" {...S} />
          <line x1="15" y1="22" x2="15" y2="25" {...S} />
          <line x1="15" y1="13" x2="15" y2="8" {...A} />
          <path d="M11 8 l8 -1.6 -8 -1.6 8 -1.6 -8 -1.6" {...A} />
        </>
      );
    case "valve_needle":
      return (
        <>
          {lead}
          {bowtie}
          <polygon points="15,5 12.5,12 17.5,12" {...A} />
          <line x1="15" y1="5" x2="15" y2="2" {...A} />
        </>
      );
    case "valve_transfer":
      return (
        <>
          <line x1="0" y1="13" x2="3" y2="13" {...S} />
          <line x1="27" y1="13" x2="30" y2="13" {...S} />
          <line x1="15" y1="0" x2="15" y2="3" {...S} />
          <line x1="15" y1="23" x2="15" y2="26" {...S} />
          <polygon points="3,7 13,13 3,19" {...S} />
          <polygon points="27,7 17,13 27,19" {...S} />
          <polygon points="9,3 15,11 21,3" {...S} />
          <polygon points="9,23 15,15 21,23" {...S} />
        </>
      );
    case "valve_reflex_gt":
      return (
        <>
          {lead}
          {bowtie}
          <line x1="15" y1="6" x2="15" y2="20" {...T} />
          <line x1="11" y1="9" x2="19" y2="17" {...A} />
        </>
      );

    /* ---------- INSTRUMENTS ---------- */
    case "inst_field":
      return <circle cx="15" cy="13" r="10" {...S} />;
    case "inst_field-R":
      return (
        <>
          <circle cx="15" cy="13" r="10" {...S} />
          <line x1="5" y1="13" x2="25" y2="13" {...S} strokeDasharray="3 2" />
        </>
      );
    case "inst_local_panel":
      return (
        <>
          <circle cx="15" cy="13" r="10" {...S} />
          <line x1="5" y1="13" x2="25" y2="13" {...S} />
        </>
      );
    case "inst_bpcs":
      return (
        <>
          <rect x="4" y="3" width="22" height="20" rx="1.5" {...S} />
          <circle cx="15" cy="13" r="7.5" {...S} />
        </>
      );
    case "inst_sis":
      return (
        <>
          <polygon points="15,2 27,13 15,24 3,13" {...S} />
          <circle cx="15" cy="13" r="6.6" {...S} />
        </>
      );

    /* ---------- CONTROL & LOGIC ---------- */
    case "DCS":
      return (
        <>
          <rect x="3" y="3" width="24" height="20" rx="1.5" {...S} />
          <circle cx="15" cy="13" r="7.5" {...S} />
          <line x1="3" y1="13" x2="27" y2="13" {...S} />
        </>
      );
    case "PLC":
      return <polygon points="15,2 27,13 15,24 3,13" {...S} />;
    case "interlock":
      return <polygon points="9,3 21,3 27,13 21,23 9,23 3,13" {...S} />;
    case "interlock-R":
      return (
        <>
          <polygon points="9,3 21,3 27,13 21,23 9,23 3,13" {...S} />
          <line x1="6" y1="13" x2="24" y2="13" {...S} strokeDasharray="3 2" />
        </>
      );
    case "SIS-R":
      return (
        <>
          <polygon points="15,2 27,13 15,24 3,13" {...S} />
          <circle cx="15" cy="13" r="6.6" {...S} />
          <line x1="4" y1="13" x2="26" y2="13" {...S} strokeDasharray="3 2" />
        </>
      );

    /* ---------- EQUIPMENT ---------- */
    case "Motor":
      return (
        <>
          <circle cx="15" cy="13" r="10" {...S} />
          {txt("M")}
        </>
      );
    case "pump":
      return (
        <>
          <circle cx="14" cy="14" r="9.5" {...S} />
          <polyline points="14,4.5 22,4.5 22,14" {...S} />
          <polygon points="10,9 19,14 10,19" {...S} />
        </>
      );

    /* ---------- INDICATORS ---------- */
    case "lamp":
      return (
        <>
          <circle cx="15" cy="13" r="9" {...S} />
          <line x1="9.4" y1="7.4" x2="20.6" y2="18.6" {...A} />
          <line x1="20.6" y1="7.4" x2="9.4" y2="18.6" {...A} />
        </>
      );
    case "lamp_local_mounted":
      return (
        <>
          <circle cx="15" cy="11" r="8" {...S} />
          <line x1="9.4" y1="5.6" x2="20.6" y2="16.4" {...A} />
          <line x1="20.6" y1="5.6" x2="9.4" y2="16.4" {...A} />
          <line x1="5" y1="24" x2="25" y2="24" {...S} />
        </>
      );

    /* ---------- ARROWS ---------- */
    case "arrow_right":
      return <polygon points="3,9 16,9 16,5 27,13 16,21 16,17 3,17" {...S} />;
    case "arrow_left":
      return <polygon points="27,9 14,9 14,5 3,13 14,21 14,17 27,17" {...S} />;
    case "arrow_up":
      return <polygon points="9,25 9,13 5,13 15,3 25,13 21,13 21,25" {...S} />;
    case "arrow_down":
      return <polygon points="9,1 9,13 5,13 15,23 25,13 21,13 21,1" {...S} />;

    /* ---------- CONNECTORS (off-page) ---------- */
    case "connector_in":
      return (
        <>
          <polygon points="24,4 8,4 2,13 8,22 24,22" {...S} />
          <line x1="10" y1="13" x2="20" y2="13" {...A} />
          <polyline points="16,9 20,13 16,17" {...A} />
        </>
      );
    case "connector_out":
      return (
        <>
          <polygon points="6,4 22,4 28,13 22,22 6,22" {...S} />
          <line x1="10" y1="13" x2="22" y2="13" {...A} />
          <polyline points="18,9 22,13 18,17" {...A} />
        </>
      );
    case "connector_io":
      return (
        <>
          <circle cx="15" cy="13" r="9" {...S} />
          <line x1="7" y1="13" x2="23" y2="13" {...A} />
          <polyline points="10,10 7,13 10,16" {...A} />
          <polyline points="20,10 23,13 20,16" {...A} />
        </>
      );

    default:
      return <>{lead}{bowtie}</>;
  }
}

export default function PidSymbol({ kind, className, strokeWidth = 1.5 }: PidSymbolProps) {
  return (
    <svg
      viewBox="0 0 30 26"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      style={{ width: "100%", height: "100%", overflow: "visible" }}
      aria-hidden="true"
    >
      {glyphBody(kind, strokeWidth)}
    </svg>
  );
}

/**
 * Map a canonical `entity_class` + `sub_class` onto a PidSymbol `kind`.
 *
 * The backend taxonomy (canonical sub_class codes) is richer than the design's
 * glyph set, so several codes collapse onto `valve_gen` / `inst_field`. The
 * mapping is the single source of truth shared by the palette and the
 * on-stage entity rows so a given class always shows the same glyph.
 *
 * Unknown inputs return "valve_gen" — PidSymbol itself also falls back to it,
 * but returning it here keeps callers explicit.
 */
export function subClassToSymKind(entityClass: string | undefined, subClass: string | undefined): string {
  const ec = (entityClass || "").toLowerCase();
  const sc = (subClass || "").toUpperCase();

  if (ec === "valve") {
    switch (sc) {
      case "BV":
        return "valve_bv";
      case "BF":
        return "valve_bf";
      case "GT":
        return "valve_gt";
      case "CK":
        return "valve_ck";
      case "DB":
        return "valve_db";
      case "GL":
        return "valve_gl";
      case "CV":
        return "valve_cv";
      case "NCBV":
        return "valve_ncbv";
      case "PV":
        return "valve_pneuctrl";
      // VB / VF / VD / SB and any other valve code → generic valve glyph.
      default:
        return "valve_gen";
    }
  }

  if (ec === "instrument") {
    // FT / PT / TT / LT and any other transmitter/controller → field instrument.
    return "inst_field";
  }

  if (ec === "equipment") {
    if (sc === "PUMP") return "pump";
    if (sc === "MOTOR") return "Motor";
    return "inst_field";
  }

  return "valve_gen";
}
