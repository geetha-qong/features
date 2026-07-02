"""Unit tests for node-level dedup by entity_id (graph pipeline).

Tile overlap makes the same physical instrument get detected several times, so
the linker produces multiple nodes with the same entity_id (job 43: 79 redundant
of 207). Collapsing them to one representative per entity gives a topologically
correct graph (one node per component) and stops edges wiring a valve to its own
duplicate boxes. Untagged nodes (no entity_id) are kept — can't group them.
"""
from webapp.graph.pipeline import dedupe_nodes_by_entity


def _n(node_id, entity_id, conf, bbox=(0, 0, 10, 10), tag="t"):
    return {"node_id": node_id, "entity_id": entity_id, "confidence": conf,
            "bbox": list(bbox), "tag": tag, "class": "valve_bv"}


def test_collapses_same_entity_to_highest_confidence():
    nodes = [
        _n("n_000", "E1", 0.6),
        _n("n_001", "E1", 0.9),  # winner (highest conf)
        _n("n_002", "E1", 0.7),
    ]
    out = dedupe_nodes_by_entity(nodes)
    assert len(out) == 1
    assert out[0]["node_id"] == "n_001"


def test_keeps_untagged_nodes_individually():
    nodes = [
        _n("n_000", None, 0.5),
        _n("n_001", None, 0.5),
        _n("n_002", "E1", 0.8),
        _n("n_003", "E1", 0.9),
    ]
    out = dedupe_nodes_by_entity(nodes)
    ids = [n["node_id"] for n in out]
    # both untagged kept; the E1 pair collapses to the 0.9 one
    assert "n_000" in ids and "n_001" in ids
    assert "n_003" in ids and "n_002" not in ids
    assert len(out) == 3


def test_tie_on_confidence_breaks_on_largest_bbox():
    nodes = [
        _n("n_000", "E1", 0.8, bbox=(0, 0, 10, 10)),    # area 100
        _n("n_001", "E1", 0.8, bbox=(0, 0, 30, 30)),    # area 900 → winner
    ]
    out = dedupe_nodes_by_entity(nodes)
    assert len(out) == 1
    assert out[0]["node_id"] == "n_001"


def test_no_entity_ids_returns_all_in_order():
    nodes = [_n("n_000", None, 0.5), _n("n_001", None, 0.4)]
    out = dedupe_nodes_by_entity(nodes)
    assert [n["node_id"] for n in out] == ["n_000", "n_001"]


def test_preserves_first_appearance_order():
    nodes = [
        _n("n_000", "E1", 0.9),
        _n("n_001", None, 0.5),
        _n("n_002", "E2", 0.9),
        _n("n_003", "E1", 0.4),  # collapses into n_000's slot (already emitted)
    ]
    out = dedupe_nodes_by_entity(nodes)
    assert [n["node_id"] for n in out] == ["n_000", "n_001", "n_002"]
