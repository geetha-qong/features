"""Unit tests for Studio node corrections (design 2026-06-28).

Covers three backend surfaces:
  - webapp/deliverables/overrides.py::load_canonical_with_overrides
      (`__rejected__` drops the entity; flag never applied as a field;
       normal field overrides on non-rejected entities still apply)
  - webapp/routers/graph.py::get_job_graph read-merge
      (UserAnnotation rows surface as source="user" nodes; rejected
       entity_id flagged rejected:true; edges with a rejected endpoint
       omitted; missing canonical_graph.json → annotation-only nodes)
  - reject/undo endpoints
      (POST creates override idempotently; DELETE removes it;
       DELETE-when-absent → 404; unknown job → 404)

In-memory SQLite, router mounted on a local FastAPI app (mirrors
test_graph_router_and_sync.py).
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models
from webapp.auth import get_current_user
from webapp.database import Base, get_db
from webapp.routers.graph import router as graph_router
from webapp.deliverables.overrides import load_canonical_with_overrides


# ── shared fixtures (local, mirrors test_graph_router_and_sync.py) ────────────

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(username="g", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user, tmp_path):
    csv = tmp_path / "valve_list.csv"
    csv.write_text("x")
    j = models.Job(
        user_id=user.id, original_filename="t.pdf", stored_filename="t.pdf",
        pid_no="T-1", status="done", output_csv_path=str(csv),
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


@pytest.fixture()
def client(db_session, user):
    app = FastAPI()
    app.include_router(graph_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── canonical / graph file helpers ────────────────────────────────────────────

EID_A = "11111111111111111111111111111111"   # uuid4().hex form
EID_B = "22222222222222222222222222222222"


def _canonical_dict():
    return {
        "job_id": 1,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [
            {
                "entity_id": str(uuid.UUID(EID_A)),
                "entity_class": "valve",
                "sub_class": "BV",
                "tag": "BV-1",
                "pid_number": "T-1",
                "sheet_number": 1,
                "bbox": [10, 10, 30, 30],
                "fields": {},
            },
            {
                "entity_id": str(uuid.UUID(EID_B)),
                "entity_class": "instrument",
                "sub_class": "FLOW TRANSMITTER",
                "tag": "FT-1",
                "pid_number": "T-1",
                "sheet_number": 1,
                "bbox": [100, 100, 130, 130],
                "fields": {},
            },
        ],
    }


def _write_canonical(job, data=None):
    job_dir = os.path.dirname(job.output_csv_path)
    with open(os.path.join(job_dir, "canonical.json"), "w") as f:
        json.dump(data or _canonical_dict(), f)


def _graph_dict(job_id, entity_a=EID_A, entity_b=EID_B):
    return {
        "version": "0.1",
        "job_id": job_id,
        "page": 1,
        "stats": {"nodes": 2, "edges": 1, "fallback_used": False},
        "nodes": [
            {"id": "n_000", "entity_id": str(uuid.UUID(entity_a)), "tag": "BV-1",
             "class": "valve_bv", "bbox": [10, 10, 30, 30],
             "tile": "tile_p0_r0_c0.png", "confidence": 0.9},
            {"id": "n_001", "entity_id": str(uuid.UUID(entity_b)), "tag": "FT-1",
             "class": "instrument", "bbox": [100, 100, 130, 130],
             "tile": "tile_p0_r0_c0.png", "confidence": 0.8},
        ],
        "edges": [
            {"id": "e_000", "source": str(uuid.UUID(entity_a)),
             "target": str(uuid.UUID(entity_b)),
             "polyline": [[20, 20], [115, 115]], "method": "opencv",
             "confidence": 0.7,
             "source_entity_id": str(uuid.UUID(entity_a)),
             "target_entity_id": str(uuid.UUID(entity_b))},
        ],
        "floating_nodes": [],
        "orphan_lines": [],
    }


def _write_graph(job, data=None):
    job_dir = os.path.dirname(job.output_csv_path)
    with open(os.path.join(job_dir, "canonical_graph.json"), "w") as f:
        json.dump(data or _graph_dict(job.id), f)


def _reject_override(job, entity_id, user_id, value=True):
    return models.EntityOverride(
        job_id=job.id, entity_id=str(uuid.UUID(entity_id)),
        field_name="__rejected__", new_value=value, edited_by=user_id,
    )


# ── overrides.py ──────────────────────────────────────────────────────────────

def test_rejected_entity_dropped_from_canonical(db_session, job, user):
    _write_canonical(job)
    db_session.add(_reject_override(job, EID_A, user.id))
    db_session.commit()

    merged = load_canonical_with_overrides(job.output_csv_path, job.id, db_session)
    eids = {str(e.entity_id) for e in merged.entities}
    assert str(uuid.UUID(EID_A)) not in eids
    assert str(uuid.UUID(EID_B)) in eids


def test_rejected_flag_not_applied_as_field(db_session, job, user):
    """`__rejected__` is a control flag — never a normal entity attribute."""
    _write_canonical(job)
    # Reject entity B with new_value=false → entity stays, flag must NOT
    # become an attribute named __rejected__.
    db_session.add(_reject_override(job, EID_B, user.id, value=False))
    db_session.commit()

    merged = load_canonical_with_overrides(job.output_csv_path, job.id, db_session)
    eids = {str(e.entity_id) for e in merged.entities}
    # falsy __rejected__ keeps the entity
    assert str(uuid.UUID(EID_B)) in eids
    ent_b = next(e for e in merged.entities if str(e.entity_id) == str(uuid.UUID(EID_B)))
    assert not hasattr(ent_b, "__rejected__")
    assert "__rejected__" not in ent_b.model_dump()


def test_normal_override_still_applies_on_non_rejected(db_session, job, user):
    _write_canonical(job)
    db_session.add(models.EntityOverride(
        job_id=job.id, entity_id=str(uuid.UUID(EID_A)),
        field_name="tag", new_value="BV-RENAMED", edited_by=user.id,
    ))
    db_session.commit()

    merged = load_canonical_with_overrides(job.output_csv_path, job.id, db_session)
    ent_a = next(e for e in merged.entities if str(e.entity_id) == str(uuid.UUID(EID_A)))
    assert ent_a.tag == "BV-RENAMED"


# ── GET /graph read-merge ─────────────────────────────────────────────────────

def test_annotation_nodes_surface_as_user_source(client, db_session, job, user):
    _write_canonical(job)
    _write_graph(job)
    ua_eid = uuid.uuid4().hex
    db_session.add(models.UserAnnotation(
        job_id=job.id, entity_id=ua_eid, user_id=user.id, source="user",
        status="user_added", entity_class="valve", sub_class="GV",
        bbox=[200, 200, 220, 220], sheet_number=1, placeholder_tag="USER-GV-0001",
    ))
    db_session.commit()

    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    by_eid = {n["entity_id"]: n for n in nodes}
    # auto nodes carry source="auto"
    assert by_eid[str(uuid.UUID(EID_A))]["source"] == "auto"
    # the annotation surfaced as a source="user" node
    assert ua_eid in by_eid
    un = by_eid[ua_eid]
    assert un["source"] == "user"
    assert un["id"] == ua_eid and un["entity_id"] == ua_eid
    assert un["tag"] == "USER-GV-0001"   # placeholder used when no tag
    assert un["class"] == "GV"
    assert un["confidence"] == 1.0
    assert un["rejected"] is False


def test_rejected_entity_flagged_and_edges_omitted(client, db_session, job, user):
    _write_canonical(job)
    _write_graph(job)
    db_session.add(_reject_override(job, EID_A, user.id))
    db_session.commit()

    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    body = r.json()
    by_eid = {n["entity_id"]: n for n in body["nodes"]}
    # rejected node is RETURNED (not dropped) so UI can ghost/restore it
    assert by_eid[str(uuid.UUID(EID_A))]["rejected"] is True
    assert by_eid[str(uuid.UUID(EID_B))]["rejected"] is False
    # the edge touching the rejected node is omitted
    assert body["edges"] == []


def test_missing_graph_file_returns_annotation_only_nodes(client, db_session, job, user):
    # No canonical_graph.json on disk, but a UserAnnotation exists.
    ua_eid = uuid.uuid4().hex
    db_session.add(models.UserAnnotation(
        job_id=job.id, entity_id=ua_eid, user_id=user.id, source="user",
        status="user_added", entity_class="valve", sub_class="GV",
        bbox=[200, 200, 220, 220], sheet_number=1, placeholder_tag="USER-GV-0001",
    ))
    db_session.commit()

    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    body = r.json()
    eids = [n["entity_id"] for n in body["nodes"]]
    assert eids == [ua_eid]
    assert body["nodes"][0]["source"] == "user"
    assert body["edges"] == []


# ── reject / undo endpoints ───────────────────────────────────────────────────

def test_reject_creates_override_idempotent(client, db_session, job):
    eid = str(uuid.UUID(EID_A))
    r1 = client.post(f"/api/v1/jobs/{job.id}/nodes/{eid}/reject")
    assert r1.status_code == 200
    assert r1.json() == {"entity_id": eid, "rejected": True}

    rows = db_session.query(models.EntityOverride).filter_by(
        job_id=job.id, entity_id=eid, field_name="__rejected__").all()
    assert len(rows) == 1
    assert rows[0].new_value in (True, "true", 1)

    # idempotent re-reject
    r2 = client.post(f"/api/v1/jobs/{job.id}/nodes/{eid}/reject")
    assert r2.status_code == 200
    db_session.expire_all()
    rows = db_session.query(models.EntityOverride).filter_by(
        job_id=job.id, entity_id=eid, field_name="__rejected__").all()
    assert len(rows) == 1


def test_undo_reject_deletes_override(client, db_session, job):
    eid = str(uuid.UUID(EID_A))
    client.post(f"/api/v1/jobs/{job.id}/nodes/{eid}/reject")
    r = client.delete(f"/api/v1/jobs/{job.id}/nodes/{eid}/reject")
    assert r.status_code == 204
    assert r.content == b""
    db_session.expire_all()
    rows = db_session.query(models.EntityOverride).filter_by(
        job_id=job.id, entity_id=eid, field_name="__rejected__").all()
    assert rows == []


def test_undo_reject_when_absent_404(client, job):
    eid = str(uuid.UUID(EID_A))
    r = client.delete(f"/api/v1/jobs/{job.id}/nodes/{eid}/reject")
    assert r.status_code == 404


def test_reject_unknown_job_404(client):
    eid = str(uuid.UUID(EID_A))
    r = client.post(f"/api/v1/jobs/999999/nodes/{eid}/reject")
    assert r.status_code == 404


# ── tag-override read-merge (graph view must reflect edited tags) ──────────────

def test_graph_reflects_tag_override(client, db_session, job, user):
    """A user tag edit (entity_overrides field_name="tag") must show on the graph
    node — the graph file holds the original OCR tag; without the merge the graph
    reverts the edit on refresh even though it's persisted (real bug, job 38)."""
    _write_canonical(job)
    _write_graph(job)
    db_session.add(models.EntityOverride(
        job_id=job.id, entity_id=str(uuid.UUID(EID_A)),
        field_name="tag", new_value="61-BV-NEW", edited_by=user.id,
    ))
    db_session.commit()

    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert nodes["n_000"]["tag"] == "61-BV-NEW"   # edited tag applied
    assert nodes["n_001"]["tag"] == "FT-1"        # un-edited node unchanged
