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


# ── GET /api/v1/jobs/{id}/sheets ──────────────────────────────────────────────

def test_sheets_not_found(client, user, api_key_pair):
    full_key, _ = api_key_pair
    resp = client.get(
        "/api/v1/jobs/99999/sheets",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 404


def test_sheets_empty_when_no_tiles(client, db_session, user, api_key_pair):
    """Job with no tile directory returns sheet_count=0, sheets=[]."""
    job = models.Job(
        user_id=user.id, pid_no="T-100", status="done",
        original_filename="x.pdf", stored_filename="y.pdf",
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/sheets",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job.id
    assert data["sheet_count"] == 0
    assert data["sheets"] == []


def test_sheets_access_denied_for_other_user(client, db_session, user, api_key_pair):
    """A user cannot list sheets for someone else's job (super_admin can)."""
    other = models.User(
        username="other_one", password_hash="x", credits_remaining=5, is_active=True,
    )
    db_session.add(other)
    db_session.commit()
    job = models.Job(
        user_id=other.id, pid_no="T-101", status="done",
        original_filename="x.pdf", stored_filename="y.pdf",
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/sheets",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 403


# ── GET /api/v1/jobs/{id}/detections ──────────────────────────────────────────

def test_detections_empty_when_no_gpu_callback(client, db_session, user, api_key_pair):
    job = models.Job(
        user_id=user.id, pid_no="T-200", status="done", valve_count=3,
        original_filename="x.pdf", stored_filename="y.pdf",
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valve_count"] == 3
    assert data["detections"] == []
    assert data["detection_count"] == 0
    assert data["valves"] == []


def test_detections_parses_gpu_callback_json(client, db_session, user, api_key_pair):
    import json as _json
    job = models.Job(
        user_id=user.id, pid_no="T-201", status="done", valve_count=2,
        original_filename="x.pdf", stored_filename="y.pdf",
        gpu_detections=_json.dumps([
            {"bbox": [10, 20, 30, 40], "label": "PT-101", "confidence": 0.91},
            {"bbox": [50, 60, 70, 80], "label": "FT-201", "confidence": 0.85},
        ]),
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_count"] == 2
    assert data["detections"][0]["label"] == "PT-101"
    assert data["detections"][0]["bbox"] == [10, 20, 30, 40]


def test_detections_survives_malformed_gpu_json(client, db_session, user, api_key_pair):
    job = models.Job(
        user_id=user.id, pid_no="T-202", status="done",
        original_filename="x.pdf", stored_filename="y.pdf",
        gpu_detections="not json at all",
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["detections"] == []


def test_detections_attach_entity_id_from_canonical(client, db_session, user, api_key_pair, tmp_path):
    """D1.5: GET /detections matches detection.label → canonical.tag and attaches entity_id.

    Detections whose label has no matching canonical entity get entity_id=None
    (informational-only — not editable via the override API).
    """
    import json as _json
    from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
    import uuid as _uuid

    # Build a real canonical.json on disk alongside output_csv_path.
    out_dir = tmp_path / "job_dir"
    out_dir.mkdir()
    csv_path = out_dir / "valve_list.csv"
    csv_path.write_text("pid_no,category\nP-1,GLOBE\n")  # contents don't matter for this test
    canonical_path = out_dir / "canonical.json"

    entity1_id = _uuid.uuid5(_uuid.NAMESPACE_DNS, "pt-101")
    entity2_id = _uuid.uuid5(_uuid.NAMESPACE_DNS, "ft-201")
    canonical = JobCanonical(
        job_id=9001,
        canonical_schema_version="1.0.0",
        customer_template_slug="default",
        entities=[
            CanonicalEntity(
                entity_id=entity1_id, entity_class="instrument",
                sub_class="PT", tag="PT-101",
                pid_number="T-301", sheet_number=1,
                bbox=(0.0, 0.0, 0.0, 0.0), fields={}, vendor_match=None,
            ),
            CanonicalEntity(
                entity_id=entity2_id, entity_class="instrument",
                sub_class="FT", tag="FT-201",
                pid_number="T-301", sheet_number=1,
                bbox=(0.0, 0.0, 0.0, 0.0), fields={}, vendor_match=None,
            ),
        ],
    )
    canonical_path.write_text(canonical.model_dump_json())

    job = models.Job(
        user_id=user.id, pid_no="T-301", status="done", valve_count=0,
        original_filename="x.pdf", stored_filename="y.pdf",
        output_csv_path=str(csv_path),
        gpu_detections=_json.dumps([
            {"bbox": [10, 20, 30, 40], "label": "PT-101"},   # matches entity1
            {"bbox": [50, 60, 70, 80], "label": "FT-201"},   # matches entity2
            {"bbox": [90, 100, 110, 120], "label": "valve_bf"},  # no canonical match
        ]),
    )
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    dets = resp.json()["detections"]
    assert dets[0]["entity_id"] == str(entity1_id)
    assert dets[0]["entity_class"] == "instrument"
    assert dets[1]["entity_id"] == str(entity2_id)
    assert dets[2]["entity_id"] is None  # symbol-class label, no tag match


def test_detections_includes_valve_rows(client, db_session, user, api_key_pair):
    job = models.Job(
        user_id=user.id, pid_no="T-203", status="done", valve_count=1,
        original_filename="x.pdf", stored_filename="y.pdf",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    db_session.add(models.ValveRow(
        job_id=job.id, pid_no="T-203", category="GLOBE",
        size='4"', line="P-12-101", qty=1,
    ))
    db_session.commit()

    full_key, _ = api_key_pair
    resp = client.get(
        f"/api/v1/jobs/{job.id}/detections",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["valves"]) == 1
    assert data["valves"][0]["category"] == "GLOBE"
    assert data["valves"][0]["line"] == "P-12-101"


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


def test_upload_html_spoofing_pdf_extension_rejected(client, user, api_key_pair):
    """A file with .pdf extension but HTML content must be rejected by the
    %PDF- magic-byte check. Without this, PyMuPDF lenient-parses the HTML as
    a blank 1-page PDF and produces a useless 'done' job with empty tiles
    — exactly what bit us when Playwright accidentally uploaded the Vite SPA
    catch-all's index.html instead of a real PDF."""
    full_key, _ = api_key_pair
    html_payload = b"<!doctype html><html><body>not a pdf</body></html>"
    resp = client.post(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {full_key}"},
        files={"file": ("test.pdf", io.BytesIO(html_payload), "application/pdf")},
    )
    assert resp.status_code == 422
    assert "%PDF-" in resp.json()["detail"]


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
