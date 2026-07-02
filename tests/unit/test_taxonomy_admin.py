"""Tests for the Phase 4b taxonomy/label-triage admin API.

Covers GET /api/v1/admin/taxonomy, GET /api/v1/admin/label-triage, and
POST /api/v1/admin/label-triage/{id}/classify.

The approve path mutates the on-disk webapp/taxonomy.json (it's the source of
truth). The `restore_taxonomy_file` fixture snapshots the file's bytes before
each test and restores them after, and resets the in-process taxonomy cache, so
the repo file is never left mutated.
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

from webapp import taxonomy as taxonomy_module  # noqa: E402
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


@pytest.fixture(autouse=True)
def restore_taxonomy_file():
    """Snapshot taxonomy.json bytes + reset cache; restore after the test."""
    path = taxonomy_module._TAXONOMY_PATH
    original = path.read_bytes()
    taxonomy_module._cache = None
    yield
    path.write_bytes(original)
    taxonomy_module._cache = None


def _login(client, user):
    token = create_access_token({"sub": user.username})
    client.cookies.set("access_token", token)


def _make_triage(db, label_value="WeirdValve", status="pending", source="ls"):
    t = models.LabelTriage(label_value=label_value, source=source, status=status)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── GET /taxonomy ────────────────────────────────────────────────────────────


def test_get_taxonomy_shape(client, admin_user):
    _login(client, admin_user)
    resp = client.get("/api/v1/admin/taxonomy")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "classes" in data
    assert "yolo_routing" in data
    assert isinstance(data["classes"], list) and len(data["classes"]) > 0
    cls = data["classes"][0]
    for key in ("entity_class", "sub_class", "display_name", "color", "glyph_kind"):
        assert key in cls


def test_get_taxonomy_forbidden_for_non_admin(client, regular_user):
    _login(client, regular_user)
    resp = client.get("/api/v1/admin/taxonomy")
    assert resp.status_code == 403


def test_get_taxonomy_unauthenticated(client):
    resp = client.get("/api/v1/admin/taxonomy", follow_redirects=False)
    assert resp.status_code in (303, 401)


# ── GET /label-triage ────────────────────────────────────────────────────────


def test_list_triage_filters_by_status(client, db_session, admin_user):
    _login(client, admin_user)
    _make_triage(db_session, label_value="A", status="pending")
    _make_triage(db_session, label_value="B", status="approved")
    _make_triage(db_session, label_value="C", status="pending")

    resp = client.get("/api/v1/admin/label-triage?status=pending")
    assert resp.status_code == 200, resp.text
    labels = {i["label_value"] for i in resp.json()["items"]}
    assert labels == {"A", "C"}

    resp_all = client.get("/api/v1/admin/label-triage?status=all")
    assert resp_all.status_code == 200
    assert len(resp_all.json()["items"]) == 3


def test_list_triage_forbidden_for_non_admin(client, regular_user):
    _login(client, regular_user)
    resp = client.get("/api/v1/admin/label-triage")
    assert resp.status_code == 403


# ── POST classify ────────────────────────────────────────────────────────────


def test_classify_approve_adds_to_taxonomy_and_db(client, db_session, admin_user):
    _login(client, admin_user)
    row = _make_triage(db_session, label_value="SpecialValve", status="pending")

    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={
            "action": "approve",
            "entity_class": "valve",
            "sub_class": "ZZ",
            "display_name": "Special Valve",
            "color": "#ABCDEF",
            "glyph_kind": "valve_gen",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "approved"
    assert body["assigned_entity_class"] == "valve"
    assert body["assigned_sub_class"] == "ZZ"
    assert body["decided_by_user_id"] == admin_user.id
    assert body["decided_at"] is not None

    # Appended to taxonomy.json on disk.
    data = json.loads(taxonomy_module._TAXONOMY_PATH.read_text())
    match = [
        c for c in data["classes"]
        if c.get("entity_class") == "valve" and c.get("sub_class") == "ZZ"
    ]
    assert len(match) == 1
    assert match[0]["display_name"] == "Special Valve"
    assert match[0]["color"] == "#ABCDEF"
    assert match[0]["yolo_label"] is None

    # Upserted into the LabelTaxonomy read-index.
    tax_row = (
        db_session.query(models.LabelTaxonomy)
        .filter_by(entity_class="valve", sub_class="ZZ")
        .first()
    )
    assert tax_row is not None
    assert tax_row.display_name == "Special Valve"


def test_classify_approve_rejects_bad_entity_class(client, db_session, admin_user):
    _login(client, admin_user)
    row = _make_triage(db_session, label_value="Foo", status="pending")
    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={"action": "approve", "entity_class": "widget"},
    )
    assert resp.status_code == 400
    db_session.refresh(row)
    assert row.status == "pending"  # unchanged


def test_classify_ignore_sets_status_only(client, db_session, admin_user):
    _login(client, admin_user)
    row = _make_triage(db_session, label_value="Junk", status="pending")
    before = json.loads(taxonomy_module._TAXONOMY_PATH.read_text())
    n_before = len(before["classes"])

    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={"action": "ignore"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ignored"
    assert body["decided_by_user_id"] == admin_user.id
    assert body["decided_at"] is not None

    # Taxonomy file untouched.
    after = json.loads(taxonomy_module._TAXONOMY_PATH.read_text())
    assert len(after["classes"]) == n_before


def test_classify_reject_sets_status(client, db_session, admin_user):
    _login(client, admin_user)
    row = _make_triage(db_session, label_value="Bad", status="pending")
    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={"action": "reject"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def test_classify_invalid_action(client, db_session, admin_user):
    _login(client, admin_user)
    row = _make_triage(db_session, label_value="X", status="pending")
    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={"action": "frobnicate"},
    )
    assert resp.status_code == 400


def test_classify_missing_row_404(client, db_session, admin_user):
    _login(client, admin_user)
    resp = client.post(
        "/api/v1/admin/label-triage/9999/classify",
        json={"action": "ignore"},
    )
    assert resp.status_code == 404


def test_classify_forbidden_for_non_admin(client, db_session, regular_user):
    _login(client, regular_user)
    resp = client.post(
        "/api/v1/admin/label-triage/1/classify",
        json={"action": "ignore"},
    )
    assert resp.status_code == 403
