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
from webapp.auth import pwd_context
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
