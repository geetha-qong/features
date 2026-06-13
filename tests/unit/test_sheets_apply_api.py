"""Unit tests for webapp/routers/sheets.py — sheet "Apply" state endpoints.

Mirrors test_edges_api.py: TestClient + in-memory SQLite, router mounted on a
local FastAPI app with db/auth dependency overrides.
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
from webapp.routers.sheets import router as sheets_router


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
    u = models.User(username="marker", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def other_user(db_session):
    u = models.User(username="someone_else", password_hash="x", role="user", is_active=True)
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
    app = FastAPI()
    app.include_router(sheets_router)

    def _override_db():
        yield db_session

    def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_applied_empty(client, job):
    resp = client.get(f"/api/v1/jobs/{job.id}/sheets/applied")
    assert resp.status_code == 200
    assert resp.json() == {"applied": {}}


def test_apply_creates_row(client, db_session, job, user):
    resp = client.post(f"/api/v1/jobs/{job.id}/sheets/3/apply")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["sheet_number"] == 3
    assert data["applied_by"] == user.id
    assert data["applied_at"].endswith("Z")  # utc_iso Z-suffix convention

    row = (
        db_session.query(models.SheetApplyState)
        .filter_by(job_id=job.id, sheet_number=3)
        .one()
    )
    assert row.applied_by == user.id
    assert row.applied_at is not None


def test_apply_then_get_returns_map(client, job):
    client.post(f"/api/v1/jobs/{job.id}/sheets/1/apply")
    client.post(f"/api/v1/jobs/{job.id}/sheets/4/apply")

    resp = client.get(f"/api/v1/jobs/{job.id}/sheets/applied")
    assert resp.status_code == 200
    applied = resp.json()["applied"]
    # JSON object keys come back as strings.
    assert set(applied.keys()) == {"1", "4"}
    for v in applied.values():
        assert v.endswith("Z")


def test_apply_is_upsert(client, db_session, job):
    first = client.post(f"/api/v1/jobs/{job.id}/sheets/2/apply")
    assert first.status_code == 200
    first_at = first.json()["applied_at"]

    second = client.post(f"/api/v1/jobs/{job.id}/sheets/2/apply")
    assert second.status_code == 200

    # Still exactly one row (UNIQUE(job_id, sheet_number) upsert, not duplicate).
    rows = (
        db_session.query(models.SheetApplyState)
        .filter_by(job_id=job.id, sheet_number=2)
        .all()
    )
    assert len(rows) == 1
    # applied_at refreshed (>= the first timestamp).
    assert second.json()["applied_at"] >= first_at


def test_delete_clears(client, db_session, job):
    client.post(f"/api/v1/jobs/{job.id}/sheets/5/apply")

    resp = client.delete(f"/api/v1/jobs/{job.id}/sheets/5/apply")
    assert resp.status_code == 204
    assert resp.content == b""

    assert (
        db_session.query(models.SheetApplyState)
        .filter_by(job_id=job.id, sheet_number=5)
        .first()
        is None
    )

    # No longer in the applied map.
    applied = client.get(f"/api/v1/jobs/{job.id}/sheets/applied").json()["applied"]
    assert "5" not in applied


def test_delete_unapplied_is_idempotent_204(client, job):
    # Re-arming a sheet that was never applied is a no-op 204 (not 404).
    resp = client.delete(f"/api/v1/jobs/{job.id}/sheets/9/apply")
    assert resp.status_code == 204


def test_foreign_job_404(client, foreign_job):
    """A user must not see/write another user's job — IDOR 404."""
    assert client.get(f"/api/v1/jobs/{foreign_job.id}/sheets/applied").status_code == 404
    assert client.post(f"/api/v1/jobs/{foreign_job.id}/sheets/1/apply").status_code == 404
    assert client.delete(f"/api/v1/jobs/{foreign_job.id}/sheets/1/apply").status_code == 404


def test_unknown_job_404(client):
    assert client.get("/api/v1/jobs/99999/sheets/applied").status_code == 404
    assert client.post("/api/v1/jobs/99999/sheets/1/apply").status_code == 404
