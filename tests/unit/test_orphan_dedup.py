import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.orphan_dedup import bbox_iou, superseded_auto_ids


def test_bbox_iou_identical_is_one():
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0


def test_bbox_iou_disjoint_is_zero():
    assert bbox_iou([0, 0, 10, 10], [100, 100, 110, 110]) == 0.0


def test_orphan_superseded_by_overlapping_annotation():
    auto = [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [1, 1, 11, 11]}]  # high overlap
    assert superseded_auto_ids(auto, anns) == {"n_1"}


def test_auto_node_with_entity_id_never_superseded():
    auto = [{"id": "n_1", "entity_id": "e-keep", "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [0, 0, 10, 10]}]
    assert superseded_auto_ids(auto, anns) == set()


def test_low_overlap_not_superseded():
    auto = [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [8, 8, 18, 18]}]  # small overlap
    assert superseded_auto_ids(auto, anns) == set()
