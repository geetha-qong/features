"""Regression tests for the /account/api-keys flow.

Locks in the security fix for the redirect-URL-leak vulnerability: the POST
handler must render the new key directly in the response body, NOT redirect
with the key in a URL query string. URL params land in nginx access logs,
browser history, and Referer headers; the response body does not.
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


def test_post_create_renders_key_in_body_not_redirect(client, authed_user, db_session):
    """SECURITY: the new key must appear in the HTML response body, never in a
    Location: header or URL query string. This locks in the fix for the
    redirect-URL-leak vulnerability."""
    resp = client.post(
        "/account/api-keys/create",
        data={"name": "ci"},
        follow_redirects=False,
    )
    # MUST be a direct render, NOT a 303 redirect
    assert resp.status_code == 200, f"expected 200 OK, got {resp.status_code}"
    assert "location" not in {h.lower() for h in resp.headers}, (
        "POST handler must not set Location header — that would leak the key "
        "into nginx access logs and browser history."
    )

    # The response body must contain the freshly minted key
    body = resp.text
    assert "qk_" in body, "expected the new key prefix in the rendered HTML"

    # And the key must actually verify against the stored hash
    key_row = (
        db_session.query(models.ApiKey)
        .filter(models.ApiKey.user_id == authed_user.id)
        .order_by(models.ApiKey.created_at.desc())
        .first()
    )
    assert key_row is not None
    # Extract the qk_<32hex> token from the body
    import re
    matches = re.findall(r"qk_[0-9a-f]{32}", body)
    assert matches, "expected at least one qk_<32hex> token in body"
    full_key = matches[0]
    assert pwd_context.verify(full_key, key_row.key_hash)


def test_get_with_new_key_query_param_does_not_render(client, authed_user):
    """SECURITY: even if an attacker crafts a URL with ?new_key=qk_..., the
    template must NOT echo that value back. The previous implementation read
    `request.query_params.get('new_key')` and rendered it — this test locks
    in that we now read from template context only."""
    resp = client.get(
        "/account/api-keys?new_key=qk_attacker_supplied_value",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "qk_attacker_supplied_value" not in resp.text, (
        "URL query param ?new_key=... must NOT be rendered into the HTML. "
        "Only the POST handler may pass new_key via template context."
    )
    # The success-banner copy must NOT appear for a plain GET
    assert "Key created!" not in resp.text
