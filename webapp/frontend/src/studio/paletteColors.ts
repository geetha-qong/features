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
import { COLOR_BY_KEY } from "./taxonomy.generated";

export const NEUTRAL_COLOR = "#9498AE";

export interface PaletteEntry {
  sub: string;
  label?: string;
  key?: string;
  color: string;
}

// Palette membership + sub-class display order live here (unchanged from the
// original PalettePanel tables); the HEX COLOR for each entry is now sourced
// from the generated taxonomy module (taxonomy.generated.ts → COLOR_BY_KEY),
// whose values come from webapp/taxonomy.json — the single source of truth.
//
// Valve labels are resolved in PalettePanel via VALVE_SUB_CLASS_LABELS, so they
// intentionally carry no `label` here.
//
// HOTKEY HINTS: intentionally NOT defined here. The palette badge is sourced
// from the live merged-with-defaults shortcut map (PalettePanel's
// buildClassKeyIndex over GET /users/me/shortcuts). Hard-coding `key` here
// caused a stale-hint bug: digits 1/2/3 are reserved for mode switching
// (select / mark-symbol / draw-edge, see routers/shortcuts.py DEFAULT_SHORTCUTS),
// so an unbound class like "DB" fell back to the static "3" and pressing it
// triggered draw-edge instead of selecting the class. Unbound classes now show
// no badge until the user assigns one at /account/shortcuts.

// (entity_class, sub) order + optional palette label. Color is filled from the
// generated map below so a class shows one consistent hex everywhere.
const PALETTE_LAYOUT: Record<string, { sub: string; label?: string }[]> = {
  valve: [
    { sub: "BV" },
    { sub: "BF" },
    { sub: "GT" },
    { sub: "CK" },
    { sub: "DB" },
    { sub: "GL" },
    { sub: "CV" },
    { sub: "NCBV" },
    { sub: "VB" },
    { sub: "VF" },
    { sub: "VD" },
    { sub: "PV" },
    { sub: "SB" },
    { sub: "RELIEF_SAFETY" },
    { sub: "3WAY_RELIEF" },
  ],
  instrument: [
    { sub: "FT", label: "Flow Tx" },
    { sub: "PT", label: "Pressure Tx" },
    { sub: "TT", label: "Temp Tx" },
    { sub: "LT", label: "Level Tx" },
    { sub: "AT", label: "Analytic Tx" },
    { sub: "PIC", label: "Pressure Controller" },
    { sub: "FIC", label: "Flow Controller" },
    { sub: "TIC", label: "Temp Controller" },
    { sub: "LIC", label: "Level Controller" },
    { sub: "interlock", label: "Interlock" },
    { sub: "BPCS", label: "BPCS" },
    { sub: "SIS", label: "SIS" },
  ],
  equipment: [
    { sub: "Pump", label: "Pump" },
    { sub: "Motor", label: "Motor" },
    { sub: "Vessel", label: "Vessel" },
    { sub: "Exchanger", label: "Exchanger" },
    { sub: "Tank", label: "Tank" },
  ],
  annotation: [
    { sub: "arrow_up",      label: "Arrow Up" },
    { sub: "arrow_down",    label: "Arrow Down" },
    { sub: "arrow_left",    label: "Arrow Left" },
    { sub: "arrow_right",   label: "Arrow Right" },
    { sub: "connector_in",  label: "Connector In" },
    { sub: "connector_out", label: "Connector Out" },
  ],
};

function paletteColor(cls: string, sub: string): string {
  return COLOR_BY_KEY[`${cls}|${sub}`] ?? NEUTRAL_COLOR;
}

export const PALETTE: Record<string, PaletteEntry[]> = Object.fromEntries(
  Object.entries(PALETTE_LAYOUT).map(([cls, entries]) => [
    cls,
    entries.map((e) => ({ ...e, color: paletteColor(cls, e.sub) })),
  ]),
);

export function colorForSubClass(entityClass?: string, sub?: string): string {
  if (!entityClass || !sub) return NEUTRAL_COLOR;
  return COLOR_BY_KEY[`${entityClass}|${sub}`] ?? NEUTRAL_COLOR;
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
