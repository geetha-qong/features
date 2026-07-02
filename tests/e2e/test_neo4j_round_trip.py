"""Integration test: Neo4j graph round-trip.

Requires the live Docker stack (localhost:8000 + Neo4j).
Skip automatically when the server is unreachable.

Test scenario:
  1. GET /graph for a job with Neo4j data → nodes present, auto_edges > 0.
  2. POST /edges → draw one edge.
  3. GET /graph again (simulates page reload) → user_edges == 1, correct shape.
  4. Cleanup: DELETE the edge so the test is repeatable.
"""
from __future__ import annotations

import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

BASE = "http://localhost:8000"
# Job 11 is known to have Neo4j data (canonical_graph.json + Metadata in Neo4j).
TEST_JOB_ID = 11

EXPECTED_USER_EDGE_KEYS = {
    "id", "source", "target", "polyline", "tile", "method", "confidence",
    "directed", "line_type", "status", "source_entity_id", "target_entity_id",
    "group_id",
}


def _make_session() -> requests.Session:
    from webapp.auth import create_access_token
    token = create_access_token({"sub": "admin"})
    s = requests.Session()
    s.cookies.set("access_token", token)
    return s


@pytest.fixture(scope="module")
def live_session():
    """Returns a requests.Session authed as admin against localhost:8000.
    Skips the whole module if the server is unreachable."""
    try:
        requests.get(f"{BASE}/healthz", timeout=2).raise_for_status()
    except Exception:
        pytest.skip("localhost:8000 not reachable — live stack not running")
    return _make_session()


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_graph(session: requests.Session) -> dict:
    r = session.get(f"{BASE}/api/v1/jobs/{TEST_JOB_ID}/graph")
    r.raise_for_status()
    return r.json()


def _draw_edge(session: requests.Session, src_eid: str, tgt_eid: str) -> str:
    r = session.post(
        f"{BASE}/api/v1/jobs/{TEST_JOB_ID}/edges",
        json={
            "line_type": "process_pipe",
            "source_entity_id": src_eid,
            "target_entity_id": tgt_eid,
            "polyline": [[10.0, 20.0], [30.0, 40.0]],
            "directed": True,
        },
    )
    assert r.status_code == 201, f"POST /edges failed: {r.status_code} {r.text}"
    return r.json()["edge_id"]


def _delete_edge(session: requests.Session, edge_id: str) -> None:
    session.delete(f"{BASE}/api/v1/jobs/{TEST_JOB_ID}/edges/{edge_id}")


# ── tests ─────────────────────────────────────────────────────────────────────

def test_graph_loads_with_nodes_and_auto_edges(live_session):
    """GET /graph returns nodes and auto edges (Neo4j or fallback, both valid)."""
    g = _get_graph(live_session)
    stats = g["stats"]
    assert stats["nodes"] > 0, "expected nodes in graph"
    assert stats["auto_edges"] > 0, "expected auto edges in graph"
    assert len(g["nodes"]) == stats["nodes"]
    # Node shape
    n = g["nodes"][0]
    for key in ("id", "class", "bbox", "tile", "confidence"):
        assert key in n, f"node missing key '{key}'"


def test_draw_edge_and_reload(live_session):
    """Draw one user edge; a second GET returns it with the correct shape."""
    # Prerequisite: need two nodes with entity_ids.
    g = _get_graph(live_session)
    nodes_with_eid = [n for n in g["nodes"] if n.get("entity_id")]
    assert len(nodes_with_eid) >= 2, "need at least 2 nodes with entity_id to draw an edge"

    n1, n2 = nodes_with_eid[0], nodes_with_eid[1]
    edge_id = _draw_edge(live_session, n1["entity_id"], n2["entity_id"])

    try:
        # Simulates a page reload — fresh GET
        g2 = _get_graph(live_session)
        stats2 = g2["stats"]

        user_edges = [e for e in g2["edges"] if e.get("method") == "user_added"]
        # At least our new edge must be present (there may be others from prior runs).
        our_edges = [e for e in user_edges if e["id"] == edge_id]
        assert our_edges, f"edge {edge_id} not found in GET /graph after draw"

        u = our_edges[0]
        missing = EXPECTED_USER_EDGE_KEYS - set(u.keys())
        extra   = set(u.keys()) - EXPECTED_USER_EDGE_KEYS
        assert not missing, f"user edge missing keys: {missing}"
        assert not extra,   f"user edge has unexpected keys: {extra}"

        assert u["method"] == "user_added"
        assert u["status"] == "user_added"
        assert u["source_entity_id"] == n1["entity_id"]
        assert u["target_entity_id"] == n2["entity_id"]
        assert u["directed"] is True
        assert u["line_type"] == "process_pipe"
        assert isinstance(u["polyline"], list) and len(u["polyline"]) == 2

        assert stats2["user_edges"] >= 1

    finally:
        _delete_edge(live_session, edge_id)
