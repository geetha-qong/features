"""Tests for the /api/v1 REST endpoints.

Uses TestClient with an in-memory SQLite DB — no live server needed.
"""
import io
import os
import secrets
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.database import Base, get_db
from webapp import models
from webapp.auth import pwd_context
from webapp.main import app


# ── Test DB setup ──────────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite DB per test; StaticPool ensures all connections share it."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    """TestClient with overridden DB dependency pointing at the test DB."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


# ── Test users + keys ──────────────────────────────────────────────────────────

@pytest.fixture()
def user(db_session):
    u = models.User(
        username="api_tester",
        password_hash=pwd_context.hash("testpass"),
        credits_remaining=20,
        tier="trial",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def api_key_pair(db_session, user):
    """Return (full_key, ApiKey record) for the test user."""
    full_key = "qk_" + secrets.token_hex(16)
    prefix = full_key[:8]
    key_hash = pwd_context.hash(full_key)
    k = models.ApiKey(
        user_id=user.id,
        name="test-key",
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db_session.add(k)
    db_session.commit()
    return full_key, k


# ── GET /api/v1/account ────────────────────────────────────────────────────────

def test_account_no_auth(client):
    resp = client.get("/api/v1/account", follow_redirects=False)
    assert resp.status_code == 401


def test_account_with_api_key(client, user, api_key_pair):
    full_key, _ = api_key_pair
    resp = client.get("/api/v1/account", headers={"Authorization": f"Bearer {full_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "api_tester"
    assert data["credits_remaining"] == 20
    assert data["tier"] == "trial"


# ── GET /api/v1/jobs/{id} ──────────────────────────────────────────────────────

def test_job_status_not_found(client, user, api_key_pair):
    full_key, _ = api_key_pair
    resp = client.get("/api/v1/jobs/99999", headers={"Authorization": f"Bearer {full_key}"})
    assert resp.status_code == 404


def test_job_status_access_denied(client, db_session, user, api_key_pair):
    other = models.User(
        username="other_user", password_hash="x", credits_remaining=5, is_active=True
    )
    db_session.add(other)
    db_session.commit()
    job = models.Job(user_id=other.id, pid_no="T-001", status="done",
                     original_filename="t.pdf", stored_filename="t.pdf")
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(f"/api/v1/jobs/{job.id}", headers={"Authorization": f"Bearer {full_key}"})
    assert resp.status_code == 403


def test_job_status_own_job(client, db_session, user, api_key_pair):
    job = models.Job(user_id=user.id, pid_no="T-002", status="done",
                     original_filename="p.pdf", stored_filename="p.pdf", valve_count=5)
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(f"/api/v1/jobs/{job.id}", headers={"Authorization": f"Bearer {full_key}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["status"] == "done"
    assert data["valve_count"] == 5
    assert data["credits_consumed"] == 0  # no ledger rows
    assert data["csv_url"] is None


# ── POST /api/v1/jobs ──────────────────────────────────────────────────────────

def test_upload_non_pdf_rejected(client, user, api_key_pair):
    full_key, _ = api_key_pair
    resp = client.post(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {full_key}"},
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_upload_insufficient_credits(client, db_session, user, api_key_pair):
    """User with 0 credits cannot submit a job."""
    user.credits_remaining = 0
    db_session.commit()

    full_key, _ = api_key_pair

    # Mock fitz.open to return a 3-page doc without actual file I/O
    mock_doc = MagicMock()
    mock_doc.__len__ = lambda self: 3
    mock_doc.close = lambda: None

    with patch("webapp.routers.api_v1.fitz.open", return_value=mock_doc), \
         patch("shutil.copyfileobj"), \
         patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock()))), \
         patch("webapp.routers.api_v1.get_user_upload_dir") as mock_dir:
        mock_path = MagicMock()
        mock_path.__truediv__ = lambda self, other: mock_path
        mock_path.open = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock()))
        mock_path.unlink = MagicMock()
        mock_dir.return_value = mock_path

        fake_pdf = io.BytesIO(b"%PDF-1.4 fake")
        resp = client.post(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {full_key}"},
            files={"file": ("test.pdf", fake_pdf, "application/pdf")},
        )
    assert resp.status_code == 402
    assert "Insufficient credits" in resp.json()["detail"]

    # Reset credits for subsequent tests
    user.credits_remaining = 20
    db_session.commit()
