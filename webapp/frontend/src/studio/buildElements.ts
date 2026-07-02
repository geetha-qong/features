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
import { DISPLAY_NAME_BY_SUB } from "./taxonomy.generated";

// Sourced from the generated taxonomy module (single source of truth). This
// used to be a private hand-maintained copy that had drifted from valveLabels.ts
// / labelMap.ts (DB="Diaphragm Valve", NCBV="Non-Compliant Ball Valve",
// PNEUCTRL="Pneumatic Control"); it now reads the reconciled taxonomy so a code
// renders the same name on the stage, palette, canvas, and exports.
const VALVE_SUB_CLASS_LABELS: Record<string, string> = DISPLAY_NAME_BY_SUB;

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

function iou(a: number[], b: number[]): number {
  const [ax1, ay1, ax2, ay2] = a;
  const [bx1, by1, bx2, by2] = b;
  const ix1 = Math.max(ax1, bx1), iy1 = Math.max(ay1, by1);
  const ix2 = Math.min(ax2, bx2), iy2 = Math.min(ay2, by2);
  const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
  if (inter === 0) return 0;
  const aA = (ax2 - ax1) * (ay2 - ay1);
  const bA = (bx2 - bx1) * (by2 - by1);
  return inter / (aA + bA - inter);
}

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

/** Build element rows for PropertiesPanel from YOLO detections + canonical entities.
 *
 * Only detections matched to a canonical entity (entity_id set) are included —
 * unmatched YOLO bboxes inflate the sidebar with raw class labels and tile-duplicates.
 * Canonical entities with no YOLO detection on this sheet are excluded so the
 * "Elements on P&ID" count matches exactly what was visually detected.
 */
export function buildElementsForTile(
  detections: DetectionItem[] | undefined,
  entityIdToCanonical: Map<string, EntityRow>,
): Record<string, CanvasElement> {
  if (!detections) return {};

  // Safety-net dedup: if two matched detections share entity_id and IoU > 0.5,
  // keep the one with higher confidence (first wins on tie).
  const bestByEntityId = new Map<string, DetectionItem>();
  for (const d of detections) {
    if (!d.entity_id) continue;
    const prev = bestByEntityId.get(d.entity_id);
    if (!prev) { bestByEntityId.set(d.entity_id, d); continue; }
    const prevBbox = Array.isArray(prev.bbox) ? (prev.bbox as number[]) : null;
    const curBbox  = Array.isArray(d.bbox)    ? (d.bbox  as number[]) : null;
    if (prevBbox && curBbox && iou(prevBbox, curBbox) <= 0.5) continue;
    const prevConf = typeof prev.confidence === "number" ? prev.confidence : 0;
    const curConf  = typeof d.confidence   === "number" ? d.confidence   : 0;
    if (curConf > prevConf) bestByEntityId.set(d.entity_id, d);
  }
  const deduped = detections.filter(
    d => !d.entity_id || bestByEntityId.get(d.entity_id) === d,
  );

  const out: Record<string, CanvasElement> = {};

  for (let idx = 0; idx < deduped.length; idx++) {
    const d = deduped[idx];
    const entityClass = d.entity_class;
    const ent = d.entity_id ? entityIdToCanonical.get(d.entity_id) : undefined;

    // Skip all unmatched detections — any YOLO bbox without a canonical entity
    // match inflates the sidebar with raw class labels and tile-duplicates.
    if (!d.entity_id || !ent) continue;

    out[d.entity_id] = {
      tag:  ent?.tag || humanType(ent?.entity_class || entityClass, ent?.sub_class, d.label),
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
