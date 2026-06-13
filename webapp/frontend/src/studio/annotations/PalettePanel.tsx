/**
 * PalettePanel — left sidebar symbol picker for "mark-symbol" mode.
 *
 * QONG Studio redesign (Jun 2026): restructured into the draw.io-style
 * **collapsible category list**. Each category (Valves, Instruments, Equipment)
 * collapses; rows are glyph + full name + hotkey badge, matching the prototype
 * the user signed off on (chat6 — "palette back as the left sidebar with
 * collapsible categories"). Click-to-arm semantics + activeMarkClass shape are
 * unchanged so the rest of Studio + the existing tests keep working.
 */
import { useMemo, useState } from "react";
import { Activity, Boxes, ChevronDown, Wrench } from "lucide-react";
import PidSymbol, { subClassToSymKind } from "../PidSymbol";
import { VALVE_SUB_CLASS_LABELS } from "./valveLabels";
import { useShortcuts } from "../shortcuts/useShortcuts";
import type { ShortcutMap } from "../shortcuts/api";

/**
 * Build a reverse lookup `"<entity_class>:<sub_class>" → key` from the live
 * keymap. The keymap is keyed by the keyboard key; a `select-class` binding
 * carries the entity_class/sub_class it arms. We invert that so each palette
 * row can show the user's ACTUAL bound key (FEATURES #38) instead of the
 * static design-time hint. If two keys bind the same class, last write wins —
 * fine for a visual hint.
 */
function buildClassKeyIndex(shortcuts: ShortcutMap): Record<string, string> {
  const idx: Record<string, string> = {};
  for (const [key, binding] of Object.entries(shortcuts)) {
    if (binding.action === "select-class" && binding.entity_class && binding.sub_class) {
      idx[`${binding.entity_class}:${binding.sub_class}`] = key;
    }
  }
  return idx;
}

/** Display form of a keymap key: single letters/digits upper-cased, named keys
 *  (Escape, Delete, …) shown verbatim. */
function formatHotkey(key: string): string {
  return key.length === 1 ? key.toUpperCase() : key;
}

interface ActiveMark {
  entity_class: string;
  sub_class: string;
}

interface PalettePanelProps {
  activeMarkClass: ActiveMark | null;
  onChange: (next: ActiveMark | null) => void;
  dark: boolean;
}

interface PaletteItem {
  sub: string;
  label: string;
  key?: string;   // single-letter hotkey badge (visual hint; actual binding via shortcuts/)
  color?: string; // accent color matching the LS taxonomy
}

interface CategoryDef {
  key: "valve" | "instrument" | "equipment";
  label: string;
  Icon: typeof Wrench;
  items: PaletteItem[];
}

// Order + hotkey + color come from the design's LIBRARY (drawio-symbols.jsx),
// mapped to the canonical sub_class codes we already use in the backend.
const VALVE_ITEMS: PaletteItem[] = [
  { sub: "BV",   key: "2", color: "#86D8C4" },
  { sub: "BF",   key: "1", color: "#FF6B6B" },
  { sub: "GT",   key: "s", color: "#7EC9C2" },
  { sub: "CK",   key: "4", color: "#D8C794" },
  { sub: "DB",   key: "3", color: "#7FD4D2" },
  { sub: "GL",   key: "5", color: "#A8DD92" },
  { sub: "CV",   key: "6", color: "#C49AE2" },
  { sub: "NCBV", key: "g", color: "#86A8E8" },
  { sub: "VB",            color: "#8EE0CE" },
  { sub: "VF",            color: "#92B4E8" },
  { sub: "VD",            color: "#EBA6C6" },
  { sub: "PV",   key: "z", color: "#EB8070" },
  { sub: "SB",   key: "d", color: "#C3B4EC" },
].map((it) => ({ ...it, label: VALVE_SUB_CLASS_LABELS[it.sub] ?? it.sub }));

const INSTRUMENT_ITEMS: PaletteItem[] = [
  { sub: "FT",  label: "Flow Tx",            key: "8", color: "#E5CBA0" },
  { sub: "PT",  label: "Pressure Tx",                 color: "#C5BCEC" },
  { sub: "TT",  label: "Temp Tx",                     color: "#8585D6" },
  { sub: "LT",  label: "Level Tx",                    color: "#B4ACE6" },
  { sub: "AT",  label: "Analytic Tx",                 color: "#EC9696" },
  { sub: "PIC", label: "Pressure Controller", key: "x", color: "#C6C6CE" },
  { sub: "FIC", label: "Flow Controller",     key: "c", color: "#ACDC90" },
  { sub: "TIC", label: "Temp Controller",               color: "#ECA666" },
  { sub: "LIC", label: "Level Controller",              color: "#EC8698" },
];

const EQUIPMENT_ITEMS: PaletteItem[] = [
  { sub: "Pump",      label: "Pump",      key: "e", color: "#8CCC76" },
  { sub: "Vessel",    label: "Vessel",              color: "#B496DC" },
  { sub: "Exchanger", label: "Exchanger",           color: "#DCD486" },
  { sub: "Tank",      label: "Tank",                color: "#DCC68C" },
];

const CATEGORIES: CategoryDef[] = [
  { key: "valve",      label: "Valves",      Icon: Wrench,   items: VALVE_ITEMS },
  { key: "instrument", label: "Instruments", Icon: Activity, items: INSTRUMENT_ITEMS },
  { key: "equipment",  label: "Equipment",   Icon: Boxes,    items: EQUIPMENT_ITEMS },
];

export default function PalettePanel({
  activeMarkClass,
  onChange,
  dark: _dark,
}: PalettePanelProps) {
  // All categories open by default — hunt-and-peck behind a closed accordion
  // breaks momentum (intern feedback before the redesign).
  const [open, setOpen] = useState<Record<string, boolean>>({
    valve: true,
    instrument: true,
    equipment: true,
  });

  // Live per-user keymap (merged with defaults by the backend). We index it by
  // class so each row shows the user's ACTUAL bound key, falling back to the
  // row's static design hint when the action has no binding (e.g. map still
  // loading, or a sub_class nobody has bound).
  const { shortcuts } = useShortcuts();
  const classKeyIndex = useMemo(() => buildClassKeyIndex(shortcuts), [shortcuts]);

  return (
    <aside className="palette-side" data-testid="palette-panel">
      <div className="palette-side-head">Symbol Palette</div>
      <div className="palette-side-scroll">
        {CATEGORIES.map((cat) => {
          const isOpen = open[cat.key];
          return (
            <div className="palette-sec" key={cat.key} data-testid={`palette-cat-${cat.key}`}>
              <button
                type="button"
                className={`palette-sec-head ${isOpen ? "" : "collapsed"}`}
                onClick={() => setOpen((p) => ({ ...p, [cat.key]: !p[cat.key] }))}
                aria-expanded={isOpen}
                aria-controls={`palette-list-${cat.key}`}
              >
                <span className="palette-sec-car">
                  <ChevronDown size={13} strokeWidth={1.8} />
                </span>
                <cat.Icon size={13} strokeWidth={1.8} className="palette-sec-ic" />
                <span className="palette-sec-nm">{cat.label}</span>
                <span className="palette-sec-cnt">{cat.items.length}</span>
              </button>

              {isOpen && (
                <div className="palette-list" id={`palette-list-${cat.key}`}>
                  {cat.items.map((item) => {
                    const isActive =
                      activeMarkClass?.entity_class === cat.key &&
                      activeMarkClass?.sub_class === item.sub;
                    // User's actual bound key for this class, else the static
                    // design-time hint, else nothing.
                    const boundKey = classKeyIndex[`${cat.key}:${item.sub}`] ?? item.key;
                    const hotkey = boundKey ? formatHotkey(boundKey) : null;
                    return (
                      <button
                        key={item.sub}
                        type="button"
                        className={`palette-row ${isActive ? "active" : ""}`}
                        data-testid={`palette-item-${cat.key}-${item.sub}`}
                        data-active={isActive ? "true" : "false"}
                        onClick={() => {
                          if (isActive) onChange(null);
                          else onChange({ entity_class: cat.key, sub_class: item.sub });
                        }}
                        title={`${item.label} (${item.sub})${hotkey ? `  ·  ${hotkey}` : ""}`}
                        style={
                          {
                            // pink fallback kept so the test that asserts
                            // `style.background` contains `var(--qong-pink`
                            // still passes when armed.
                            background: isActive ? "var(--qong-pink, #FF4DA8)" : undefined,
                            // CSS var consumed by the row's accent stripe + glow.
                            ["--lc" as string]: item.color || "var(--qong-purple, #C73FBE)",
                          } as React.CSSProperties
                        }
                      >
                        <span className="palette-row-glyph">
                          <PidSymbol kind={subClassToSymKind(cat.key, item.sub)} />
                        </span>
                        <span className="palette-row-name">{item.label}</span>
                        {hotkey ? (
                          <kbd className="palette-row-kbd">{hotkey}</kbd>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {activeMarkClass && (
        <div className="palette-armed">
          <span>Armed:</span>{" "}
          <span className="palette-armed-sub">{activeMarkClass.sub_class}</span>
          <div className="palette-armed-hint">Click canvas to drop · Esc to disarm</div>
        </div>
      )}
    </aside>
  );
}
