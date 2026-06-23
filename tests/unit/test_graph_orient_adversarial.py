"""Adversarial / edge-case coverage for webapp/graph/orient.py.

The happy-path orient tests live in test_graph_orient.py. These hammer the
robustness contract the spec implies ("best-effort, never crashes, edge count
invariant"):

  - two arrows near one edge → the NEAREST wins;
  - arrow exactly at the proximity boundary (inclusive ``<=``);
  - arrow with a malformed / short bbox → ignored, no crash;
  - polyline with 1 point / duplicate (zero-length) points → undirected, no crash;
  - two equidistant arrows that DISAGREE → deterministic, no crash;
  - connector with a malformed bbox → ignored;
  - empty inputs.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.orient import ARROW_PROXIMITY_PX, orient_edges, split_direction_detections  # noqa: E402
from webapp.graph.resolver import Edge  # noqa: E402


def _node(node_id, bbox):
    return {"node_id": node_id, "bbox": bbox}


def _edge(source, target, polyline):
    return Edge(source=source, target=target, polyline=polyline,
                tile="page", method="opencv", confidence=0.8)


def _arrow(label, bbox):
    return {"label": label, "bbox": bbox}


NODES = [_node("n_A", [0, 0, 20, 20]), _node("n_B", [100, 0, 120, 20])]
HORIZONTAL_POLY = [(15, 10), (105, 10)]  # A(left) → B(right)


# ── two arrows near one edge → nearest wins ───────────────────────────────────

def test_two_arrows_nearest_wins():
    # arrow_left is FAR (15px off the line); arrow_right is ON the line (0px).
    # The nearest (arrow_right) must decide → no swap, A→B.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    near_right = _arrow("arrow_right", [55, 5, 65, 15])    # centroid (60,10) dist 0
    far_left = _arrow("arrow_left", [55, 20, 65, 30])      # centroid (60,25) dist 15
    oriented, directed = orient_edges([edge], [near_right, far_left], NODES)[0]
    assert directed is True
    assert oriented.source == "n_A" and oriented.target == "n_B"

    # Reverse the proximity: now arrow_left is nearer → must swap to B→A.
    near_left = _arrow("arrow_left", [55, 5, 65, 15])      # dist 0
    far_right = _arrow("arrow_right", [55, 20, 65, 30])    # dist 15
    oriented2, directed2 = orient_edges([_edge("n_A", "n_B", HORIZONTAL_POLY)],
                                        [near_left, far_right], NODES)[0]
    assert directed2 is True
    assert oriented2.source == "n_B" and oriented2.target == "n_A"


# ── threshold boundary: <= is inclusive ───────────────────────────────────────

def test_arrow_exactly_at_threshold_is_included():
    # Arrow centroid exactly ARROW_PROXIMITY_PX below the line → dist == threshold.
    line_y = 10
    cy = line_y + ARROW_PROXIMITY_PX  # exactly on the boundary
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    arrow = _arrow("arrow_right", [58, cy - 2, 62, cy + 2])  # centroid x=60, y=cy
    _oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is True  # boundary is inclusive (dist <= proximity_px)


def test_arrow_just_past_threshold_is_excluded():
    line_y = 10
    cy = line_y + ARROW_PROXIMITY_PX + 0.5  # just past
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    arrow = _arrow("arrow_right", [58, cy - 2, 62, cy + 2])
    _oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is False


# ── malformed / short bboxes are ignored, not crashing ────────────────────────

def test_arrow_with_short_bbox_ignored():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    bad = _arrow("arrow_right", [55, 5, 65])  # 3 coords, not 4
    _oriented, directed = orient_edges([edge], [bad], NODES)[0]
    assert directed is False  # dropped by split_direction_detections


def test_arrow_with_no_bbox_ignored():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    bad = {"label": "arrow_right"}  # no bbox key at all
    _oriented, directed = orient_edges([edge], [bad], NODES)[0]
    assert directed is False


def test_split_drops_malformed_keeps_valid():
    dets = [
        _arrow("arrow_right", [55, 5, 65, 15]),       # valid
        _arrow("arrow_left", [1, 2]),                 # short bbox → dropped
        {"label": "connector_in", "bbox": [0, 0, 10, 10]},  # valid connector
        {"label": "valve_BV", "bbox": [0, 0, 10, 10]},      # not a direction class
        {"bbox": [0, 0, 10, 10]},                     # no label → dropped
    ]
    arrows, connectors = split_direction_detections(dets)
    assert len(arrows) == 1
    assert len(connectors) == 1


# ── degenerate polylines: 1 point / duplicate points → undirected, no crash ──

def test_single_point_polyline_undirected():
    edge = _edge("n_A", "n_B", [(15, 10)])
    arrow = _arrow("arrow_right", [12, 8, 18, 12])
    _oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is False


def test_duplicate_point_polyline_zero_vector_undirected():
    # Two identical points → zero edge vector → cannot determine flow agreement.
    edge = _edge("n_A", "n_B", [(50, 10), (50, 10)])
    arrow = _arrow("arrow_right", [48, 8, 52, 12])
    _oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is False


def test_empty_polyline_undirected_no_crash():
    edge = _edge("n_A", "n_B", [])
    _oriented, directed = orient_edges([edge], [_arrow("arrow_right", [10, 8, 14, 12])], NODES)[0]
    assert directed is False


# ── equidistant disagreeing arrows: deterministic, no crash ──────────────────

def test_equidistant_disagreeing_arrows_deterministic():
    # Two arrows symmetric about the line, same distance, opposite directions.
    # Result must be deterministic (first-seen wins on ties: code uses
    # strict `<` so it does NOT replace on equal distance) and must not crash.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    up = _arrow("arrow_right", [55, -5, 65, 5])    # centroid (60,0), dist 10
    down = _arrow("arrow_left", [55, 15, 65, 25])  # centroid (60,20), dist 10
    out1 = orient_edges([_edge("n_A", "n_B", HORIZONTAL_POLY)], [up, down], NODES)[0]
    out2 = orient_edges([_edge("n_A", "n_B", HORIZONTAL_POLY)], [up, down], NODES)[0]
    # Deterministic across runs.
    assert out1[0].source == out2[0].source
    assert out1[1] is True and out2[1] is True
    # First-seen (up = arrow_right) wins the tie → no swap, A→B.
    assert out1[0].source == "n_A" and out1[0].target == "n_B"


# ── connector robustness ──────────────────────────────────────────────────────

def test_connector_with_malformed_bbox_ignored():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    conn = {"label": "connector_in", "bbox": [100, 5]}  # short → dropped at split
    _oriented, directed = orient_edges([edge], [conn], NODES)[0]
    assert directed is False


def test_connector_far_from_both_endpoints_undirected():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    # Connector centred mid-span, far from BOTH endpoints (> proximity).
    conn = _arrow("connector_in", [55, 5, 65, 15])  # centroid (60,10): dist to ends ~45
    _oriented, directed = orient_edges([edge], [conn], NODES)[0]
    assert directed is False


# ── empty / no inputs ─────────────────────────────────────────────────────────

def test_no_edges_returns_empty():
    assert orient_edges([], [_arrow("arrow_right", [1, 1, 2, 2])], NODES) == []


def test_no_detections_all_undirected():
    edges = [_edge("n_A", "n_B", HORIZONTAL_POLY) for _ in range(3)]
    out = orient_edges(edges, [], NODES)
    assert len(out) == 3
    assert all(d is False for (_e, d) in out)
