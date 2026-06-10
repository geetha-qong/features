"""Tests for GET /jobs/{job_id}/page/{page_index}/full.

Covers:
  - Happy path: file exists → 200 + image/png + CORS headers.
  - 404 when file missing.
  - 404 (not 403) when job belongs to another user (IDOR pattern).
  - OPTIONS preflight returns CORS headers.

In-memory sqlite via StaticPool; `get_db` and `get_current_user` overridden
through `app.dependency_overrides` — no real auth flow is exercised.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.database import Base, get_db
from webapp import models
from webapp.auth import get_current_user, pwd_context
from webapp.main import app
from webapp.routers import jobs as jobs_router


# ── Test DB setup ──────────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
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
def user(db_session):
    u = models.User(
        username="page_full_owner",
        password_hash=pwd_context.hash("testpass"),
        credits_remaining=10,
        tier="trial",
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
        username="page_full_other",
        password_hash=pwd_context.hash("testpass"),
        credits_remaining=10,
        tier="trial",
        is_active=True,
        role="user",
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
    """TestClient that auths as `user` and routes DB through the in-memory session."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


# Minimal PNG header (8-byte signature + IHDR with 1x1 dimensions). Enough
# bytes that FileResponse will happily stream it back.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a"  # PNG signature
    "0000000d49484452"  # IHDR length + type
    "00000001000000010806000000"  # 1×1 RGBA
    "1f15c4890000000a49444154789c63000100000005000157bf"  # IDAT
    "0000000049454e44ae426082"  # IEND
)


@pytest.fixture()
def page_full_dir(tmp_path, monkeypatch):
    """Redirect `get_job_dir` so jobs.py writes/reads under a tmp dir.

    Returns a callable: `seed(job, page_idx, content=_TINY_PNG)` writes the
    page-full PNG into the patched location.
    """
    base = tmp_path

    def fake_get_job_dir(j) -> Path:
        d = base / str(j.user_id) / str(j.id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(jobs_router, "get_job_dir", fake_get_job_dir)

    def seed(j, page_idx: int, content: bytes = _TINY_PNG) -> Path:
        tmp_dir = fake_get_job_dir(j) / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        png_path = tmp_dir / f"page_{page_idx}_full.png"
        png_path.write_bytes(content)
        return png_path

    return seed


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_serve_page_full_ok(client, job, page_full_dir):
    seeded = page_full_dir(job, 0)
    assert seeded.exists()

    resp = client.get(f"/jobs/{job.id}/page/0/full")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("vary") == "Origin"
    assert "access-control-allow-methods" in {k.lower() for k in resp.headers.keys()}
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_serve_page_full_missing(client, job, page_full_dir):  # noqa: ARG001
    # No seed — dir exists (created lazily by fake_get_job_dir on access) but file is absent.
    resp = client.get(f"/jobs/{job.id}/page/3/full")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "page render not found"


def test_serve_page_full_foreign_job_404(client, foreign_job, page_full_dir):
    # Even if the file exists on disk, the auth check fires first and returns 404.
    page_full_dir(foreign_job, 0)
    resp = client.get(f"/jobs/{foreign_job.id}/page/0/full")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_serve_page_full_unknown_job_404(client, page_full_dir):  # noqa: ARG001
    resp = client.get("/jobs/99999/page/0/full")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_options_preflight(client, job):
    resp = client.options(f"/jobs/{job.id}/page/0/full")
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("vary") == "Origin"
    methods = resp.headers.get("access-control-allow-methods", "")
    assert "GET" in methods
