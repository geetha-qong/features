"""Regression tests for the POST /api/v1/account/api-keys flow.

Locks in the security fix for the redirect-URL-leak vulnerability: the POST
handler must return the new key directly in the JSON response body, NOT
redirect with the key in a URL query string. URL params land in nginx access
logs, browser history, and Referer headers; the JSON body does not.

Migrated 2026-06-02 from the legacy Jinja /account/api-keys form (deleted
with the Jinja->SPA sweep, FEATURES #19). The endpoint is now JSON-only.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.auth import create_access_token, pwd_context
from webapp.database import Base, get_db
from webapp import models
from webapp.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_user(db_session, client):
    u = models.User(
        username="ak_tester",
        password_hash=pwd_context.hash("testpass"),
        credits_remaining=10,
        tier="trial",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    token = create_access_token({"sub": u.username})
    client.cookies.set("access_token", token)
    return u


def test_post_create_returns_key_in_json_body_not_redirect(client, authed_user, db_session):
    """SECURITY: the new key must appear in the JSON response body, never in a
    Location: header or URL query string. This locks in the fix for the
    redirect-URL-leak vulnerability."""
    resp = client.post(
        "/api/v1/account/api-keys",
        json={"name": "ci"},
        follow_redirects=False,
    )
    # MUST be a 201 direct render, NOT a 303 redirect
    assert resp.status_code == 201, f"expected 201 Created, got {resp.status_code}"
    assert "location" not in {h.lower() for h in resp.headers}, (
        "POST handler must not set Location header — that would leak the key "
        "into nginx access logs and browser history."
    )
    payload = resp.json()
    full_key = payload["key"]
    assert full_key.startswith("qk_"), f"expected key with qk_ prefix, got {full_key!r}"
    assert len(full_key) == len("qk_") + 32, "expected qk_<32hex>"
    assert payload["key_prefix"] == full_key[:8]

    # And the key must actually verify against the stored hash
    key_row = (
        db_session.query(models.ApiKey)
        .filter(models.ApiKey.user_id == authed_user.id)
        .order_by(models.ApiKey.created_at.desc())
        .first()
    )
    assert key_row is not None
    assert pwd_context.verify(full_key, key_row.key_hash)


def test_list_does_not_expose_full_key(client, authed_user, db_session):
    """SECURITY: GET /api/v1/account/api-keys must return only metadata + prefix.
    The full key is only returned by POST (one-time reveal). The DB only stores
    a bcrypt hash, so even the server cannot recover the full value after creation."""
    create = client.post(
        "/api/v1/account/api-keys", json={"name": "list-test"}, follow_redirects=False,
    )
    assert create.status_code == 201
    full_key = create.json()["key"]

    list_resp = client.get("/api/v1/account/api-keys", follow_redirects=False)
    assert list_resp.status_code == 200
    body_text = list_resp.text
    assert full_key not in body_text, "full key must NOT appear in any list response"
    # But the prefix should
    assert full_key[:8] in body_text


def test_revoke_returns_204_and_removes_from_list(client, authed_user, db_session):
    create = client.post(
        "/api/v1/account/api-keys", json={"name": "to-revoke"}, follow_redirects=False,
    )
    key_id = create.json()["id"]

    revoke = client.delete(f"/api/v1/account/api-keys/{key_id}", follow_redirects=False)
    assert revoke.status_code == 204

    listed = client.get("/api/v1/account/api-keys", follow_redirects=False).json()
    assert all(k["id"] != key_id for k in listed["keys"]), "revoked key must not appear in list"


def test_revoke_other_users_key_returns_404(client, authed_user, db_session):
    """SECURITY: a user must not be able to revoke another user's key — even
    by guessing the id. The handler scopes by user_id, so an unknown-to-this-
    user id returns 404 (not 403, which would leak existence)."""
    other = models.User(
        username="other_user",
        password_hash=pwd_context.hash("x"),
        credits_remaining=0,
        tier="trial",
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    other_key = models.ApiKey(
        user_id=other.id,
        name="other-user-key",
        key_prefix="qk_aaaaa",
        key_hash=pwd_context.hash("qk_dummy"),
    )
    db_session.add(other_key)
    db_session.commit()
    db_session.refresh(other_key)

    revoke = client.delete(
        f"/api/v1/account/api-keys/{other_key.id}", follow_redirects=False,
    )
    assert revoke.status_code == 404, "must not let user revoke another user's key"
