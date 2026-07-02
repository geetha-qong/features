"""Drop orphan auto graph-nodes (no entity_id) superseded by an adopted
user-annotation node at the same position. Shared by the live GET /graph merge
and the frozen-GT builder so both stay identical (mirrors the reject-edge
omission pattern)."""
from typing import Any, Dict, List, Sequence, Set


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    # Guard: non-4-element inputs can't form a valid rect (parity with the TS twin).
    if len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def superseded_auto_ids(
    auto_nodes: List[Dict[str, Any]],
    annotation_nodes: List[Dict[str, Any]],
    iou_threshold: float = 0.5,
) -> Set[str]:
    # An orphan overlapping ANY adopted annotation at IoU >= 0.5 is superseded;
    # fine for typical P&ID symbol spacing (symbols are far enough apart that a
    # 0.5 IoU match is unambiguous — no two distinct symbols overlap that much).
    ann_boxes = [a.get("bbox") for a in annotation_nodes if a.get("bbox")]
    out: Set[str] = set()
    for n in auto_nodes:
        if (n.get("entity_id") or ""):
            continue  # has an entity — never an orphan
        box = n.get("bbox")
        nid = n.get("id")
        if not box or not nid:
            continue
        if any(bbox_iou(box, ab) >= iou_threshold for ab in ann_boxes):
            out.add(nid)
    return out
