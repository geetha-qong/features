"""Tests for /api/v1/users/me/shortcuts.

Covers GET defaults, PATCH whole-object replace + merge-on-read, validation
(unknown action, modifier chord, invalid mode), POST reset, and the
unauthenticated path.

The router is registered onto `app` at test-collection time inside this module
because webapp/main.py wires routers separately (parallel-edit concurrency
hazard during development). When main.py registers the router for real, this
module's include_router is a no-op (FastAPI dedupes by routes).
"""
import os
import sys

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
from webapp.routers import shortcuts as shortcuts_router

# Idempotent: if main.py later registers this router too, FastAPI tolerates
# the duplicate (the second registration just re-exposes the same routes).
app.include_router(shortcuts_router.router)


# ── fixtures ──────────────────────────────────────────────────────────────────


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
        username="shortcut_tester",
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
def client(db_session, user):
    """TestClient with DB + current_user overrides.

    Override `get_current_user` directly so we don't have to mint a cookie /
    JWT for every test. Cleanup is per-test via dependency_overrides.clear().
    """
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


@pytest.fixture()
def unauthed_client(db_session):
    """TestClient with DB but NO get_current_user override — exercises the
    real cookie-JWT path which 303-redirects when no token is present."""
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True, follow_redirects=False)
    app.dependency_overrides.clear()


# ── tests ────────────────────────────────────────────────────────────────────


def test_get_defaults_for_fresh_user(client):
    """User.shortcuts is None → GET returns DEFAULTS exactly."""
    resp = client.get("/api/v1/users/me/shortcuts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["shortcuts"] == shortcuts_router.DEFAULT_SHORTCUTS
    # Sanity-check a couple of known bindings rather than trust the equality.
    assert data["shortcuts"]["v"]["entity_class"] == "valve"
    assert data["shortcuts"]["v"]["sub_class"] == "BV"
    assert data["shortcuts"]["1"]["mode"] == "select"
    assert data["shortcuts"]["Escape"]["action"] == "cancel"


def test_patch_then_get(client, db_session, user):
    """PATCH a subset, then GET returns the merged view (defaults filled in)."""
    payload = {
        "shortcuts": {
            "v": {"action": "select-class", "entity_class": "valve", "sub_class": "GT"},
            "x": {"action": "delete-selected"},
        }
    }
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 200
    # PATCH returns the stored value (NOT merged with defaults).
    stored = resp.json()["shortcuts"]
    assert set(stored.keys()) == {"v", "x"}
    assert stored["v"]["sub_class"] == "GT"

    # GET returns merged: user's "v" overrides default; default "g","b" still present;
    # user's "x" is added on top.
    get_resp = client.get("/api/v1/users/me/shortcuts")
    assert get_resp.status_code == 200
    merged = get_resp.json()["shortcuts"]
    assert merged["v"]["sub_class"] == "GT"               # user override
    assert merged["g"]["sub_class"] == "GT"               # default still present
    assert merged["b"]["sub_class"] == "BF"               # default still present
    assert merged["x"]["action"] == "delete-selected"     # new user binding
    # Sample of an untouched default
    assert merged["Escape"]["action"] == "cancel"

    # DB row was actually updated to the partial map, not the merged map.
    db_session.refresh(user)
    assert set(user.shortcuts.keys()) == {"v", "x"}


def test_patch_unknown_action(client):
    payload = {"shortcuts": {"v": {"action": "do-a-barrel-roll"}}}
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 400
    assert "v" in resp.json()["detail"]
    assert "do-a-barrel-roll" in resp.json()["detail"]


def test_patch_modifier_chord_rejected(client):
    payload = {
        "shortcuts": {
            "Ctrl+S": {"action": "select-class", "entity_class": "valve", "sub_class": "BV"},
        }
    }
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 400
    assert "modifier chords" in resp.json()["detail"]


def test_patch_invalid_mode(client):
    payload = {"shortcuts": {"9": {"action": "mode", "mode": "teleport"}}}
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 400
    assert "mode" in resp.json()["detail"]


def test_patch_select_class_missing_subclass(client):
    """select-class without entity_class+sub_class is a 400, not a silent accept."""
    payload = {"shortcuts": {"v": {"action": "select-class", "entity_class": "valve"}}}
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 400
    assert "select-class" in resp.json()["detail"]


def test_patch_long_key_rejected(client):
    """Multi-char keys outside the NAMED_KEYS allowlist are rejected."""
    payload = {"shortcuts": {"Backspace": {"action": "delete-selected"}}}
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 400
    assert "Backspace" in resp.json()["detail"]


def test_patch_named_key_accepted(client):
    """Tab/Enter/Space (in NAMED_KEYS) are valid alongside single chars."""
    payload = {"shortcuts": {"Tab": {"action": "cancel"}}}
    resp = client.patch("/api/v1/users/me/shortcuts", json=payload)
    assert resp.status_code == 200


def test_reset(client, db_session, user):
    """After PATCH then POST /reset, GET returns DEFAULTS and DB row is NULL."""
    payload = {
        "shortcuts": {
            "v": {"action": "select-class", "entity_class": "valve", "sub_class": "GT"},
        }
    }
    client.patch("/api/v1/users/me/shortcuts", json=payload)
    db_session.refresh(user)
    assert user.shortcuts is not None  # PATCH took effect

    reset = client.post("/api/v1/users/me/shortcuts/reset")
    assert reset.status_code == 200
    assert reset.json()["shortcuts"] == shortcuts_router.DEFAULT_SHORTCUTS

    db_session.refresh(user)
    assert user.shortcuts is None       # cleared

    get_resp = client.get("/api/v1/users/me/shortcuts")
    assert get_resp.json()["shortcuts"] == shortcuts_router.DEFAULT_SHORTCUTS


def test_unauthenticated_401(unauthed_client):
    """Without a session cookie, the endpoint blocks the request.

    Note: the project's `get_current_user` raises a 303 redirect to /signin
    rather than a 401 (cookie-auth pattern shared across the app). The
    important contract is "not 2xx" — we assert the redirect status here.
    """
    resp = unauthed_client.get("/api/v1/users/me/shortcuts")
    assert resp.status_code in (401, 303)
    assert resp.status_code != 200
