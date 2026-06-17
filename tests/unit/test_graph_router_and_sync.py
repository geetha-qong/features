"""Unit tests for Stream 3 graph integration:
  - webapp/graph/graph_db_index.py::sync_graph_to_db (DB read-index dual-write)
  - webapp/routers/graph.py::get_job_graph (file + graph_corrections merge)

In-memory SQLite, router mounted on a local FastAPI app (mirrors
test_edges_api.py — independent of webapp.main registration).
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

from webapp import models
from webapp.auth import get_current_user
from webapp.database import Base, get_db
from webapp.graph.graph_db_index import sync_graph_to_db
from webapp.routers.graph import router as graph_router


def _graph(job_id: int, edges=None):
    return {
        "version": "0.1",
        "job_id": job_id,
        "page": 1,
        "generated_at": "2026-06-13T00:00:00Z",
        "stats": {"nodes": 2, "edges": len(edges or []), "fallback_used": False},
        "nodes": [
            {"id": "n_000", "entity_id": "ent-A", "tag": "BV-1", "class": "valve_bv",
             "bbox": [10, 10, 30, 30], "tile": "tile_p0_r0_c0.png", "confidence": 0.9},
            {"id": "n_001", "entity_id": "ent-B", "tag": "FT-1", "class": "instrument",
             "bbox": [100, 100, 130, 130], "tile": "tile_p0_r0_c0.png", "confidence": 0.8},
        ],
        "edges": edges or [],
        "floating_nodes": [],
        "orphan_lines": [],
    }


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(username="g", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user, tmp_path):
    csv = tmp_path / "valve_list.csv"
    csv.write_text("x")
    j = models.Job(
        user_id=user.id, original_filename="t.pdf", stored_filename="t.pdf",
        pid_no="T-1", status="done", output_csv_path=str(csv),
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


@pytest.fixture()
def client(db_session, user):
    app = FastAPI()
    app.include_router(graph_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── sync_graph_to_db ────────────────────────────────────────────────────────

def test_sync_inserts_nodes_and_edges(db_session, job):
    edges = [{"id": "e_000", "source": "n_000", "target": "n_001",
              "polyline": [[20, 20], [115, 115]], "tile": "t.png",
              "method": "opencv", "confidence": 0.7}]
    n, e = sync_graph_to_db(_graph(job.id, edges), db_session)
    assert (n, e) == (2, 1)
    assert db_session.query(models.GraphNodeRow).filter_by(job_id=job.id).count() == 2
    row = db_session.query(models.GraphEdgeRow).filter_by(job_id=job.id).one()
    assert row.method == "opencv" and row.source_node == "n_000"
    assert row.directed is False  # no `directed` key in edge dict → stored false


def test_sync_persists_directed_flag(db_session, job):
    """A directed edge from canonical_graph.json stores directed=True in graph_edges."""
    edges = [{"id": "e_dir", "source": "n_000", "target": "n_001",
              "polyline": [[0, 0], [1, 1]], "method": "opencv",
              "confidence": 0.9, "directed": True}]
    sync_graph_to_db(_graph(job.id, edges), db_session)
    row = db_session.query(models.GraphEdgeRow).filter_by(job_id=job.id, edge_id="e_dir").one()
    assert row.directed is True


def test_sync_is_idempotent_and_prunes_stale(db_session, job):
    edges = [{"id": "e_000", "source": "n_000", "target": "n_001",
              "polyline": [[0, 0], [1, 1]], "method": "opencv"}]
    sync_graph_to_db(_graph(job.id, edges), db_session)
    # Re-sync with zero edges → stale edge pruned, nodes still 2.
    sync_graph_to_db(_graph(job.id, []), db_session)
    assert db_session.query(models.GraphEdgeRow).filter_by(job_id=job.id).count() == 0
    assert db_session.query(models.GraphNodeRow).filter_by(job_id=job.id).count() == 2


# ── GET /graph ──────────────────────────────────────────────────────────────

def test_get_graph_404_when_no_canonical(client, job):
    # No canonical_graph.json and no canonical.json next to the CSV.
    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_canonical"


def test_get_graph_409_when_canonical_but_no_graph(client, job):
    job_dir = os.path.dirname(job.output_csv_path)
    with open(os.path.join(job_dir, "canonical.json"), "w") as f:
        json.dump({"entities": []}, f)
    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "canonical_required"


def test_get_graph_merges_user_edges(client, db_session, job):
    job_dir = os.path.dirname(job.output_csv_path)
    auto = [{"id": "e_000", "source": "n_000", "target": "n_001",
             "polyline": [[0, 0], [1, 1]], "method": "opencv", "confidence": 0.7}]
    with open(os.path.join(job_dir, "canonical_graph.json"), "w") as f:
        json.dump(_graph(job.id, auto), f)
    # A user-drawn edge + a rejected one (rejected must be excluded).
    db_session.add(models.GraphCorrection(
        job_id=job.id, edge_id="u_1", user_id=1, source="user", status="user_added",
        line_type="process_pipe", source_entity_id="ent-A", target_entity_id="ent-B",
        polyline=[[5, 5], [6, 6]], sheet_number=1))
    db_session.add(models.GraphCorrection(
        job_id=job.id, edge_id="u_2", user_id=1, source="user", status="user_rejected",
        line_type="process_pipe", source_entity_id="ent-A", target_entity_id="ent-B",
        polyline=[[7, 7], [8, 8]], sheet_number=1))
    db_session.commit()

    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    body = r.json()
    methods = sorted(e["method"] for e in body["edges"])
    assert methods == ["opencv", "user_added"]  # rejected excluded
    assert body["stats"]["auto_edges"] == 1 and body["stats"]["user_edges"] == 1

    # directed (graph-directions, 2026-06-17): legacy auto edge (no key) reads
    # as False; user edge surfaces as True.
    by_method = {e["method"]: e for e in body["edges"]}
    assert by_method["opencv"]["directed"] is False
    assert by_method["user_added"]["directed"] is True


def test_get_graph_preserves_directed_auto_edge(client, job):
    """An auto edge whose canonical_graph.json carries directed=true surfaces it."""
    job_dir = os.path.dirname(job.output_csv_path)
    auto = [{"id": "e_000", "source": "n_000", "target": "n_001",
             "polyline": [[0, 0], [1, 1]], "method": "opencv",
             "confidence": 0.7, "directed": True}]
    with open(os.path.join(job_dir, "canonical_graph.json"), "w") as f:
        json.dump(_graph(job.id, auto), f)
    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    assert r.json()["edges"][0]["directed"] is True
