"""API round-trip for the `directed` flag across BOTH routers
(graph-directions spec 2026-06-17).

test_edges_api.py covers POST/PATCH `directed` on /edges in isolation;
test_graph_router_and_sync.py covers a hand-seeded GraphCorrection row in the
/graph merge. This file closes the gap between them: it mounts the edges *and*
graph routers on one app sharing one DB, then drives the real user workflow —
POST an edge via /edges, GET it back via /graph, and assert the `directed` flag
survives the create→merge path with the correct value per edge.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models  # noqa: E402
from webapp.auth import get_current_user  # noqa: E402
from webapp.database import Base, get_db  # noqa: E402
from webapp.routers.edges import router as edges_router  # noqa: E402
from webapp.routers.graph import router as graph_router  # noqa: E402


def _canonical_graph(job_id, edges):
    return {
        "version": "0.1", "job_id": job_id, "page": 1,
        "generated_at": "2026-06-17T00:00:00Z",
        "stats": {"nodes": 2, "edges": len(edges), "fallback_used": False},
        "nodes": [
            {"id": "n_000", "entity_id": "ent-A", "tag": "BV-1", "class": "valve_bv",
             "bbox": [10, 10, 30, 30], "tile": "t.png", "confidence": 0.9},
            {"id": "n_001", "entity_id": "ent-B", "tag": "FT-1", "class": "instrument",
             "bbox": [100, 100, 130, 130], "tile": "t.png", "confidence": 0.8},
        ],
        "edges": edges, "floating_nodes": [], "orphan_lines": [],
    }


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(username="u", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user, tmp_path):
    csv = tmp_path / "valve_list.csv"
    csv.write_text("x")
    j = models.Job(user_id=user.id, original_filename="t.pdf", stored_filename="t.pdf",
                   pid_no="T-1", status="done", output_csv_path=str(csv))
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


@pytest.fixture()
def client(db_session, user):
    app = FastAPI()
    app.include_router(edges_router)
    app.include_router(graph_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _payload(**over):
    p = {
        "line_type": "process_pipe",
        "source_entity_id": "ent-A",
        "target_entity_id": "ent-B",
        "polyline": [[10.0, 20.0], [110.0, 20.0]],
        "sheet_number": 1,
    }
    p.update(over)
    return p


def _write_graph(job, edges):
    job_dir = os.path.dirname(job.output_csv_path)
    with open(os.path.join(job_dir, "canonical_graph.json"), "w") as f:
        json.dump(_canonical_graph(job.id, edges), f)


# ── POST (directed omitted → default true) then GET /graph ────────────────────

def test_post_default_directed_surfaces_true_in_graph(client, job):
    _write_graph(job, [])  # no auto edges; just the user edge
    create = client.post(f"/api/v1/jobs/{job.id}/edges", json=_payload())
    assert create.status_code == 201, create.text
    edge_id = create.json()["edge_id"]

    g = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert g.status_code == 200, g.text
    edges = g.json()["edges"]
    mine = [e for e in edges if e["id"] == edge_id]
    assert len(mine) == 1
    assert mine[0]["directed"] is True
    assert mine[0]["method"] == "user_added"


# ── POST directed=false → surfaces false in /graph ────────────────────────────

def test_post_directed_false_surfaces_false_in_graph(client, job):
    _write_graph(job, [])
    edge_id = client.post(
        f"/api/v1/jobs/{job.id}/edges", json=_payload(directed=False)
    ).json()["edge_id"]
    edges = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    mine = [e for e in edges if e["id"] == edge_id][0]
    assert mine["directed"] is False


# ── PATCH flips direction, /graph reflects the flip ───────────────────────────

def test_patch_flip_reflected_in_graph(client, job):
    _write_graph(job, [])
    edge_id = client.post(f"/api/v1/jobs/{job.id}/edges", json=_payload()).json()["edge_id"]
    # Starts True.
    g0 = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    assert [e for e in g0 if e["id"] == edge_id][0]["directed"] is True
    # Flip to False via PATCH.
    patch = client.patch(f"/api/v1/jobs/{job.id}/edges/{edge_id}", json={"directed": False})
    assert patch.status_code == 200, patch.text
    g1 = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    assert [e for e in g1 if e["id"] == edge_id][0]["directed"] is False
    # And flip back to True.
    client.patch(f"/api/v1/jobs/{job.id}/edges/{edge_id}", json={"directed": True})
    g2 = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    assert [e for e in g2 if e["id"] == edge_id][0]["directed"] is True


# ── legacy DB row (directed column NULL) surfaces in /graph as True ───────────
# Per edges.py/_row_to_response + graph.py/_user_edge_to_dict: a NULL `directed`
# (a row created before the migration added the column) reads as True because
# user edges were ALWAYS directed.

def test_legacy_null_directed_user_row_surfaces_true(client, db_session, job):
    _write_graph(job, [])
    db_session.add(models.GraphCorrection(
        job_id=job.id, edge_id="legacy_user", user_id=1, source="user",
        status="user_added", line_type="process_pipe",
        source_entity_id="ent-A", target_entity_id="ent-B",
        polyline=[[1, 1], [2, 2]], sheet_number=1, directed=None,
    ))
    db_session.commit()
    edges = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    legacy = [e for e in edges if e["id"] == "legacy_user"][0]
    assert legacy["directed"] is True


# ── legacy AUTO edge (no `directed` key on disk) surfaces as False ────────────

def test_legacy_auto_edge_without_key_surfaces_false(client, job):
    # Auto edge dict deliberately omits `directed` (pre-spec canonical_graph.json).
    _write_graph(job, [{
        "id": "e_000", "source": "n_000", "target": "n_001",
        "polyline": [[20, 20], [120, 120]], "tile": "t.png",
        "method": "opencv", "confidence": 0.7,
        # no "directed" key
    }])
    edges = client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]
    auto = [e for e in edges if e["id"] == "e_000"][0]
    assert auto["directed"] is False


# ── mixed: directed auto + directed user + undirected auto in one response ────

def test_graph_mixes_directed_flags_per_edge(client, db_session, job):
    _write_graph(job, [
        {"id": "e_dir", "source": "n_000", "target": "n_001", "polyline": [[0, 0], [1, 1]],
         "tile": "t.png", "method": "opencv", "confidence": 0.7, "directed": True},
        {"id": "e_undir", "source": "n_000", "target": "n_001", "polyline": [[0, 0], [2, 2]],
         "tile": "t.png", "method": "opencv", "confidence": 0.6, "directed": False},
    ])
    client.post(f"/api/v1/jobs/{job.id}/edges", json=_payload(directed=True))
    client.post(f"/api/v1/jobs/{job.id}/edges", json=_payload(directed=False,
                                                              source_entity_id="ent-C",
                                                              target_entity_id="ent-D"))
    edges = {e["id"]: e for e in client.get(f"/api/v1/jobs/{job.id}/graph").json()["edges"]}
    assert edges["e_dir"]["directed"] is True
    assert edges["e_undir"]["directed"] is False
    user_dirs = sorted(e["directed"] for k, e in edges.items()
                       if e["method"] == "user_added")
    assert user_dirs == [False, True]
