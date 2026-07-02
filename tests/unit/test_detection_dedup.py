import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.detection_dedup import dedupe_detections_page_space


class _Box:
    def __init__(self, x0, y0): self.x0, self.y0 = x0, y0


def test_overlapping_same_class_collapse_keep_highest_conf():
    # Same glyph in two tiles whose offsets place them at the same page point.
    dets = [
        {"label": "inst_field", "tile": "A", "bbox": [10, 10, 30, 30], "confidence": 0.7},
        {"label": "inst_field", "tile": "B", "bbox": [0, 0, 20, 20], "confidence": 0.9},
    ]
    offs = {"A": _Box(0, 0), "B": _Box(10, 10)}  # B's box → page [10,10,30,30] == A
    out = dedupe_detections_page_space(dets, offs)
    assert len(out) == 1
    assert out[0]["confidence"] == 0.9  # highest-confidence survivor


def test_different_class_same_location_both_kept():
    dets = [
        {"label": "inst_field", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
        {"label": "inst_sis", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
    ]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 2  # BPCS circle + SIS diamond both survive


def test_distinct_adjacent_same_class_both_kept():
    dets = [
        {"label": "valve_bv", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
        {"label": "valve_bv", "tile": "A", "bbox": [100, 100, 120, 120], "confidence": 0.8},
    ]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 2  # low IoU → not merged


def test_unknown_tile_uses_bbox_as_is_and_passes_through():
    # Single detection on an unknown tile — must still pass through (len == 1).
    dets = [{"label": "valve_bv", "tile": "ZZZ", "bbox": [0, 0, 20, 20], "confidence": 0.5}]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 1


def test_two_unknown_tiles_same_local_bbox_both_survive():
    # Regression for multi-page false-merge:
    # Two genuinely distinct glyphs on page>=1 with IDENTICAL tile-local rects
    # but DIFFERENT tiles.  Under the old code both mapped to [0,0,20,20] in
    # "page space" → IoU 1.0 → one was wrongly suppressed.
    # With the fix, unknown-tile detections are excluded from NMS entirely and
    # both must survive.
    dets = [
        {"label": "valve_bv", "tile": "tile_p1_r0_c0.png", "bbox": [0, 0, 20, 20], "confidence": 0.8},
        {"label": "valve_bv", "tile": "tile_p1_r0_c1.png", "bbox": [0, 0, 20, 20], "confidence": 0.8},
    ]
    # offsets only contain a page-0 tile — neither page-1 tile is present
    offs = {"tile_p0_r0_c0.png": _Box(0, 0)}
    out = dedupe_detections_page_space(dets, offs)
    assert len(out) == 2, (
        f"Expected both page-1 detections to survive NMS; got {len(out)}"
    )


def test_missing_bbox_passes_through():
    dets = [{"label": "valve_bv", "tile": "A"}]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert out == dets


def test_enforce_one_to_one_keeps_best_unmatches_rest():
    from webapp.graph.detection_dedup import enforce_one_to_one
    dets = [
        {"entity_id": "E1", "entity_tag": "61-HS-00471", "confidence": 0.6},
        {"entity_id": "E1", "entity_tag": "61-HS-00471", "confidence": 0.9},
        {"entity_id": "E2", "entity_tag": "61-FT-1", "confidence": 0.5},
    ]
    enforce_one_to_one(dets)
    kept = [d for d in dets if d["entity_id"] == "E1"]
    assert len(kept) == 1 and kept[0]["confidence"] == 0.9
    dropped = [d for d in dets if d["entity_id"] is None]
    assert len(dropped) == 1 and dropped[0]["entity_tag"] == "61-HS-00471"  # tag retained
    assert any(d["entity_id"] == "E2" for d in dets)  # untouched
