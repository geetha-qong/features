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
import { PALETTE } from "../paletteColors";
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

// Order + hotkey + color now live in `../paletteColors` (PALETTE) — the single
// source of truth shared with the canvas glyph renderer. We just resolve each
// entry's display label here: valves come from VALVE_SUB_CLASS_LABELS,
// instruments/equipment carry their own `label`, falling back to the sub code.
const VALVE_ITEMS: PaletteItem[] = PALETTE.valve.map((it) => ({
  ...it,
  label: VALVE_SUB_CLASS_LABELS[it.sub] ?? it.sub,
}));

const INSTRUMENT_ITEMS: PaletteItem[] = PALETTE.instrument.map((it) => ({
  ...it,
  label: it.label ?? it.sub,
}));

const EQUIPMENT_ITEMS: PaletteItem[] = PALETTE.equipment.map((it) => ({
  ...it,
  label: it.label ?? it.sub,
}));

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
