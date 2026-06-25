"""Tests for /api/v1/jobs/{job_id}/annotations.

Mirrors test_api_v1.py: in-memory sqlite + StaticPool + TestClient. Auth is
mocked via dependency_overrides on get_current_user — no JWT cookie flow.
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models
from webapp.auth import get_current_user, pwd_context
from webapp.database import Base, get_db
from webapp.main import app
from webapp.routers.annotations import router as annotations_router  # ensure import side-effects


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Workaround for an upstream model defect: GraphCorrection has both
    # `index=True` on `line_type` AND an explicit Index with the same name,
    # which SQLite refuses to create twice. Drop the duplicate before DDL.
    gc_table = Base.metadata.tables.get("graph_corrections")
    if gc_table is not None:
        dupes = [
            ix for ix in gc_table.indexes
            if ix.name == "ix_graph_corrections_line_type"
        ]
        if len(dupes) > 1:
            for ix in dupes[1:]:
                gc_table.indexes.discard(ix)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    # Register the annotations router on the test app. main.py registration
    # happens in the main session per the spec, but tests need routes live
    # now. We insert at index 0 so the SPA catch-all in main.py (mounted at
    # "/" with prefix matching every path) doesn't shadow our /api/v1 routes.
    _already_registered = any(
        getattr(r, "path", None) == "/api/v1/jobs/{job_id}/annotations"
        for r in app.routes
    )
    if not _already_registered:
        # include_router appends; we then bubble the new routes to the front
        # so they win over the SPA catch-all that's already in app.routes.
        before = len(app.routes)
        app.include_router(annotations_router)
        added = app.routes[before:]
        del app.routes[before:]
        app.router.routes[0:0] = added
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(
        username="annotator_a",
        password_hash=pwd_context.hash("x"),
        credits_remaining=20,
        is_active=True,
        role="user",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def other_user(db_session):
    u = models.User(
        username="annotator_b",
        password_hash=pwd_context.hash("x"),
        credits_remaining=20,
        is_active=True,
        role="user",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def client(db_session, user):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _make_job(db_session, owner, *, pid_no="T-001", gpu_detections=None) -> models.Job:
    job = models.Job(
        user_id=owner.id,
        pid_no=pid_no,
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        gpu_detections=json.dumps(gpu_detections) if gpu_detections else None,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# ── tests ─────────────────────────────────────────────────────────────────────


def test_list_empty(client, db_session, user):
    job = _make_job(db_session, user)
    resp = client.get(f"/api/v1/jobs/{job.id}/annotations")
    assert resp.status_code == 200
    assert resp.json() == {"annotations": []}


def test_create_fresh_mark(client, db_session, user):
    """POST with linked_detection_index=null → user_added, placeholder_tag set,
    AND a new model_corrections('add') row linked via linked_correction_id."""
    job = _make_job(db_session, user)
    resp = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": [10.0, 20.0, 30.0, 40.0],
            "sheet_number": 1,
            "linked_detection_index": None,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "user_added"
    assert body["source"] == "user"
    assert body["entity_class"] == "valve"
    assert body["sub_class"] == "BV"
    assert body["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert body["placeholder_tag"] == "USER-BV-0001"
    assert body["linked_correction_id"] is not None
    assert body["linked_detection_index"] is None

    # Verify model_corrections row landed with action='add'
    corrections = db_session.query(models.ModelCorrection).filter(
        models.ModelCorrection.job_id == job.id
    ).all()
    assert len(corrections) == 1
    assert corrections[0].action == "add"
    assert corrections[0].new_label == "valve_bv"
    assert corrections[0].new_bbox == [10.0, 20.0, 30.0, 40.0]
    assert corrections[0].detection_index == -1
    assert corrections[0].id == body["linked_correction_id"]


def test_create_confirm(client, db_session, user):
    """Pre-seed Job.gpu_detections[0] with valve_bv. POST with linked_detection_index=0
    + matching class → status='user_confirmed', NO model_corrections row."""
    job = _make_job(
        db_session,
        user,
        gpu_detections=[
            {"bbox": [1, 2, 3, 4], "label": "valve_bv", "confidence": 0.9},
        ],
    )
    resp = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "sheet_number": 1,
            "linked_detection_index": 0,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "user_confirmed"
    assert body["source"] == "model"
    assert body["linked_detection_index"] == 0
    assert body["linked_correction_id"] is None

    # No corrections row for a pure confirmation
    corrections = db_session.query(models.ModelCorrection).filter(
        models.ModelCorrection.job_id == job.id
    ).all()
    assert corrections == []


def test_create_replace(client, db_session, user):
    """Same setup as confirm but POST a different class → user_added +
    model_corrections('delete') flagging the original detection as wrong."""
    job = _make_job(
        db_session,
        user,
        gpu_detections=[
            {"bbox": [1, 2, 3, 4], "label": "valve_bv", "confidence": 0.9},
        ],
    )
    resp = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "GT",       # differs from model's BV
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "sheet_number": 1,
            "linked_detection_index": 0,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "user_added"
    assert body["source"] == "user"
    assert body["linked_correction_id"] is not None

    corrections = db_session.query(models.ModelCorrection).filter(
        models.ModelCorrection.job_id == job.id
    ).all()
    assert len(corrections) == 1
    assert corrections[0].action == "delete"
    assert corrections[0].detection_index == 0
    assert corrections[0].id == body["linked_correction_id"]


def test_foreign_job_404(client, db_session, other_user):
    """POSTing to another user's job → 404 (not 403). Same for GET / PATCH /
    DELETE — but POST covers the auth pattern cleanly here."""
    foreign_job = _make_job(db_session, other_user, pid_no="T-FOR")
    resp = client.post(
        f"/api/v1/jobs/{foreign_job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": [1.0, 2.0, 3.0, 4.0],
        },
    )
    assert resp.status_code == 404
    resp_get = client.get(f"/api/v1/jobs/{foreign_job.id}/annotations")
    assert resp_get.status_code == 404


def test_patch_status_and_tag(client, db_session, user):
    job = _make_job(db_session, user)
    create = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "instrument",
            "sub_class": "FT",
            "bbox": [0.0, 0.0, 5.0, 5.0],
            "linked_detection_index": None,
        },
    )
    assert create.status_code == 201
    entity_id = create.json()["entity_id"]

    patch = client.patch(
        f"/api/v1/jobs/{job.id}/annotations/{entity_id}",
        json={"status": "user_confirmed", "tag": "FT-202"},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["status"] == "user_confirmed"
    assert body["tag"] == "FT-202"
    assert body["entity_id"] == entity_id

    # Bad status → 422 from Pydantic validator
    bad = client.patch(
        f"/api/v1/jobs/{job.id}/annotations/{entity_id}",
        json={"status": "not_a_real_status"},
    )
    assert bad.status_code == 422


def test_delete_204_and_gone(client, db_session, user):
    job = _make_job(db_session, user)
    create = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "equipment",
            "sub_class": "P",
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "linked_detection_index": None,
        },
    )
    assert create.status_code == 201
    entity_id = create.json()["entity_id"]

    delete = client.delete(f"/api/v1/jobs/{job.id}/annotations/{entity_id}")
    assert delete.status_code == 204
    assert delete.content == b""

    # Second delete → 404
    delete2 = client.delete(f"/api/v1/jobs/{job.id}/annotations/{entity_id}")
    assert delete2.status_code == 404

    # And the list is empty again
    listed = client.get(f"/api/v1/jobs/{job.id}/annotations")
    assert listed.status_code == 200
    assert listed.json()["annotations"] == []


def test_unique_constraint(client, db_session, user, monkeypatch):
    """Two POSTs that resolve to the same entity_id → second returns 409.

    Entity IDs come from uuid4().hex so collisions don't happen organically.
    Patch uuid4 to deterministically return the same id twice and verify the
    UNIQUE (job_id, entity_id) constraint surfaces as a 409 (documented
    choice — not upsert, since callers should retry with a fresh id rather
    than silently mutating the prior row).
    """
    import webapp.routers.annotations as anno_mod

    class _FixedUUID:
        hex = "deadbeefdeadbeefdeadbeefdeadbeef"

    monkeypatch.setattr(anno_mod.uuid, "uuid4", lambda: _FixedUUID())

    job = _make_job(db_session, user)
    payload = {
        "entity_class": "valve",
        "sub_class": "BV",
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "linked_detection_index": None,
    }
    first = client.post(f"/api/v1/jobs/{job.id}/annotations", json=payload)
    assert first.status_code == 201
    second = client.post(f"/api/v1/jobs/{job.id}/annotations", json=payload)
    assert second.status_code == 409


def test_bad_payload_400(client, db_session, user):
    """Pydantic-level validation: bbox of length 3 → 422 (FastAPI's default
    code for body-validation failure). Documented here because the spec calls
    for "400 for bad payload" — FastAPI uses 422 for body shape errors, and
    we don't override that. Asserting the precise code keeps the contract
    explicit."""
    job = _make_job(db_session, user)
    resp = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": [1.0, 2.0, 3.0],   # only 3 elements
        },
    )
    assert resp.status_code == 422

    # Bad entity_class
    resp2 = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "pipe",
            "sub_class": "BV",
            "bbox": [1.0, 2.0, 3.0, 4.0],
        },
    )
    assert resp2.status_code == 422


def test_list_returns_all_statuses(client, db_session, user):
    """GET must return rows of every status — caller filters client-side."""
    job = _make_job(
        db_session,
        user,
        gpu_detections=[
            {"bbox": [1, 2, 3, 4], "label": "valve_bv"},
        ],
    )
    # confirmed
    client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve", "sub_class": "BV",
            "bbox": [1.0, 2.0, 3.0, 4.0], "linked_detection_index": 0,
        },
    )
    # fresh added
    client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve", "sub_class": "GT",
            "bbox": [5.0, 6.0, 7.0, 8.0], "linked_detection_index": None,
        },
    )
    resp = client.get(f"/api/v1/jobs/{job.id}/annotations")
    assert resp.status_code == 200
    annotations = resp.json()["annotations"]
    assert len(annotations) == 2
    statuses = {a["status"] for a in annotations}
    assert statuses == {"user_confirmed", "user_added"}
