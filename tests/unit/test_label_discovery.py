"""Phase 4d: unknown-label discovery hook on the detections endpoint.

When `GET /api/v1/jobs/{id}/detections` enriches gpu_detections, any YOLO label
with no taxonomy match (and that isn't an intentional arrow_/connector_ direction
marker) gets a `LabelTriage` row upserted (source='detection', status='pending',
deduped on label_value). Known and direction labels file no row.

Uses TestClient with an in-memory SQLite DB — same pattern as test_api_v1.py.
"""
import json as _json
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp.database import Base, get_db
from webapp import models
from webapp import taxonomy as taxonomy_module
from webapp.auth import create_access_token, pwd_context
from webapp.main import app


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
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


@pytest.fixture()
def user(db_session):
    u = models.User(
        username="discovery_tester",
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
    full_key = "qk_" + secrets.token_hex(16)
    k = models.ApiKey(
        user_id=user.id,
        name="test-key",
        key_prefix=full_key[:8],
        key_hash=pwd_context.hash(full_key),
    )
    db_session.add(k)
    db_session.commit()
    return full_key, k


def _make_job(db_session, user, detections):
    job = models.Job(
        user_id=user.id,
        pid_no="T-4D",
        status="done",
        original_filename="x.pdf",
        stored_filename="y.pdf",
        gpu_detections=_json.dumps(detections),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _fetch(client, job_id, full_key):
    return client.get(
        f"/api/v1/jobs/{job_id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )


# ── Tests ────────────────────────────────────────────────────────────────────

def test_unknown_label_creates_triage_row(client, db_session, user, api_key_pair):
    full_key, _ = api_key_pair
    job = _make_job(
        db_session, user,
        [{"bbox": [1, 2, 3, 4], "label": "totally_new_symbol", "confidence": 0.9}],
    )

    resp = _fetch(client, job.id, full_key)
    assert resp.status_code == 200

    rows = db_session.query(models.LabelTriage).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.label_value == "totally_new_symbol"
    assert row.source == "detection"
    assert row.status == "pending"


def test_arrow_label_creates_no_triage_row(client, db_session, user, api_key_pair):
    full_key, _ = api_key_pair
    job = _make_job(
        db_session, user,
        [
            {"bbox": [1, 2, 3, 4], "label": "arrow_up", "confidence": 0.9},
            {"bbox": [5, 6, 7, 8], "label": "connector_in", "confidence": 0.8},
        ],
    )

    resp = _fetch(client, job.id, full_key)
    assert resp.status_code == 200

    assert db_session.query(models.LabelTriage).count() == 0


def test_known_label_creates_no_triage_row(client, db_session, user, api_key_pair):
    full_key, _ = api_key_pair
    # valve_bv is a known YOLO class routed to (valve, BV); inst_field → instrument.
    job = _make_job(
        db_session, user,
        [
            {"bbox": [1, 2, 3, 4], "label": "valve_bv", "confidence": 0.9},
            {"bbox": [5, 6, 7, 8], "label": "inst_field", "confidence": 0.8},
        ],
    )

    resp = _fetch(client, job.id, full_key)
    assert resp.status_code == 200

    assert db_session.query(models.LabelTriage).count() == 0


def test_rediscovery_does_not_duplicate(client, db_session, user, api_key_pair):
    full_key, _ = api_key_pair
    job = _make_job(
        db_session, user,
        [{"bbox": [1, 2, 3, 4], "label": "mystery_glyph", "confidence": 0.9}],
    )

    assert _fetch(client, job.id, full_key).status_code == 200
    assert _fetch(client, job.id, full_key).status_code == 200

    rows = db_session.query(models.LabelTriage).filter(
        models.LabelTriage.label_value == "mystery_glyph"
    ).all()
    assert len(rows) == 1


# ── End-to-end: discover → classify → taxonomy (Phase-4 loop) ──────────────────

@pytest.fixture()
def admin_user(db_session):
    u = models.User(
        username="triage_admin",
        password_hash=pwd_context.hash("x"),
        role="super_admin",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def restore_taxonomy_file():
    """Snapshot taxonomy.json + reset cache; restore after (classify mutates it)."""
    path = taxonomy_module._TAXONOMY_PATH
    original = path.read_bytes()
    taxonomy_module._cache = None
    yield
    path.write_bytes(original)
    taxonomy_module._cache = None


def test_discover_then_classify_closes_the_loop(
    client, db_session, user, api_key_pair, admin_user, restore_taxonomy_file
):
    """The full Phase-4 loop on a SINGLE row: an unknown label discovered on the
    detections endpoint becomes a pending triage row, which an admin then
    classifies — promoting it to a real taxonomy class queryable from
    taxonomy.json and the LabelTaxonomy read-index. (The per-step behaviours are
    covered above and in test_taxonomy_admin.py; this proves they are wired
    together.)"""
    full_key, _ = api_key_pair

    # 1) Discover: an unknown label files a pending triage row (source=detection).
    job = _make_job(
        db_session, user,
        [{"bbox": [1, 2, 3, 4], "label": "mystery_glyph_e2e", "confidence": 0.95}],
    )
    assert _fetch(client, job.id, full_key).status_code == 200
    row = (
        db_session.query(models.LabelTriage)
        .filter(models.LabelTriage.label_value == "mystery_glyph_e2e")
        .one()
    )
    assert row.status == "pending"
    assert row.source == "detection"

    # 2) Classify (admin): approve THAT row → promote to a real taxonomy class.
    client.cookies.set("access_token", create_access_token({"sub": admin_user.username}))
    resp = client.post(
        f"/api/v1/admin/label-triage/{row.id}/classify",
        json={
            "action": "approve",
            "entity_class": "valve",
            "sub_class": "E2E",
            "display_name": "E2E Test Valve",
            "color": "#0A0B0C",
            "glyph_kind": "valve_gen",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    # 3) The discovered+classified label is now a real, queryable taxonomy class.
    db_session.refresh(row)
    assert row.status == "approved"
    assert row.assigned_entity_class == "valve"
    assert row.assigned_sub_class == "E2E"

    taxonomy_module._cache = None  # force a fresh read of the mutated file
    tax = taxonomy_module.load_taxonomy()
    match = [
        c for c in tax["classes"]
        if c.get("entity_class") == "valve" and c.get("sub_class") == "E2E"
    ]
    assert len(match) == 1
    assert match[0]["display_name"] == "E2E Test Valve"

    tax_row = (
        db_session.query(models.LabelTaxonomy)
        .filter_by(entity_class="valve", sub_class="E2E")
        .first()
    )
    assert tax_row is not None
    assert tax_row.display_name == "E2E Test Valve"
