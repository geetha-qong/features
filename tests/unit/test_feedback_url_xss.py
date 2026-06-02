"""Regression tests for the POST /api/v1/feedback page_url XSS fix.

Locks in the security fix that scrubs non-http(s) URLs at submission time
(and as defense-in-depth at render time in the admin/feedback SPA). Without
these, an unauthenticated attacker could submit `page_url=javascript:...`
and execute JS in the admin origin when the admin clicks the link in the
Feedback Inbox — escalating to super_admin via cookie-auth admin endpoints
(no CSRF token exists on those POSTs).

Migrated 2026-06-02 from the legacy Jinja /feedback form (deleted with the
Jinja->SPA sweep, FEATURES #19). The endpoint is now JSON-only.
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


def _submit(client, page_url):
    return client.post(
        "/api/v1/feedback",
        json={
            "category": "bug",
            "subject": "test",
            "message": "test",
            "page_url": page_url,
        },
        follow_redirects=False,
    )


@pytest.mark.parametrize("hostile", [
    "javascript:alert(1)",
    "JavaScript:fetch('/admin/users/create',{method:'POST',credentials:'include'})",
    "  javascript:alert(1)  ",            # leading whitespace; .strip() should not let scheme through
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "ftp://attacker.example/path",
    "//attacker.example/path",            # protocol-relative — netloc set but no scheme
    "javascript://attacker.example/?",    # tricky: parses as http-ish but scheme is javascript
])
def test_hostile_page_url_is_dropped(client, db_session, hostile):
    """SECURITY: any non-http(s) scheme must NOT be persisted to the DB."""
    resp = _submit(client, hostile)
    assert resp.status_code == 201
    item = db_session.query(models.UserFeedback).one()
    assert item.page_url is None, (
        f"hostile URL {hostile!r} was stored as {item.page_url!r}; "
        "it must be dropped at submission time"
    )


@pytest.mark.parametrize("ok", [
    "http://example.com/path",
    "https://example.com/path?q=1",
    "https://dev.qongsystems.com/jobs/42",
])
def test_legitimate_page_url_is_kept(client, db_session, ok):
    resp = _submit(client, ok)
    assert resp.status_code == 201
    item = db_session.query(models.UserFeedback).one()
    assert item.page_url == ok


def test_empty_page_url_is_none(client, db_session):
    resp = _submit(client, "")
    assert resp.status_code == 201
    item = db_session.query(models.UserFeedback).one()
    assert item.page_url is None
