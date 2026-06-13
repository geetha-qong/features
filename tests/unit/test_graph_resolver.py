"""Unit tests for webapp/graph/resolver.py (predecessor spec §8).

2 bboxes + 1 line → 1 edge; too-far line → orphan; 3 bboxes + 1 line → the
correct pair is connected.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.resolver import resolve_edges  # noqa: E402
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


def test_self_loop_discarded():
    nodes = [_node("n_001", [0, 0, 100, 100])]
    # Both endpoints land inside the same node bbox.
    seg = LineSegment(polyline=[(10, 10), (90, 90)], tile="page", confidence=0.5)
    result = resolve_edges([seg], nodes, proximity_px=30)
    assert len(result.edges) == 0
    assert len(result.orphan_lines) == 1
    assert result.orphan_lines[0].reason == "self_loop"
