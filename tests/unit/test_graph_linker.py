"""Unit tests for webapp/graph/linker.py (predecessor spec §8).

OCR is monkeypatched so tests are hermetic (no onnxruntime model load).
Covers: exact match, 8-vs-B weak match, class-prior fallback when OCR empty.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph import linker  # noqa: E402
from webapp.graph.linker import (  # noqa: E402
    CLASS_FALLBACK,
    MATCH,
    NONE,
    WEAK_MATCH,
    crop_bbox,
    link_to_canonical,
    yolo_class_to_canonical,
)


CANONICAL = [
    {"entity_id": "ent_a", "entity_class": "valve", "sub_class": "BV", "tag": "63-BV-00822"},
    {"entity_id": "ent_b", "entity_class": "valve", "sub_class": "GV", "tag": "63-GV-00100"},
    {"entity_id": "ent_c", "entity_class": "instrument", "sub_class": None, "tag": "FT-201"},
]


def test_class_mapping_port():
    assert yolo_class_to_canonical("valve_bv") == ("valve", "BV")
    assert yolo_class_to_canonical("inst_flow") == ("instrument", None)
    assert yolo_class_to_canonical("Pump/Dwg Pump") == ("equipment", None)
    assert yolo_class_to_canonical("Pump_Dwg_Pump") == ("equipment", None)
    assert yolo_class_to_canonical("arrow_up") == (None, None)
    assert yolo_class_to_canonical(None) == (None, None)


def test_crop_bbox_clamps_and_handles_degenerate():
    img = np.zeros((100, 200), dtype=np.uint8)
    crop = crop_bbox(img, [10, 10, 50, 40])
    assert crop.shape == (30, 40)
    # out of bounds clamps
    crop2 = crop_bbox(img, [-20, -20, 30, 30])
    assert crop2.shape == (30, 30)
    # degenerate → empty
    assert crop_bbox(img, [50, 50, 50, 50]).size == 0


def test_exact_match():
    eid, tag, quality = link_to_canonical("63-BV-00822", CANONICAL)
    assert eid == "ent_a"
    assert tag == "63-BV-00822"
    assert quality == MATCH


def test_8_vs_B_weak_match():
    # OCR confuses '8' for 'B' and drops a char → Levenshtein distance ~2-3.
    # "63-8V-0082" vs "63-BV-00822": substitution(8→B) + insertion(2) = dist 2.
    eid, tag, quality = link_to_canonical("63-8V-0082", CANONICAL)
    assert eid == "ent_a"
    assert quality in (MATCH, WEAK_MATCH)


def test_far_string_no_match():
    eid, tag, quality = link_to_canonical("ZZZZZZZZZZ", CANONICAL)
    assert eid is None
    assert quality == NONE


def test_empty_ocr_no_match():
    assert link_to_canonical("", CANONICAL) == (None, None, NONE)


def test_class_fallback_when_ocr_empty(monkeypatch):
    # OCR returns nothing → class prior should grab the matching valve_BV entity.
    monkeypatch.setattr(linker, "ocr_crop", lambda crop: "")
    img = np.zeros((100, 200), dtype=np.uint8)
    det = {"bbox": [10, 10, 40, 40], "label": "valve_BV"}
    consumed: set = set()
    eid, tag, quality = linker.link_detection(img, det, CANONICAL, consumed)
    assert eid == "ent_a"
    assert quality == CLASS_FALLBACK
    assert "ent_a" in consumed


def test_class_fallback_two_same_class_distinct_entities(monkeypatch):
    monkeypatch.setattr(linker, "ocr_crop", lambda crop: "")
    img = np.zeros((100, 200), dtype=np.uint8)
    consumed: set = set()
    # Two valve detections of unspecified sub → should consume two distinct valves.
    canon = [
        {"entity_id": "ent_1", "entity_class": "valve", "sub_class": "BV", "tag": "T1"},
        {"entity_id": "ent_2", "entity_class": "valve", "sub_class": "BV", "tag": "T2"},
    ]
    d1 = {"bbox": [0, 0, 10, 10], "label": "valve_BV"}
    d2 = {"bbox": [20, 20, 30, 30], "label": "valve_BV"}
    e1, _, _ = linker.link_detection(img, d1, canon, consumed)
    e2, _, _ = linker.link_detection(img, d2, canon, consumed)
    assert {e1, e2} == {"ent_1", "ent_2"}


def test_ocr_match_takes_priority_over_class(monkeypatch):
    monkeypatch.setattr(linker, "ocr_crop", lambda crop: "FT-201")
    img = np.zeros((100, 200), dtype=np.uint8)
    det = {"bbox": [10, 10, 40, 40], "label": "inst_flow"}
    consumed: set = set()
    eid, tag, quality = linker.link_detection(img, det, CANONICAL, consumed)
    assert eid == "ent_c"
    assert quality == MATCH
