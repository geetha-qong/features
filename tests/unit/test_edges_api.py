"""Unit tests for webapp/routers/edges.py — graph-edge CRUD endpoints.

Uses TestClient with an in-memory SQLite DB. Mounts the router on a local
FastAPI app (not webapp.main.app) because the main router-registration is
done by the orchestrator after this subagent finishes; the router is testable
in isolation.
"""
from __future__ import annotations

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
from webapp.routers.edges import router as edges_router


# ── App + DB fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(
        username="marker",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def other_user(db_session):
    u = models.User(
        username="someone_else",
        password_hash="x",
        role="user",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user):
    j = models.Job(
        user_id=user.id,
        original_filename="t.pdf",
        stored_filename="t.pdf",
        pid_no="T-001",
        status="done",
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


@pytest.fixture()
def foreign_job(db_session, other_user):
    j = models.Job(
        user_id=other_user.id,
        original_filename="o.pdf",
        stored_filename="o.pdf",
        pid_no="O-001",
        status="done",
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


@pytest.fixture()
def client(db_session, user):
    """Local FastAPI app with just the edges router mounted, plus DB + auth
    overrides. Avoids depending on webapp.main router registration which
    the orchestrator wires up after this file lands.
    """
    app = FastAPI()
    app.include_router(edges_router)

    def _override_db():
        yield db_session

    def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── helpers ───────────────────────────────────────────────────────────────────

def _valid_payload(**overrides):
    payload = {
        "line_type": "process_pipe",
        "source_entity_id": "ent-A",
        "target_entity_id": "ent-B",
        "polyline": [[10.0, 20.0], [110.0, 20.0], [110.0, 120.0]],
        "sheet_number": 1,
    }
    payload.update(overrides)
    return payload


# ── tests ─────────────────────────────────────────────────────────────────────

def test_list_empty(client, job):
    resp = client.get(f"/api/v1/jobs/{job.id}/edges")
    assert resp.status_code == 200
    assert resp.json() == {"edges": []}


def test_create_process_pipe(client, db_session, job, user):
    resp = client.post(f"/api/v1/jobs/{job.id}/edges", json=_valid_payload())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "user_added"
    assert data["source"] == "user"
    assert data["line_type"] == "process_pipe"
    assert data["job_id"] == job.id
    assert data["user_id"] == user.id
    assert len(data["edge_id"]) == 32  # uuid4().hex

    # Verify in DB
    row = (
        db_session.query(models.GraphCorrection)
        .filter_by(job_id=job.id, edge_id=data["edge_id"])
        .one()
    )
    assert row.status == "user_added"
    assert row.source == "user"
    assert row.line_type == "process_pipe"
    assert row.source_entity_id == "ent-A"
    assert row.target_entity_id == "ent-B"


# ── directed flag (graph-directions, 2026-06-17) ──────────────────────────────

def test_create_defaults_directed_true(client, db_session, job):
    """User edges are directed source→target by construction → default True."""
    resp = client.post(f"/api/v1/jobs/{job.id}/edges", json=_valid_payload())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["directed"] is True
    row = (
        db_session.query(models.GraphCorrection)
        .filter_by(job_id=job.id, edge_id=data["edge_id"])
        .one()
    )
    assert bool(row.directed) is True


def test_create_directed_false_round_trips(client, job):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges", json=_valid_payload(directed=False)
    )
    assert resp.status_code == 201, resp.text
    edge_id = resp.json()["edge_id"]
    assert resp.json()["directed"] is False
    # GET surfaces it too.
    listing = client.get(f"/api/v1/jobs/{job.id}/edges").json()["edges"]
    match = [e for e in listing if e["edge_id"] == edge_id]
    assert len(match) == 1
    assert match[0]["directed"] is False


def test_patch_can_flip_direction(client, job):
    edge_id = client.post(
        f"/api/v1/jobs/{job.id}/edges", json=_valid_payload()
    ).json()["edge_id"]
    resp = client.patch(
        f"/api/v1/jobs/{job.id}/edges/{edge_id}", json={"directed": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["directed"] is False


@pytest.mark.parametrize("line_type", ["process_pipe", "instrument", "signal", "interlock"])
def test_create_each_line_type(client, job, line_type):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(line_type=line_type),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["line_type"] == line_type


def test_create_invalid_line_type(client, job):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(line_type="laser_beam"),
    )
    assert resp.status_code == 400
    assert "invalid line_type" in resp.json()["detail"]


def test_create_short_polyline(client, job):
    # Single-point polyline — fails pydantic conlist(min_length=2)
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(polyline=[[10.0, 20.0]]),
    )
    assert resp.status_code == 422  # FastAPI / pydantic validation

    # Bad point shape (only one coord)
    resp2 = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(polyline=[[10.0], [20.0]]),
    )
    assert resp2.status_code == 422


def test_create_self_loop(client, job):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(source_entity_id="X", target_entity_id="X"),
    )
    assert resp.status_code == 400
    assert "self-loop" in resp.json()["detail"].lower()


def test_create_invalid_relation_type(client, job):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(relation_type="teleports"),
    )
    assert resp.status_code == 400
    assert "invalid relation_type" in resp.json()["detail"]


def test_create_valid_relation_type_ok(client, job):
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(relation_type="carries"),
    )
    assert resp.status_code == 201, resp.text


def test_patch_invalid_status_rejected(client, job):
    edge_id = client.post(
        f"/api/v1/jobs/{job.id}/edges", json=_valid_payload()
    ).json()["edge_id"]
    resp = client.patch(
        f"/api/v1/jobs/{job.id}/edges/{edge_id}", json={"status": "user_rejcted"}
    )
    assert resp.status_code == 400
    assert "invalid status" in resp.json()["detail"]


def test_create_oversized_polyline_rejected(client, job):
    # > max_length (500) points — pydantic conlist max_length guard (DoS cap).
    huge = [[float(i), float(i)] for i in range(501)]
    resp = client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(polyline=huge),
    )
    assert resp.status_code == 422


def test_foreign_job_404(client, foreign_job):
    """A user must not see (or write to) another user's job — IDOR 404."""
    # GET
    resp = client.get(f"/api/v1/jobs/{foreign_job.id}/edges")
    assert resp.status_code == 404

    # POST
    resp = client.post(
        f"/api/v1/jobs/{foreign_job.id}/edges",
        json=_valid_payload(),
    )
    assert resp.status_code == 404

    # PATCH (irrelevant edge_id — still 404 on job check)
    resp = client.patch(
        f"/api/v1/jobs/{foreign_job.id}/edges/deadbeef",
        json={"status": "user_confirmed"},
    )
    assert resp.status_code == 404

    # DELETE
    resp = client.delete(f"/api/v1/jobs/{foreign_job.id}/edges/deadbeef")
    assert resp.status_code == 404


def test_patch_relation_and_group(client, db_session, job):
    """Can reclassify a process_pipe edge into an interlock loop with group_id."""
    create = client.post(f"/api/v1/jobs/{job.id}/edges", json=_valid_payload())
    assert create.status_code == 201
    edge_id = create.json()["edge_id"]

    patch = client.patch(
        f"/api/v1/jobs/{job.id}/edges/{edge_id}",
        json={
            "line_type": "interlock",
            "relation_type": "interlocks_with",
            "group_id": "loop-FIC-101",
        },
    )
    assert patch.status_code == 200, patch.text
    data = patch.json()
    assert data["line_type"] == "interlock"
    assert data["relation_type"] == "interlocks_with"
    assert data["group_id"] == "loop-FIC-101"

    # DB reflects the change
    db_session.expire_all()
    row = (
        db_session.query(models.GraphCorrection)
        .filter_by(edge_id=edge_id)
        .one()
    )
    assert row.line_type == "interlock"
    assert row.relation_type == "interlocks_with"
    assert row.group_id == "loop-FIC-101"


def test_patch_invalid_line_type(client, job):
    create = client.post(f"/api/v1/jobs/{job.id}/edges", json=_valid_payload())
    edge_id = create.json()["edge_id"]
    resp = client.patch(
        f"/api/v1/jobs/{job.id}/edges/{edge_id}",
        json={"line_type": "telepathy"},
    )
    assert resp.status_code == 400


def test_patch_unknown_edge_404(client, job):
    resp = client.patch(
        f"/api/v1/jobs/{job.id}/edges/nonexistent",
        json={"status": "user_confirmed"},
    )
    assert resp.status_code == 404


def test_delete_204(client, db_session, job):
    create = client.post(f"/api/v1/jobs/{job.id}/edges", json=_valid_payload())
    edge_id = create.json()["edge_id"]

    resp = client.delete(f"/api/v1/jobs/{job.id}/edges/{edge_id}")
    assert resp.status_code == 204
    assert resp.content == b""

    # Confirm hard delete
    assert (
        db_session.query(models.GraphCorrection)
        .filter_by(edge_id=edge_id)
        .first()
        is None
    )

    # Second delete → 404 (idempotency boundary: hard delete is not idempotent
    # on the response side, only on the DB state side).
    resp2 = client.delete(f"/api/v1/jobs/{job.id}/edges/{edge_id}")
    assert resp2.status_code == 404


def test_group_id_visible_in_list(client, job):
    """Edges with the same group_id all appear in the list endpoint with that
    group_id surfaced — exercises the read path for control-loop UI."""
    g = "loop-FIC-202"
    client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(
            source_entity_id="FIC-202",
            target_entity_id="FT-202",
            line_type="signal",
            group_id=g,
        ),
    )
    client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(
            source_entity_id="FIC-202",
            target_entity_id="FV-202",
            line_type="signal",
            group_id=g,
        ),
    )
    client.post(
        f"/api/v1/jobs/{job.id}/edges",
        json=_valid_payload(
            source_entity_id="P-101",
            target_entity_id="V-101",
            line_type="process_pipe",
        ),  # group_id NULL
    )

    resp = client.get(f"/api/v1/jobs/{job.id}/edges")
    assert resp.status_code == 200
    edges = resp.json()["edges"]
    assert len(edges) == 3
    grouped = [e for e in edges if e["group_id"] == g]
    assert len(grouped) == 2
    assert {e["target_entity_id"] for e in grouped} == {"FT-202", "FV-202"}
    ungrouped = [e for e in edges if e["group_id"] is None]
    assert len(ungrouped) == 1
    assert ungrouped[0]["line_type"] == "process_pipe"


def test_create_with_metadata_and_target_sheet(client, job):
    """Cross-sheet edge with line-type-specific metadata round-trips."""
    payload = _valid_payload(
        line_type="signal",
        relation_type="carries",
        target_sheet_number=3,
        metadata_json={"signal_type": "4-20mA", "fail_safe": "open"},
    )
    resp = client.post(f"/api/v1/jobs/{job.id}/edges", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["target_sheet_number"] == 3
    assert data["metadata_json"]["signal_type"] == "4-20mA"
    assert data["metadata_json"]["fail_safe"] == "open"
