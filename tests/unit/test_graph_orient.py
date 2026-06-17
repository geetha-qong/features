"""Unit tests for webapp/graph/orient.py — edge flow-direction (graph-directions
spec 2026-06-17).

Covers:
  (a) edge near an arrow → directed=True + correct source→target orientation
      (incl. the swap case when the tracer assigned the opposite direction);
  (b) edge with no arrow nearby → directed=False, unchanged;
  (c) orientation never changes the edge COUNT;
  connector_in/out fallback orientation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.orient import ARROW_PROXIMITY_PX, orient_edges  # noqa: E402
from webapp.graph.resolver import Edge  # noqa: E402


def _node(node_id, bbox):
    return {"node_id": node_id, "bbox": bbox}


def _edge(source, target, polyline):
    return Edge(
        source=source, target=target, polyline=polyline,
        tile="page", method="opencv", confidence=0.8,
    )


# Two nodes on a horizontal run: A at left (10,10), B at right (110,10).
NODES = [
    _node("n_A", [0, 0, 20, 20]),
    _node("n_B", [100, 0, 120, 20]),
]
HORIZONTAL_POLY = [(15, 10), (105, 10)]


def _arrow(label, bbox):
    return {"label": label, "bbox": bbox}


# ── (a) arrow near edge → directed + correct orientation ──────────────────────

def test_arrow_right_keeps_source_to_target():
    # Edge already A→B (left→right). arrow_right (flow →) agrees: no swap.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    arrow = _arrow("arrow_right", [55, 5, 65, 15])  # centroid (60,10) on the line
    out = orient_edges([edge], [arrow], NODES)
    assert len(out) == 1
    oriented, directed = out[0]
    assert directed is True
    assert oriented.source == "n_A"
    assert oriented.target == "n_B"


def test_arrow_left_swaps_source_and_target():
    # Edge is A→B (left→right) but flow arrow points LEFT → must swap to B→A.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    arrow = _arrow("arrow_left", [55, 5, 65, 15])
    out = orient_edges([edge], [arrow], NODES)
    oriented, directed = out[0]
    assert directed is True
    assert oriented.source == "n_B"
    assert oriented.target == "n_A"
    # polyline reversed so polyline[0] stays near the (new) source
    assert oriented.polyline[0] == HORIZONTAL_POLY[-1]
    assert oriented.polyline[-1] == HORIZONTAL_POLY[0]


def test_arrow_down_orients_vertical_edge():
    nodes = [_node("n_T", [0, 0, 20, 20]), _node("n_D", [0, 100, 20, 120])]
    poly = [(10, 15), (10, 105)]  # top→down
    edge = _edge("n_T", "n_D", poly)
    arrow = _arrow("arrow_down", [5, 55, 15, 65])  # centroid (10,60) on the line
    oriented, directed = orient_edges([edge], [arrow], nodes)[0]
    assert directed is True
    assert oriented.source == "n_T"
    assert oriented.target == "n_D"


# ── (b) no arrow → undirected, unchanged ──────────────────────────────────────

def test_no_arrow_leaves_undirected():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    out = orient_edges([edge], [], NODES)
    oriented, directed = out[0]
    assert directed is False
    assert oriented.source == "n_A"
    assert oriented.target == "n_B"
    assert oriented.polyline == HORIZONTAL_POLY


def test_far_arrow_does_not_orient():
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    # Arrow far above the line (well beyond proximity).
    far_y = int(10 + ARROW_PROXIMITY_PX + 50)
    arrow = _arrow("arrow_right", [55, far_y, 65, far_y + 10])
    _oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is False


# ── (c) edge count invariant ──────────────────────────────────────────────────

def test_edge_count_unchanged_with_arrows():
    edges = [
        _edge("n_A", "n_B", HORIZONTAL_POLY),
        _edge("n_A", "n_B", [(15, 12), (105, 12)]),
        _edge("n_A", "n_B", [(15, 8), (105, 8)]),
    ]
    arrow = _arrow("arrow_left", [55, 5, 65, 15])
    out = orient_edges(edges, [arrow], NODES)
    assert len(out) == len(edges)  # never adds/drops


def test_edge_count_unchanged_without_arrows():
    edges = [_edge("n_A", "n_B", HORIZONTAL_POLY) for _ in range(5)]
    out = orient_edges(edges, [], NODES)
    assert len(out) == 5
    assert all(d is False for (_e, d) in out)


# ── connector fallback ────────────────────────────────────────────────────────

def test_connector_in_marks_source_side():
    # No arrow; connector_in sits at the right endpoint (near n_B). connector_in
    # marks the SOURCE side, so flow should be B→A → swap.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    conn = _arrow("connector_in", [100, 5, 110, 15])  # centroid (105,10) == poly end
    oriented, directed = orient_edges([edge], [conn], NODES)[0]
    assert directed is True
    assert oriented.source == "n_B"
    assert oriented.target == "n_A"


def test_connector_out_marks_target_side():
    # connector_out at the right endpoint → that's the target → no swap.
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    conn = _arrow("connector_out", [100, 5, 110, 15])
    oriented, directed = orient_edges([edge], [conn], NODES)[0]
    assert directed is True
    assert oriented.source == "n_A"
    assert oriented.target == "n_B"


def test_arrow_takes_precedence_over_connector():
    # Both present and disagree: arrow_right (no swap) wins over connector_in
    # (which alone would swap).
    edge = _edge("n_A", "n_B", HORIZONTAL_POLY)
    dets = [
        _arrow("arrow_right", [55, 5, 65, 15]),
        _arrow("connector_in", [100, 5, 110, 15]),
    ]
    oriented, directed = orient_edges([edge], dets, NODES)[0]
    assert directed is True
    assert oriented.source == "n_A"
    assert oriented.target == "n_B"


def test_degenerate_polyline_stays_undirected():
    edge = _edge("n_A", "n_B", [(15, 10)])  # single point
    arrow = _arrow("arrow_right", [12, 5, 18, 15])
    oriented, directed = orient_edges([edge], [arrow], NODES)[0]
    assert directed is False
