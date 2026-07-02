"""Tests for GET /api/v1/admin/annotations/metrics."""

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

from webapp.auth import create_access_token, pwd_context  # noqa: E402
from webapp.database import Base, get_db  # noqa: E402
from webapp import models  # noqa: E402
from webapp.main import app  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


@pytest.fixture()
def regular_user(db_session, client):
    u = models.User(
        username="reg",
        password_hash=pwd_context.hash("x"),
        role="user",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def admin_user(db_session, client):
    u = models.User(
        username="admin",
        password_hash=pwd_context.hash("x"),
        role="super_admin",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _login(client, user):
    token = create_access_token({"sub": user.username})
    client.cookies.set("access_token", token)


def test_metrics_unauthenticated_redirects(client):
    """No cookie => 303 redirect to /signin (auth dep). Treated as not-authed."""
    resp = client.get("/api/v1/admin/annotations/metrics", follow_redirects=False)
    # cookie-auth returns 303 with Location: /signin for missing/invalid token.
    assert resp.status_code in (303, 401)


def test_metrics_forbidden_for_non_admin(client, regular_user):
    _login(client, regular_user)
    resp = client.get("/api/v1/admin/annotations/metrics")
    assert resp.status_code == 403


def test_metrics_shape_on_populated_db(client, db_session, admin_user):
    _login(client, admin_user)
    # One done job with 3 model detections.
    job = models.Job(
        user_id=admin_user.id,
        original_filename="p.pdf",
        stored_filename="p.pdf",
        pid_no="T-1",
        status="done",
        gpu_detections=json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    for status, eid in [
        ("user_added", "ent-1"),
        ("user_added", "ent-2"),
        ("user_confirmed", "ent-3"),
        ("user_rejected", "ent-4"),
    ]:
        db_session.add(
            models.UserAnnotation(
                job_id=job.id,
                entity_id=eid,
                user_id=admin_user.id,
                source="user",
                status=status,
                entity_class="valve",
                sub_class="BV",
                bbox=[1, 2, 3, 4],
                sheet_number=1,
            )
        )
    db_session.commit()

    resp = client.get("/api/v1/admin/annotations/metrics")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_model_detections"] == 3
    assert data["total_user_annotations"] == 4
    bs = data["by_status"]
    assert bs["user_added"] == 2
    assert bs["user_confirmed"] == 1
    assert bs["user_rejected"] == 1
    assert "model_found" in bs

    assert isinstance(data["per_day_last_30"], list)
    assert len(data["per_day_last_30"]) == 30
    for item in data["per_day_last_30"]:
        assert "date" in item
        assert "model" in item
        assert "user" in item


def test_metrics_empty_db_zero_counts(client, db_session, admin_user):
    _login(client, admin_user)
    resp = client.get("/api/v1/admin/annotations/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_model_detections"] == 0
    assert data["total_user_annotations"] == 0
    assert data["by_status"]["user_added"] == 0
    assert len(data["per_day_last_30"]) == 30
