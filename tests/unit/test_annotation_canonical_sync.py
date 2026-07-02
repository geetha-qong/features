"""A tagged Mark-Symbol annotation must flow into canonical.json (so it shows in
exports / DatasheetDrawer / Bulk Review); an untagged or rejected/deleted one
must NOT (product rule, 2026-06-17).

The deliverable path reads canonical.json (file) via load_canonical_with_overrides,
so these tests assert directly against the on-disk canonical.json.
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

from webapp import models
from webapp.auth import get_current_user, pwd_context
from webapp.database import Base, get_db
from webapp.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    gc_table = Base.metadata.tables.get("graph_corrections")
    if gc_table is not None:
        dupes = [ix for ix in gc_table.indexes if ix.name == "ix_graph_corrections_line_type"]
        for ix in dupes[1:]:
            gc_table.indexes.discard(ix)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(username="sync_u", password_hash=pwd_context.hash("x"),
                    credits_remaining=20, is_active=True, role="user")
    db_session.add(u); db_session.commit(); db_session.refresh(u)
    return u


@pytest.fixture()
def client(db_session, user):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


@pytest.fixture()
def job_with_canonical(db_session, user, tmp_path):
    """A done job whose output dir has an (empty) canonical.json on disk."""
    csv = tmp_path / "valve_list.csv"
    csv.write_text("x")
    (tmp_path / "canonical.json").write_text(json.dumps({
        "version": "1.0", "job_id": 1, "customer_template_slug": "default", "entities": [],
    }))
    job = models.Job(user_id=user.id, pid_no="T-SYNC", status="done",
                     original_filename="t.pdf", stored_filename="t.pdf",
                     output_csv_path=str(csv))
    db_session.add(job); db_session.commit(); db_session.refresh(job)
    return job, tmp_path / "canonical.json"


def _canon_entities(path):
    return json.loads(path.read_text()).get("entities", [])


def _create_mark(client, job_id):
    r = client.post(f"/api/v1/jobs/{job_id}/annotations", json={
        "entity_class": "valve", "sub_class": "BV",
        "bbox": [10.0, 20.0, 30.0, 40.0], "sheet_number": 1,
        "linked_detection_index": None,
    })
    assert r.status_code == 201, r.text
    return r.json()["entity_id"]


def test_untagged_mark_not_in_canonical(client, job_with_canonical):
    job, canon = job_with_canonical
    _create_mark(client, job.id)
    # Fresh mark has no tag → must NOT appear in canonical (training-only).
    assert _canon_entities(canon) == []


def test_patch_tag_adds_to_canonical(client, job_with_canonical):
    job, canon = job_with_canonical
    eid = _create_mark(client, job.id)
    r = client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}",
                     json={"tag": "62-BV-9001", "fields_json": {"size": "8\""}})
    assert r.status_code == 200, r.text
    ents = _canon_entities(canon)
    assert len(ents) == 1
    e = ents[0]
    assert e["entity_id"] == eid
    assert e["tag"] == "62-BV-9001"
    assert e["entity_class"] == "valve" and e["sub_class"] == "BV"
    assert e["fields"].get("size") == "8\""


def test_reject_removes_from_canonical(client, job_with_canonical):
    job, canon = job_with_canonical
    eid = _create_mark(client, job.id)
    client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}", json={"tag": "62-BV-9002"})
    assert len(_canon_entities(canon)) == 1
    r = client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}", json={"status": "user_rejected"})
    assert r.status_code == 200, r.text
    assert _canon_entities(canon) == []  # rejected → gone from exports


def test_delete_removes_from_canonical(client, job_with_canonical):
    job, canon = job_with_canonical
    eid = _create_mark(client, job.id)
    client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}", json={"tag": "62-BV-9003"})
    assert len(_canon_entities(canon)) == 1
    r = client.delete(f"/api/v1/jobs/{job.id}/annotations/{eid}")
    assert r.status_code == 204
    assert _canon_entities(canon) == []  # deleted → gone from exports


def test_clearing_tag_removes_from_canonical(client, job_with_canonical):
    job, canon = job_with_canonical
    eid = _create_mark(client, job.id)
    client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}", json={"tag": "62-BV-9004"})
    assert len(_canon_entities(canon)) == 1
    # tag cleared → no longer exportable → removed
    r = client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}", json={"tag": ""})
    assert r.status_code == 200, r.text
    assert _canon_entities(canon) == []
