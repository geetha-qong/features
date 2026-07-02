"""Unit tests for webapp/graph/fallback.py (predecessor spec §8).

A stubbed OpenRouter client merges CV + LLM edges; malformed JSON is safe;
the gate ratio fires correctly. No network, no extractor import (client injected).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import tempfile  # noqa: E402

from webapp.graph.fallback import (  # noqa: E402
    run_fallback,
    should_use_fallback,
    _parse_pairs,
    _select_nodes_in_tile,
)
from webapp.graph.loader import compute_tile_offsets  # noqa: E402
from webapp.graph.resolver import Edge  # noqa: E402


class _StubMessage:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _StubResponse:
    def __init__(self, content):
        self.choices = [_StubMessage(content)]


class _StubClient:
    """Minimal OpenAI-compatible stub: client.chat.completions.create(...)."""

    def __init__(self, content):
        self._content = content
        self.calls = 0

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls += 1
                return _StubResponse(outer._content)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


NODES = [
    {"node_id": "n_001", "tag": "A", "class": "valve_BV", "bbox": [0, 0, 10, 10]},
    {"node_id": "n_002", "tag": "B", "class": "valve_GV", "bbox": [50, 0, 60, 10]},
    {"node_id": "n_003", "tag": "C", "class": "instrument", "bbox": [0, 50, 10, 60]},
]


def test_gate_fires_when_edges_sparse():
    assert should_use_fallback(num_nodes=10, num_edges=2) is True   # 2 < 3
    assert should_use_fallback(num_nodes=10, num_edges=3) is False  # 3 == 3, not <
    assert should_use_fallback(num_nodes=10, num_edges=5) is False
    assert should_use_fallback(num_nodes=0, num_edges=0) is False


def test_parse_pairs_variants():
    assert _parse_pairs('[["n_001","n_002"]]') == [("n_001", "n_002")]
    assert _parse_pairs('```json\n[["n_001","n_002"]]\n```') == [("n_001", "n_002")]
    assert _parse_pairs('[{"source":"n_001","target":"n_003"}]') == [("n_001", "n_003")]
    # malformed
    assert _parse_pairs("not json at all") == []
    assert _parse_pairs("") == []
    assert _parse_pairs("[broken,,,") == []


def test_merges_cv_and_llm_edges():
    existing = [Edge("n_001", "n_002", [(5, 5), (55, 5)], "page", "opencv", 0.7)]
    client = _StubClient('[["n_001","n_003"]]')
    merged, used = run_fallback(NODES, existing, client=client, warnings=[])
    assert used is True
    assert len(merged) == 2
    methods = {e.method for e in merged}
    assert methods == {"opencv", "llm_fallback"}
    new_edge = [e for e in merged if e.method == "llm_fallback"][0]
    assert {new_edge.source, new_edge.target} == {"n_001", "n_003"}
    assert client.calls == 1


def test_skips_duplicate_and_unknown_pairs():
    existing = [Edge("n_001", "n_002", [], "page", "opencv", 0.7)]
    # First pair duplicates existing (unordered); second references unknown node.
    client = _StubClient('[["n_002","n_001"],["n_001","n_999"]]')
    merged, used = run_fallback(NODES, existing, client=client, warnings=[])
    assert used is False
    assert len(merged) == 1  # nothing added


def test_malformed_json_is_safe():
    existing = [Edge("n_001", "n_002", [], "page", "opencv", 0.7)]
    warnings = []
    client = _StubClient("the pipes connect everything, trust me")
    merged, used = run_fallback(NODES, existing, client=client, warnings=warnings)
    assert used is False
    assert merged == existing
    assert any("no usable connections" in w for w in warnings)


# ── Chunked (per-tile) fallback ───────────────────────────────────────────────

def _node(nid, cx, cy):
    return {"node_id": nid, "tag": nid, "class": "valve_bv",
            "bbox": [cx - 5, cy - 5, cx + 5, cy + 5]}


# 300x300 page; centers chosen so top-left and top-right tiles each hold 2 nodes.
NODES_BIG = [
    _node("n_001", 40, 40), _node("n_002", 60, 40),     # top-left tile (r0c0)
    _node("n_003", 250, 40), _node("n_004", 250, 60),   # top-right tile (r0c2)
    _node("n_005", 150, 250),                            # bottom-middle, alone
]


def test_select_nodes_in_tile():
    box = (0, 0, 100, 100)  # top-left region
    picked = {n["node_id"] for n in _select_nodes_in_tile(NODES_BIG, box)}
    assert picked == {"n_001", "n_002"}


def test_parse_pairs_handles_structured_object():
    # Structured-output shape: a top-level object with a connections array.
    assert _parse_pairs('{"connections": [["n_001","n_002"]]}') == [("n_001", "n_002")]
    assert _parse_pairs('{"edges": [{"source":"n_001","target":"n_003"}]}') == [("n_001", "n_003")]


def test_chunked_calls_once_per_qualifying_tile():
    W = H = 300
    boxes = compute_tile_offsets(W, H)
    expected = sum(1 for b in boxes.values() if len(_select_nodes_in_tile(NODES_BIG, b)) >= 2)
    assert expected >= 2  # sanity: our fixture has at least 2 multi-node tiles
    client = _StubClient('{"connections": [["n_001","n_002"]]}')
    with tempfile.TemporaryDirectory() as jd:
        merged, used = run_fallback(
            NODES_BIG, [], job_dir=jd, page_width=W, page_height=H,
            client=client, warnings=[],
        )
    assert client.calls == expected  # one call per tile with >=2 nodes, no others


def test_chunked_dedups_pair_across_tiles():
    W = H = 300
    client = _StubClient('{"connections": [["n_001","n_002"]]}')
    with tempfile.TemporaryDirectory() as jd:
        merged, used = run_fallback(
            NODES_BIG, [], job_dir=jd, page_width=W, page_height=H,
            client=client, warnings=[],
        )
    assert used is True
    llm = [e for e in merged if e.method == "llm_fallback"]
    assert len(llm) == 1  # same pair returned by multiple tiles collapses to one edge


def test_chunked_per_tile_failure_is_nonfatal():
    W = H = 300

    class _FlakyClient:
        def __init__(self):
            self.calls = 0
            outer = self

            class _Completions:
                def create(self, **kwargs):
                    outer.calls += 1
                    if outer.calls == 1:
                        raise RuntimeError("tile 1 down")
                    return _StubResponse('{"connections": [["n_003","n_004"]]}')

            class _Chat:
                completions = _Completions()
            self.chat = _Chat()

    warnings = []
    client = _FlakyClient()
    with tempfile.TemporaryDirectory() as jd:
        merged, used = run_fallback(
            NODES_BIG, [], job_dir=jd, page_width=W, page_height=H,
            client=client, warnings=warnings,
        )
    assert used is True  # surviving tiles still produced an edge
    assert any("n_003" in (e.source + e.target) for e in merged if e.method == "llm_fallback")
    assert any("tile" in w.lower() for w in warnings)


def test_client_exception_is_safe():
    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("network down")

    existing = [Edge("n_001", "n_002", [], "page", "opencv", 0.7)]
    warnings = []
    merged, used = run_fallback(NODES, existing, client=_Boom(), warnings=warnings)
    assert used is False
    assert merged == existing
    assert any("LLM call failed" in w for w in warnings)
