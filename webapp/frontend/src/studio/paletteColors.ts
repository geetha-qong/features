/**
 * paletteColors — single source of truth for the per-class symbol colors.
 *
 * MOVED here verbatim from `annotations/PalettePanel.tsx` (the inline VALVE_ITEMS
 * / INSTRUMENT_ITEMS / EQUIPMENT_ITEMS tables). The palette imports `PALETTE`
 * from here so the left-sidebar colors/hotkeys stay identical; the canvas glyph
 * renderer reuses `colorForSubClass` / `colorForKind` so a class always shows
 * the same color in the palette AND on the stage.
 *
 * The map keys are the canonical lowercase `entity_class` strings the backend
 * uses ("valve", "instrument", "equipment") — matching PalettePanel's
 * category→entity_class scheme (CategoryDef.key, used as `sub_class`'s class).
 */
import { subClassToSymKind } from "./PidSymbol";

export const NEUTRAL_COLOR = "#9498AE";

export interface PaletteEntry {
  sub: string;
  label?: string;
  key?: string;
  color: string;
}

// MOVED from PalettePanel.tsx — exact sub codes + hex + hotkeys preserved.
// Grouped by entity_class. Valve labels are resolved in PalettePanel via
// VALVE_SUB_CLASS_LABELS, so they intentionally carry no `label` here.
export const PALETTE: Record<string, PaletteEntry[]> = {
  valve: [
    { sub: "BV", key: "2", color: "#86D8C4" },
    { sub: "BF", key: "1", color: "#FF6B6B" },
    { sub: "GT", key: "s", color: "#7EC9C2" },
    { sub: "CK", key: "4", color: "#D8C794" },
    { sub: "DB", key: "3", color: "#7FD4D2" },
    { sub: "GL", key: "5", color: "#A8DD92" },
    { sub: "CV", key: "6", color: "#C49AE2" },
    { sub: "NCBV", key: "g", color: "#86A8E8" },
    { sub: "VB", color: "#8EE0CE" },
    { sub: "VF", color: "#92B4E8" },
    { sub: "VD", color: "#EBA6C6" },
    { sub: "PV", key: "z", color: "#EB8070" },
    { sub: "SB", key: "d", color: "#C3B4EC" },
  ],
  instrument: [
    { sub: "FT", label: "Flow Tx", key: "8", color: "#E5CBA0" },
    { sub: "PT", label: "Pressure Tx", color: "#C5BCEC" },
    { sub: "TT", label: "Temp Tx", color: "#8585D6" },
    { sub: "LT", label: "Level Tx", color: "#B4ACE6" },
    { sub: "AT", label: "Analytic Tx", color: "#EC9696" },
    { sub: "PIC", label: "Pressure Controller", key: "x", color: "#C6C6CE" },
    { sub: "FIC", label: "Flow Controller", key: "c", color: "#ACDC90" },
    { sub: "TIC", label: "Temp Controller", color: "#ECA666" },
    { sub: "LIC", label: "Level Controller", color: "#EC8698" },
  ],
  equipment: [
    { sub: "Pump", label: "Pump", key: "e", color: "#8CCC76" },
    { sub: "Vessel", label: "Vessel", color: "#B496DC" },
    { sub: "Exchanger", label: "Exchanger", color: "#DCD486" },
    { sub: "Tank", label: "Tank", color: "#DCC68C" },
  ],
};

const SUB_INDEX = new Map<string, string>(); // "valve|BV" -> hex
for (const [cls, entries] of Object.entries(PALETTE))
  for (const e of entries) SUB_INDEX.set(`${cls}|${e.sub}`, e.color);

export function colorForSubClass(entityClass?: string, sub?: string): string {
  if (!entityClass || !sub) return NEUTRAL_COLOR;
  return SUB_INDEX.get(`${entityClass}|${sub}`) ?? NEUTRAL_COLOR;
}

// Derive kind -> color by running each palette sub through the shared mapper.
const KIND_INDEX = new Map<string, string>();
for (const [cls, entries] of Object.entries(PALETTE))
  for (const e of entries) {
    const kind = subClassToSymKind(cls, e.sub);
    if (!KIND_INDEX.has(kind)) KIND_INDEX.set(kind, e.color);
  }

export function colorForKind(kind?: string): string {
  if (!kind) return NEUTRAL_COLOR;
  return KIND_INDEX.get(kind) ?? NEUTRAL_COLOR;
}
