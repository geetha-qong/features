"""GET /jobs/{id}/graph must reflect user tag edits (entity_overrides) on the
graph nodes — the graph file holds the original OCR tag, so without merging the
override the graph view reverts edited tags on refresh (real bug, job 38)."""
from webapp.routers.graph import _merge_tag_overrides


def test_merge_overlays_tag_by_entity_id():
    nodes = [
        {"id": "n_1", "entity_id": "e1", "tag": "OLD-1"},
        {"id": "n_2", "entity_id": "e2", "tag": "OLD-2"},
        {"id": "n_3", "entity_id": None, "tag": "TYPE-B"},  # type-B, untouched
    ]
    _merge_tag_overrides(nodes, {"e1": "61-PZIT-149111"})
    assert nodes[0]["tag"] == "61-PZIT-149111"   # override applied
    assert nodes[1]["tag"] == "OLD-2"            # no override → unchanged
    assert nodes[2]["tag"] == "TYPE-B"           # no entity_id → unchanged


def test_merge_noop_when_no_overrides():
    nodes = [{"id": "n_1", "entity_id": "e1", "tag": "OLD"}]
    _merge_tag_overrides(nodes, {})
    assert nodes[0]["tag"] == "OLD"


def test_merge_ignores_override_for_absent_entity():
    nodes = [{"id": "n_1", "entity_id": "e1", "tag": "OLD"}]
    _merge_tag_overrides(nodes, {"e_missing": "NEW"})
    assert nodes[0]["tag"] == "OLD"


def test_merge_handles_node_without_entity_id_key():
    nodes = [{"id": "n_1", "tag": "OLD"}]  # no entity_id key at all
    _merge_tag_overrides(nodes, {"e1": "NEW"})
    assert nodes[0]["tag"] == "OLD"
