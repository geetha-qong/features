"""Unit tests for webapp/graph/fallback.py (predecessor spec §8).

A stubbed OpenRouter client merges CV + LLM edges; malformed JSON is safe;
the gate ratio fires correctly. No network, no extractor import (client injected).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.fallback import (  # noqa: E402
    run_fallback,
    should_use_fallback,
    _parse_pairs,
)
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
