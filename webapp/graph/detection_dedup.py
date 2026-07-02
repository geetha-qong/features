"""Page-space non-max suppression to drop cross-tile duplicate detections.

Pages are tiled 3x3 with 20% overlap, so a glyph on a tile seam is detected
once per overlapping tile. This collapses same-class copies that overlap in
PAGE space (IoU >= threshold), keeping the highest-confidence representative.
Read-time + non-destructive: drops suppressed copies, never mutates a bbox.
Different classes never suppress each other (a BPCS circle and SIS diamond at
the same point both survive)."""
from typing import Any, Dict, List

from webapp.graph.orphan_dedup import bbox_iou


def _page_bbox(det: Dict[str, Any], tile_offsets: Dict[str, Any]):
    bbox = det.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    tile = det.get("tile")
    if tile:
        off = tile_offsets.get(tile)
        if off is None:
            # tile-local bbox for a page we have no offsets for (e.g. page >= 1).
            # Returning the raw bbox as page-space would make two distinct page-1
            # glyphs with the same tile-local rect hit IoU ~1.0 and be wrongly
            # suppressed.  Exclude from NMS entirely — pass through untouched.
            return None
        return [bbox[0] + off.x0, bbox[1] + off.y0, bbox[2] + off.x0, bbox[3] + off.y0]
    # No tile key → detection is already in page-space (synthetic / page-space input).
    return list(bbox)


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def dedupe_detections_page_space(
    detections: List[Dict[str, Any]],
    tile_offsets: Dict[str, Any],
    iou_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    page = [_page_bbox(d, tile_offsets) for d in detections]
    # Indices that have a usable page bbox participate in NMS; others pass through.
    idx = [i for i, p in enumerate(page) if p is not None]
    # Sort candidates by confidence desc, then area desc (tie-break).
    idx.sort(key=lambda i: (detections[i].get("confidence") or 0.0, _area(page[i])), reverse=True)
    suppressed = set()
    for a_pos, i in enumerate(idx):
        if i in suppressed:
            continue
        for j in idx[a_pos + 1:]:
            if j in suppressed:
                continue
            if detections[i].get("label") != detections[j].get("label"):
                continue
            if bbox_iou(page[i], page[j]) >= iou_threshold:
                suppressed.add(j)
    return [d for k, d in enumerate(detections) if k not in suppressed]


def enforce_one_to_one(detections: List[Dict[str, Any]]) -> None:
    """Ensure each entity_id is bound to at most one detection. For any
    entity_id on >1 detection keep the best (has entity_tag, then highest
    confidence) and unmatch the rest (entity_id=None; keep entity_tag so the
    label still shows -> the extra glyph becomes an adoptable type-B node)."""
    by_eid: Dict[str, List[Dict[str, Any]]] = {}
    for d in detections:
        eid = d.get("entity_id")
        if eid:
            by_eid.setdefault(str(eid), []).append(d)
    for eid, group in by_eid.items():
        if len(group) <= 1:
            continue
        group.sort(key=lambda d: (bool(d.get("entity_tag")), d.get("confidence") or 0.0), reverse=True)
        for d in group[1:]:
            d["entity_id"] = None
