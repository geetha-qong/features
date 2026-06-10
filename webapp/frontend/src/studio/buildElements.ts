/**
 * Derive the right-panel "Selected Element" + "Elements on Sheet" data from
 * live backend responses — replaces the prototype `DEMO_ELEMENT_DATA` fallback
 * that used to render even after real detections were loaded.
 *
 * Keyed by `detection.entity_id` (UUID) so the same key drives both the panel
 * row click and the DatasheetDrawer's `entityId` prop. Detections without an
 * `entity_id` (direction labels, arrows, page connectors — non-editable per
 * FEATURES #31) are intentionally excluded; they're visual aids only.
 */
import type { DetectionItem, EntitiesResponse, EntityRow } from "./api";
import type { CanvasElement } from "./types";

// Human-readable names for the valve sub_class field. Mirrors the
// `_yolo_class_to_canonical` mapping in webapp/routers/api_v1.py so the
// label on screen matches what the backend matcher used to key the entity.
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
};

function humanType(
  entityClass: string | undefined,
  subClass: string | undefined,
  fallbackLabel: string | undefined,
): string {
  if (entityClass === "valve") {
    return VALVE_SUB_CLASS_LABELS[subClass || ""] || `Valve (${subClass || "?"})`;
  }
  if (entityClass === "instrument") return "Instrument";
  if (entityClass === "equipment") return "Equipment";
  if (fallbackLabel?.startsWith("arrow_")) return "Flow arrow";
  if (fallbackLabel?.startsWith("connector_")) return "Page connector";
  return fallbackLabel ?? "Unknown";
}

/** Per-tile element rows for PropertiesPanel. Keys are `entity_id` UUIDs. */
export function buildElementsForTile(
  detections: DetectionItem[] | undefined,
  entityIdToCanonical: Map<string, EntityRow>,
  activeTileFilename: string | null,
): Record<string, CanvasElement> {
  if (!detections || !activeTileFilename) return {};
  const out: Record<string, CanvasElement> = {};
  for (const d of detections) {
    if (d.tile !== activeTileFilename) continue;
    if (!d.entity_id) continue;
    const ent = entityIdToCanonical.get(d.entity_id);
    out[d.entity_id] = {
      tag: ent?.tag || d.entity_id.slice(0, 8),
      type: humanType(ent?.entity_class, ent?.sub_class, d.label),
      confidence: typeof d.confidence === "number" ? d.confidence : 0,
      lines: [],
      entityClass: ent?.entity_class || d.entity_class,
    };
  }
  return out;
}

/** Merge multiple deliverable responses (valve_list + instrument_index + ...)
 *  into a single entity_id → EntityRow lookup. Later payloads can't collide
 *  in practice since each EntityRow belongs to one entity_class, but the Map
 *  semantics make "last write wins" the explicit contract anyway. */
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
