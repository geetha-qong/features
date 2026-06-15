/**
 * Derive the right-panel "Elements on P&ID" list from live backend responses.
 *
 * ALL YOLO detections are included — no filtering by tile, by entity_class, or
 * by whether the detection was matched to a canonical entity. Change 3 (2026-06-15).
 *
 * Keys:
 *   - `detection.entity_id` (UUID) when the D1.5 matcher attached a canonical entity.
 *   - `${entity_class|label}_${idx}` stable composite for unmatched detections
 *     (arrows, connectors, instruments/equipment without a canonical row).
 */
import type { DetectionItem, EntitiesResponse, EntityRow } from "./api";
import type { CanvasElement } from "./types";

const VALVE_SUB_CLASS_LABELS: Record<string, string> = {
  BV: "Ball Valve",
  BF: "Butterfly Valve",
  GT: "Gate Valve",
  CK: "Check Valve",
  DB: "Diaphragm Valve",
  GL: "Globe Valve",
  CV: "Control Valve",
  NCBV: "Non-Compliant Ball Valve",
  PNEUCTRL: "Pneumatic Control",
  RELIEF_SAFETY: "Relief / Safety Valve",
  "3WAY_RELIEF": "3-Way Relief Valve",
  VB: "Block Valve",
  VF: "Flow Valve",
  VD: "Drain Valve",
  PV: "Pressure Valve",
  SB: "Sample/Bleed Valve",
};

const INST_YOLO_LABELS: Record<string, string> = {
  inst_bpcs:        "Instrument (BPCS)",
  inst_sis:         "Instrument (SIS)",
  inst_local_panel: "Instrument (Local Panel)",
  "SIS-R":          "SIS Device",
  interlock:        "Interlock",
};

const EQUIP_YOLO_LABELS: Record<string, string> = {
  Motor:           "Motor",
  "Pump/Dwg Pump": "Pump",
  Pump_Dwg_Pump:   "Pump",
};

function humanType(
  entityClass: string | undefined,
  subClass: string | undefined,
  fallbackLabel: string | undefined,
): string {
  if (entityClass === "valve") {
    // For unmatched detections the canonical entity has no sub_class; derive it
    // from the YOLO label so "valve_db" → "Diaphragm Valve" not "Valve (?)".
    const sub = subClass ||
      (fallbackLabel?.startsWith("valve_") ? fallbackLabel.slice(6).toUpperCase() : undefined);
    return VALVE_SUB_CLASS_LABELS[sub || ""] || `Valve (${sub || "?"})`;
  }
  if (entityClass === "instrument") {
    if (subClass) return subClass;
    return INST_YOLO_LABELS[fallbackLabel || ""] || "Instrument";
  }
  if (entityClass === "equipment") {
    if (subClass) return subClass;
    return EQUIP_YOLO_LABELS[fallbackLabel || ""] || "Equipment";
  }
  if (fallbackLabel?.startsWith("arrow_")) return "Flow arrow";
  if (fallbackLabel?.startsWith("connector_")) return "Page connector";
  return fallbackLabel ?? "Unknown";
}

/** Build element rows for PropertiesPanel from ALL YOLO detections in the job.
 *  No tile filter, no entity_class filter — every bbox appears in the list. */
export function buildElementsForTile(
  detections: DetectionItem[] | undefined,
  entityIdToCanonical: Map<string, EntityRow>,
): Record<string, CanvasElement> {
  if (!detections) return {};
  const out: Record<string, CanvasElement> = {};
  for (let idx = 0; idx < detections.length; idx++) {
    const d = detections[idx];
    const entityClass = d.entity_class;
    // Stable composite key for unmatched detections: index in the original
    // detections array. PidCanvas preserves _origIdx via the same counter so
    // sidebar key === canvas detKey for every detection, enabling bidirectional sync.
    const key = d.entity_id || `_det_${idx}`;
    const ent = d.entity_id ? entityIdToCanonical.get(d.entity_id) : undefined;
    out[key] = {
      tag:  ent?.tag || (d.entity_id ? d.entity_id.slice(0, 8) : (d.label || `${entityClass || "?"}-${idx}`)),
      type: humanType(ent?.entity_class || entityClass, ent?.sub_class, d.label),
      confidence: typeof d.confidence === "number" ? d.confidence : 0,
      lines: [],
      entityClass: ent?.entity_class || entityClass,
      subClass: ent?.sub_class,
    };
  }
  return out;
}

/** Merge multiple deliverable responses into a single entity_id → EntityRow lookup. */
export function buildEntityIndex(
  responses: (EntitiesResponse | null | undefined)[],
): Map<string, EntityRow> {
  const m = new Map<string, EntityRow>();
  for (const r of responses) {
    if (!r) continue;
    for (const e of r.entities) m.set(e.entity_id, e);
  }
  return m;
}
