"""Neo4j is opt-in (FEATURES #118/#119). When NEO4J_PASSWORD is unset, the
graph/agent-memory code must skip Neo4j WITHOUT creating a driver — otherwise
resolving the absent host is slow (~30s) and slows every page.
"""
import time

from webapp.graph import agent_memory as am
from webapp.graph import neo4j_writer as nw


def test_neo4j_disabled_when_password_unset(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    assert nw._neo4j_enabled() is False
    assert am._neo4j_enabled() is False


def test_neo4j_enabled_when_password_set(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    assert nw._neo4j_enabled() is True
    assert am._neo4j_enabled() is True


def test_read_graph_returns_none_instantly_when_disabled(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    t0 = time.time()
    result = nw.read_graph_from_neo4j(55, {"nodes": [], "edges": []})
    elapsed = time.time() - t0
    assert result is None
    # No driver / no DNS attempt → must be effectively instant (well under the
    # ~30s DNS-failure that caused the slowdown).
    assert elapsed < 0.1, f"expected instant skip, took {elapsed:.3f}s"


def test_write_paths_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    # None of these should raise or block when Neo4j is disabled.
    assert nw.write_graph_to_neo4j({"job_id": 55}) is None
    assert nw.write_user_edge_to_neo4j(55, "e1", "a", "b", "pipe", [], False) is None
    assert nw.delete_user_edge_from_neo4j(55, "e1") is None


def test_agent_memory_init_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    # Should log + return without raising (and without a slow driver attempt).
    t0 = time.time()
    am.initialize_schema()
    assert time.time() - t0 < 0.1


def test_get_driver_raises_fast_when_disabled(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    import pytest
    with pytest.raises(RuntimeError):
        am._get_driver()
