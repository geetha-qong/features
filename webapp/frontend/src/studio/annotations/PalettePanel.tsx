/**
 * PalettePanel — left-rail symbol picker for "mark-symbol" mode.
 *
 * Hierarchy: category (valve / instrument / equipment) → sub_class button.
 * Click-to-arm semantics: clicking a sub_class sets `activeMarkClass` on the
 * parent; the canvas (PidCanvas) then drops a mark on the next canvas click.
 * Clicking the same button again disarms (toggles off).
 *
 * No HTML5 drag-and-drop — kept intentionally simple for v1; the spec
 * (docs/superpowers/specs/2026-06-10-qong-studio-marking-design.md §6) calls
 * out that click-to-arm is the chosen mark affordance.
 */
import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench, Activity, Boxes } from "lucide-react";
import { VALVE_SUB_CLASS_LABELS } from "./valveLabels";

interface ActiveMark {
  entity_class: string;
  sub_class: string;
}

interface PalettePanelProps {
  activeMarkClass: ActiveMark | null;
  onChange: (next: ActiveMark | null) => void;
  dark: boolean;
}

interface CategoryDef {
  key: "valve" | "instrument" | "equipment";
  label: string;
  Icon: typeof Wrench;
  items: Array<{ sub: string; label: string }>;
}

// Valve sub_classes — order matches the spec sheet. Labels come from
// buildElements.ts where possible to stay one-to-one with the human-readable
// strings used elsewhere in Studio.
const VALVE_ORDER: Array<{ sub: string; fallback: string }> = [
  { sub: "BV", fallback: "Ball Valve" },
  { sub: "GT", fallback: "Gate Valve" },
  { sub: "BF", fallback: "Butterfly Valve" },
  { sub: "CK", fallback: "Check Valve" },
  { sub: "DB", fallback: "Double Block" },
  { sub: "GL", fallback: "Globe Valve" },
  { sub: "CV", fallback: "Control Valve" },
  { sub: "NCBV", fallback: "NC Ball Valve" },
  { sub: "VB", fallback: "Block Valve" },
  { sub: "VF", fallback: "Flow Valve" },
  { sub: "VD", fallback: "Drain Valve" },
  { sub: "PV", fallback: "Pressure Valve" },
  { sub: "SB", fallback: "Sample/Bleed Valve" },
];

const INSTRUMENT_ITEMS = [
  { sub: "FT",  label: "Flow Tx" },
  { sub: "PT",  label: "Pressure Tx" },
  { sub: "TT",  label: "Temp Tx" },
  { sub: "LT",  label: "Level Tx" },
  { sub: "AT",  label: "Analytic Tx" },
  { sub: "PIC", label: "Pressure Controller" },
  { sub: "FIC", label: "Flow Controller" },
  { sub: "TIC", label: "Temp Controller" },
  { sub: "LIC", label: "Level Controller" },
];

const EQUIPMENT_ITEMS = [
  { sub: "Pump",      label: "Pump" },
  { sub: "Vessel",    label: "Vessel" },
  { sub: "Exchanger", label: "Exchanger" },
  { sub: "Tank",      label: "Tank" },
];

const CATEGORIES: CategoryDef[] = [
  {
    key: "valve",
    label: "Valves",
    Icon: Wrench,
    items: VALVE_ORDER.map(({ sub, fallback }) => ({
      sub,
      label: VALVE_SUB_CLASS_LABELS[sub] ?? fallback,
    })),
  },
  { key: "instrument", label: "Instruments", Icon: Activity, items: INSTRUMENT_ITEMS },
  { key: "equipment",  label: "Equipment",   Icon: Boxes,    items: EQUIPMENT_ITEMS },
];

export default function PalettePanel({
  activeMarkClass,
  onChange,
  dark,
}: PalettePanelProps) {
  // All categories open by default; intern feedback was that hunt-and-peck for
  // a sub_class behind a closed accordion lost too much momentum.
  const [open, setOpen] = useState<Record<string, boolean>>({
    valve: true,
    instrument: true,
    equipment: true,
  });

  const bg = dark ? "var(--bg-elev, #14162A)" : "var(--bg-elev, #ffffff)";
  const fg = dark ? "var(--fg, #E8EAF4)" : "var(--fg, #14162A)";
  const sub = dark ? "var(--ink-400, #9498AE)" : "var(--ink-600, #6B6F8A)";
  const border = dark ? "rgba(255,255,255,0.08)" : "rgba(20,22,42,0.08)";

  return (
    <div
      data-testid="palette-panel"
      style={{
        width: 220,
        background: bg,
        color: fg,
        borderRight: `1px solid ${border}`,
        padding: "var(--s-3, 12px) 0",
        fontFamily: "Outfit, sans-serif",
        display: "flex",
        flexDirection: "column",
        gap: "var(--s-2, 8px)",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          padding: "0 var(--s-3, 12px)",
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: sub,
          fontWeight: 600,
        }}
      >
        Symbol Palette
      </div>

      {CATEGORIES.map((cat) => {
        const isOpen = open[cat.key];
        return (
          <div key={cat.key} data-testid={`palette-cat-${cat.key}`}>
            <button
              type="button"
              onClick={() => setOpen((p) => ({ ...p, [cat.key]: !p[cat.key] }))}
              style={{
                width: "100%",
                background: "transparent",
                border: "none",
                color: fg,
                padding: "var(--s-2, 8px) var(--s-3, 12px)",
                display: "flex",
                alignItems: "center",
                gap: 8,
                cursor: "pointer",
                fontFamily: "Outfit, sans-serif",
                fontSize: 13,
                fontWeight: 600,
                textAlign: "left",
              }}
              aria-expanded={isOpen}
              aria-controls={`palette-list-${cat.key}`}
            >
              {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <cat.Icon size={14} style={{ color: "var(--qong-purple, #C73FBE)" }} />
              <span>{cat.label}</span>
              <span style={{ marginLeft: "auto", color: sub, fontSize: 11 }}>
                {cat.items.length}
              </span>
            </button>

            {isOpen && (
              <div
                id={`palette-list-${cat.key}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 6,
                  padding: "0 var(--s-3, 12px) var(--s-2, 8px)",
                }}
              >
                {cat.items.map((item) => {
                  const isActive =
                    activeMarkClass?.entity_class === cat.key &&
                    activeMarkClass?.sub_class === item.sub;
                  return (
                    <button
                      key={item.sub}
                      type="button"
                      data-testid={`palette-item-${cat.key}-${item.sub}`}
                      data-active={isActive ? "true" : "false"}
                      onClick={() => {
                        if (isActive) onChange(null);
                        else onChange({ entity_class: cat.key, sub_class: item.sub });
                      }}
                      title={`${item.label} (${item.sub})`}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 2,
                        padding: "var(--s-2, 8px) 6px",
                        borderRadius: "var(--r-2, 6px)",
                        border: isActive
                          ? "1px solid var(--qong-pink, #FF4DA8)"
                          : `1px solid ${border}`,
                        background: isActive
                          ? "var(--qong-pink, #FF4DA8)"
                          : "transparent",
                        color: isActive ? "#fff" : fg,
                        cursor: "pointer",
                        fontFamily: "Outfit, sans-serif",
                        transition: "background 0.12s ease, border-color 0.12s ease",
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "JetBrains Mono, monospace",
                          fontWeight: 700,
                          fontSize: 12,
                          letterSpacing: "0.04em",
                        }}
                      >
                        {item.sub}
                      </span>
                      <span
                        style={{
                          fontSize: 9,
                          textAlign: "center",
                          lineHeight: 1.1,
                          color: isActive ? "rgba(255,255,255,0.85)" : sub,
                          maxWidth: "100%",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {activeMarkClass && (
        <div
          style={{
            margin: "auto var(--s-3, 12px) 0",
            padding: "var(--s-2, 8px)",
            borderRadius: "var(--r-2, 6px)",
            background: "rgba(255,77,168,0.10)",
            border: "1px solid var(--qong-pink, #FF4DA8)",
            fontSize: 11,
            color: fg,
          }}
        >
          Armed:{" "}
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontWeight: 700 }}>
            {activeMarkClass.sub_class}
          </span>
          <div style={{ marginTop: 4, color: sub, fontSize: 10 }}>
            Click canvas to drop. Esc to disarm.
          </div>
        </div>
      )}
    </div>
  );
}
