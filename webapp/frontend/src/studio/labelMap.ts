/**
 * Display-name maps for canvas labels.
 *
 * Two code spaces feed labels onto the canvas, and both need a single
 * user-facing human name:
 *
 *  1. **YOLO model codes** (e.g. `valve_bf`, `inst_field`, `arrow_right`) —
 *     attached to `DetectionItem.label`. Come straight from the trained ONNX
 *     class list (FEATURES #28/#30/#31). The model knows nothing about CSV
 *     terminology, so these are the canonical inference surface.
 *  2. **Canonical sub_class codes** (e.g. `BV`, `BF`, `FT`, `Pump`) — attached
 *     to `UserAnnotation.sub_class`. These are the human-typed picker codes,
 *     also surfaced by the canonical_entities DB index (FEATURES #34).
 *
 * Both eventually mean the same thing on a P&ID. We keep the codes (model and
 * canonical) so the backend can stay stable, but the canvas always renders
 * the corresponding **human name** so reviewers don't have to memorise codes
 * like `valve_ncbv`. See FEATURES #40 — user requirement that "labels we gave
 * are not working properly… show proper labels".
 *
 * Adding a new label?
 *  - If it's a new YOLO class: add it to `MODEL_LABEL_NAMES`.
 *  - If it's a new canonical sub_class (from canonical_entities / user-picker):
 *    add it to `SUB_CLASS_NAMES`.
 */

/** YOLO model class codes → human label.
 *
 *  Source: webapp/routers/api_v1.py `_yolo_class_to_canonical` + the 23-class
 *  v1-10 model class list. Keep alphabetised within each section. */
export const MODEL_LABEL_NAMES: Record<string, string> = {
  // Valves
  valve_bf: "Butterfly Valve",
  valve_bv: "Ball Valve",
  valve_ck: "Check Valve",
  valve_cv: "Control Valve",
  valve_db: "Diaphragm Valve",
  valve_gen: "Valve",
  valve_gl: "Globe Valve",
  valve_gt: "Gate Valve",
  valve_ncbv: "NC Ball Valve",
  valve_pneuctrl: "Pneumatic Valve",
  valve_relief_safety: "Relief / Safety Valve",
  valve_3way: "3-Way Valve",
  valve_3way_relief: "3-Way Relief Valve",
  valve_needle: "Needle Valve",
  valve_reflex_gt: "Reflex Gate Valve",
  valve_transfer: "Transfer Valve",
  // Instruments
  inst_field: "Field Instrument",
  "inst_field-R": "Field Instrument (R)",
  inst_local_panel: "Local Panel Instrument",
  inst_bpcs: "BPCS Instrument",
  inst_sis: "SIS Instrument",
  // Control & logic
  DCS: "Distributed Control",
  PLC: "Logic Controller",
  interlock: "Interlock",
  "interlock-R": "Interlock (R)",
  "SIS-R": "Safety Logic (SIS-R)",
  // Equipment
  Motor: "Motor",
  pump: "Pump",
  // Indicators
  lamp: "Indicator Lamp",
  lamp_local_mounted: "Lamp (Local)",
  // Arrows + connectors (rendered as visual aids, not entities)
  arrow_right: "Flow →",
  arrow_left: "Flow ←",
  arrow_up: "Flow ↑",
  arrow_down: "Flow ↓",
  connector_in: "Connector In",
  connector_out: "Connector Out",
  connector_io: "Connector I/O",
};

/** Canonical sub_class codes → human label.
 *
 *  Source: webapp/deliverables/canonical_db_index.py + the canonical_entities
 *  backfill. Mirrors the table inside buildElements.ts (extended). */
export const SUB_CLASS_NAMES: Record<string, string> = {
  // Valves — YOLO vocabulary
  BV: "Ball Valve",
  BF: "Butterfly Valve",
  GT: "Gate Valve",
  CK: "Check Valve",
  DB: "Diaphragm Valve",
  GL: "Globe Valve",
  CV: "Control Valve",
  NCBV: "NC Ball Valve",
  PNEUCTRL: "Pneumatic Valve",
  RELIEF_SAFETY: "Relief / Safety Valve",
  "3WAY_RELIEF": "3-Way Relief Valve",
  // Valves — customer/CSV codes from canonical_entities
  VB: "Block Valve",
  VF: "Flow Valve",
  VD: "Drain Valve",
  PV: "Pressure Valve",
  SB: "Sample/Bleed Valve",
  // Instruments (sub_class on canonical_entities + PalettePanel rows)
  FT:  "Flow Tx",
  PT:  "Pressure Tx",
  TT:  "Temperature Tx",
  LT:  "Level Tx",
  AT:  "Analytic Tx",
  PIC: "Pressure Ctrl",
  FIC: "Flow Ctrl",
  TIC: "Temperature Ctrl",
  LIC: "Level Ctrl",
  // Equipment
  Pump:      "Pump",
  Vessel:    "Vessel",
  Exchanger: "Exchanger",
  Tank:      "Tank",
};

/** Best human label for a YOLO detection on the canvas. Falls back to the raw
 *  code if we haven't mapped it yet (better visible than blank). */
export function displayNameForModelLabel(label?: string | null): string {
  if (!label) return "";
  return MODEL_LABEL_NAMES[label] ?? label;
}

/** Best human label for a canonical sub_class on the canvas. */
export function displayNameForSubClass(sub?: string | null): string {
  if (!sub) return "";
  return SUB_CLASS_NAMES[sub] ?? sub;
}

/** Compact label for the canvas — first non-empty of:
 *    1. the tag (e.g. "FT-101") — the engineer's identity, always wins
 *    2. placeholder_tag (assigned at mark-time for review)
 *    3. human name for the sub_class (e.g. "Ball Valve")
 *    4. human name for the model label (e.g. "Field Instrument")
 *    5. raw fallback so something always renders */
export function canvasDisplayLabel(opts: {
  tag?: string | null;
  placeholder_tag?: string | null;
  sub_class?: string | null;
  model_label?: string | null;
}): string {
  if (opts.tag) return opts.tag;
  if (opts.placeholder_tag) return opts.placeholder_tag;
  const sub = displayNameForSubClass(opts.sub_class);
  if (sub) return sub;
  const mod = displayNameForModelLabel(opts.model_label);
  if (mod) return mod;
  return "?";
}
