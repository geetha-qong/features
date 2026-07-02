"""Unit tests for webapp/graph/resolver.py (predecessor spec §8).

2 bboxes + 1 line → 1 edge; too-far line → orphan; 3 bboxes + 1 line → the
correct pair is connected.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.resolver import resolve_edges, split_edges_at_intermediates, Edge  # noqa: E402
from webapp.graph.tracer import LineSegment  # noqa: E402


def _node(node_id, bbox):
    return {"node_id": node_id, "bbox": bbox}


def test_two_bboxes_one_line_makes_one_edge():
    nodes = [
        _node("n_001", [0, 0, 20, 20]),       # center (10,10)
        _node("n_002", [100, 0, 120, 20]),    # center (110,10)
    ]
    # Line from near node 1 to near node 2.
    seg = LineSegment(polyline=[(15, 10), (105, 10)], tile="page", confidence=0.8)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 1
    assert len(result.orphan_lines) == 0
    edge = result.edges[0]
    assert {edge.source, edge.target} == {"n_001", "n_002"}
    assert edge.method == "opencv"
    assert edge.polyline == [(15, 10), (105, 10)]


def test_too_far_line_becomes_orphan():
    nodes = [_node("n_001", [0, 0, 20, 20])]
    # Both endpoints far from any node.
    seg = LineSegment(polyline=[(500, 500), (600, 600)], tile="page", confidence=0.5)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 0
    assert len(result.orphan_lines) == 1
    assert result.orphan_lines[0].reason == "no_bbox_within_proximity"


def test_one_endpoint_unmatched_is_orphan():
    nodes = [_node("n_001", [0, 0, 20, 20])]
    seg = LineSegment(polyline=[(15, 10), (600, 600)], tile="page", confidence=0.5)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 0
    assert len(result.orphan_lines) == 1
    assert result.orphan_lines[0].reason == "one_endpoint_unmatched"


def test_three_bboxes_one_line_picks_correct_pair():
    nodes = [
        _node("n_001", [0, 0, 20, 20]),       # center (10,10)
        _node("n_002", [100, 0, 120, 20]),    # center (110,10)
        _node("n_003", [0, 200, 20, 220]),    # center (10,210) — far from the line
    ]
    seg = LineSegment(polyline=[(15, 10), (105, 10)], tile="page", confidence=0.9)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert {edge.source, edge.target} == {"n_001", "n_002"}
    assert "n_003" not in {edge.source, edge.target}


# ── split_edges_at_intermediates tests ───────────────────────────────────────

def _edge(src, tgt, polyline):
    return Edge(source=src, target=tgt, polyline=polyline, tile="page", method="opencv", confidence=0.8)


def test_no_intermediates_unchanged():
    # A→C with no node between them — edge passes through unchanged.
    nodes = [
        _node("A", [0, 0, 20, 20]),
        _node("C", [200, 0, 220, 20]),
    ]
    edge = _edge("A", "C", [(10, 10), (210, 10)])
    result = split_edges_at_intermediates([edge], nodes)
    assert len(result) == 1
    assert result[0].source == "A"
    assert result[0].target == "C"


def test_one_intermediate_splits_into_two():
    # A ——pipe——> B ——pipe——> C
    # polyline: (10,10) → (110,10) → (210,10)
    # B bbox centered at (110,10)
    nodes = [
        _node("A", [0, 0, 20, 20]),
        _node("B", [100, 0, 120, 20]),
        _node("C", [200, 0, 220, 20]),
    ]
    edge = _edge("A", "C", [(10, 10), (110, 10), (210, 10)])
    result = split_edges_at_intermediates([edge], nodes, proximity_px=20)
    assert len(result) == 2
    srcs = [e.source for e in result]
    tgts = [e.target for e in result]
    assert srcs == ["A", "B"]
    assert tgts == ["B", "C"]


def test_two_intermediates_split_into_three():
    # A → B → C → D along y=10
    nodes = [
        _node("A", [0, 0, 20, 20]),
        _node("B", [80, 0, 100, 20]),
        _node("C", [160, 0, 180, 20]),
        _node("D", [240, 0, 260, 20]),
    ]
    poly = [(10, 10), (90, 10), (170, 10), (250, 10)]
    edge = _edge("A", "D", poly)
    result = split_edges_at_intermediates([edge], nodes, proximity_px=20)
    assert len(result) == 3
    assert [e.source for e in result] == ["A", "B", "C"]
    assert [e.target for e in result] == ["B", "C", "D"]


def test_sub_edge_inherits_tile_method_confidence():
    nodes = [
        _node("A", [0, 0, 20, 20]),
        _node("B", [100, 0, 120, 20]),
        _node("C", [200, 0, 220, 20]),
    ]
    edge = Edge(source="A", target="C", polyline=[(10, 10), (110, 10), (210, 10)],
                tile="tile_0_0", method="topology", confidence=0.9)
    result = split_edges_at_intermediates([edge], nodes, proximity_px=20)
    assert len(result) == 2
    for sub in result:
        assert sub.tile == "tile_0_0"
        assert sub.method == "topology"
        assert sub.confidence == 0.9


def test_node_outside_proximity_not_intermediate():
    # B is 50px from the polyline — beyond the 20px threshold.
    nodes = [
        _node("A", [0, 0, 20, 20]),
        _node("B", [100, 60, 120, 80]),  # 50px below the line at y=10
        _node("C", [200, 0, 220, 20]),
    ]
    edge = _edge("A", "C", [(10, 10), (110, 10), (210, 10)])
    result = split_edges_at_intermediates([edge], nodes, proximity_px=20)
    assert len(result) == 1  # no split


def test_self_loop_discarded():
    nodes = [_node("n_001", [0, 0, 100, 100])]
    # Both endpoints land inside the same node bbox.
    seg = LineSegment(polyline=[(10, 10), (90, 90)], tile="page", confidence=0.5)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 0
    assert len(result.orphan_lines) == 1
    assert result.orphan_lines[0].reason == "self_loop"
