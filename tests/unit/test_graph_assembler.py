"""Unit tests for webapp/graph/assembler.py (predecessor spec §8).

Round-trip identity (to_json → from_json); 2 nodes + 1 edge produce the correct
spec §3 shape with correct attrs; floating nodes detected.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.assembler import (  # noqa: E402
    GRAPH_VERSION,
    assemble,
    build_multigraph,
    from_json,
    to_json,
)
from webapp.graph.resolver import Edge, OrphanLine  # noqa: E402


GEN_AT = "2026-06-13T00:00:00Z"


def _nodes():
    return [
        {"node_id": "n_001", "entity_id": "ent_a", "tag": "63-BV-1", "class": "valve_BV",
         "bbox": [0, 0, 20, 20], "tile": "tile_p0_r0_c0.png", "confidence": 0.9},
        {"node_id": "n_002", "entity_id": "ent_b", "tag": "63-GV-2", "class": "valve_GV",
         "bbox": [100, 0, 120, 20], "tile": "tile_p0_r0_c1.png", "confidence": 0.8},
    ]


def _edges():
    return [
        Edge(source="n_001", target="n_002", polyline=[(15, 10), (105, 10)],
             tile="page", method="opencv", confidence=0.72),
    ]


def test_assemble_shape_and_attrs():
    graph = assemble(_nodes(), _edges(), [], job_id=42, page=1, generated_at=GEN_AT)
    assert graph["version"] == GRAPH_VERSION
    assert graph["job_id"] == 42
    assert graph["page"] == 1
    assert graph["generated_at"] == GEN_AT
    assert graph["stats"] == {"nodes": 2, "edges": 1, "fallback_used": False}
    # Spec §3 node keys
    n0 = graph["nodes"][0]
    assert set(n0.keys()) == {"id", "entity_id", "tag", "class", "bbox", "tile", "confidence"}
    assert n0["id"] == "n_001"
    # Spec §3 edge keys
    e0 = graph["edges"][0]
    assert set(e0.keys()) == {"id", "source", "target", "polyline", "tile", "method", "confidence"}
    assert e0["id"] == "e_000"
    assert e0["source"] == "n_001"
    assert e0["target"] == "n_002"
    assert e0["method"] == "opencv"
    assert e0["polyline"] == [[15, 10], [105, 10]]
    # No floating nodes (both connected)
    assert graph["floating_nodes"] == []
    assert graph["orphan_lines"] == []


def test_floating_nodes_detected():
    nodes = _nodes() + [
        {"node_id": "n_003", "entity_id": None, "tag": None, "class": "valve_BV",
         "bbox": [200, 200, 220, 220], "tile": None, "confidence": 0.5},
    ]
    graph = assemble(nodes, _edges(), [], job_id=1, page=1, generated_at=GEN_AT)
    assert graph["floating_nodes"] == ["n_003"]
    assert graph["stats"]["nodes"] == 3


def test_orphan_lines_serialized():
    orphans = [OrphanLine(polyline=[(700, 100), (700, 200)], tile="page", reason="no_bbox_within_proximity")]
    graph = assemble(_nodes(), _edges(), orphans, job_id=1, page=1, generated_at=GEN_AT)
    assert graph["orphan_lines"] == [
        {"polyline": [[700, 100], [700, 200]], "tile": "page", "reason": "no_bbox_within_proximity"}
    ]


def test_round_trip_identity():
    graph = assemble(_nodes(), _edges(), [], job_id=42, page=1, generated_at=GEN_AT)
    restored = from_json(to_json(graph))
    assert restored == graph
    # And serialise again — byte-stable.
    assert to_json(restored) == to_json(graph)


def test_build_multigraph_structure():
    g = build_multigraph(_nodes(), _edges())
    import networkx as nx
    assert isinstance(g, nx.MultiGraph)
    assert g.number_of_nodes() == 2
    assert g.number_of_edges() == 1
    assert g.nodes["n_001"]["tag"] == "63-BV-1"
    assert g.has_edge("n_001", "n_002")
    # MultiGraph allows parallel edges between the same pair.
    g2 = build_multigraph(
        _nodes(),
        _edges() + [Edge("n_001", "n_002", [(1, 1)], "page", "llm_fallback", 0.5)],
    )
    assert g2.number_of_edges() == 2
