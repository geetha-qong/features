"""E2E: adopting a YOLO orphan node via Mark Symbol.

When a user marks a symbol linked to an orphan detection (entity_id=None in
canonical_graph.json), the resulting UserAnnotation should:

  1. POST /api/v1/jobs/{id}/annotations → 201, produces entity_id
  2. PATCH /api/v1/jobs/{id}/annotations/{entity_id} → 200, sets tag
  3. load_canonical_with_overrides sees the new entity_id in canon.entities
  4. GET /api/v1/jobs/{id}/graph deduplicates the orphan node (n_1 is GONE,
     the annotation node is present, and the graph has exactly 1 node)
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


# ── Fixtures (verbatim from test_annotation_canonical_sync.py) ─────────────────

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


# ── Job fixture with canonical + graph files ───────────────────────────────────

@pytest.fixture()
def job_with_canonical_and_graph(db_session, user, tmp_path):
    """A done job whose output dir has canonical.json + canonical_graph.json.

    canonical.json has entities=[] (the orphan has no entity_id yet).
    canonical_graph.json has one orphan node (entity_id=None) at bbox [0,0,10,10].
    gpu_detections is set to the shape _load_detection expects: a list with one
    dict keyed 'label' (v1-10 in-process inference shape) at index 0.
    """
    csv = tmp_path / "output.csv"
    csv.write_text("")

    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "nodes": [
            {
                "id": "n_1",
                "entity_id": None,
                "bbox": [0.0, 0.0, 10.0, 10.0],
                "class": "valve_bv",
                "source": "auto",
            }
        ],
        "edges": [
            {"id": "e1", "source": "n_1", "target": "n_1"}
        ],
        "page_width": 100,
        "page_height": 100,
    }))

    # gpu_detections: a JSON list; index 0 is the detection linked by
    # linked_detection_index=0.  Use the v1-10 'label' key.
    gpu_detections = json.dumps([
        {
            "label": "valve_bv",
            "bbox": [0.0, 0.0, 10.0, 10.0],
            "confidence": 0.9,
        }
    ])

    job = models.Job(
        user_id=user.id,
        pid_no="T-ADOPT",
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        output_csv_path=str(csv),
        gpu_detections=gpu_detections,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # Write canonical.json after commit so job_id matches the ORM-assigned id.
    (tmp_path / "canonical.json").write_text(json.dumps({
        "job_id": job.id,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }))

    return job


# ── Test ──────────────────────────────────────────────────────────────────────

def test_adopt_node_e2e_flows(client, job_with_canonical_and_graph, db_session):
    job = job_with_canonical_and_graph

    # a) POST → 201, capture entity_id
    r = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": [1.0, 1.0, 11.0, 11.0],
            "sheet_number": 1,
            "linked_detection_index": 0,
        },
    )
    assert r.status_code == 201, r.text
    entity_id = r.json()["entity_id"]
    assert entity_id, "entity_id must be non-empty"

    # b) PATCH tag → 200
    r = client.patch(
        f"/api/v1/jobs/{job.id}/annotations/{entity_id}",
        json={"tag": "62-BV-9"},
    )
    assert r.status_code == 200, r.text

    # c) canonical has the entity_id after tagging.
    # entity_id from the API is a hex32 string (no dashes: uuid4().hex);
    # CanonicalEntity.entity_id is a UUID → str() inserts dashes.
    # Normalise both to UUID-with-dashes form before comparing.
    from uuid import UUID
    from webapp.deliverables.overrides import load_canonical_with_overrides
    canon = load_canonical_with_overrides(job.output_csv_path, job.id, db_session)
    entity_ids_in_canon = [str(e.entity_id) for e in canon.entities]
    entity_id_normalized = str(UUID(entity_id))
    assert entity_id_normalized in entity_ids_in_canon, (
        f"Expected entity_id {entity_id_normalized!r} in canonical entities; got {entity_ids_in_canon}"
    )

    # d) GET graph: dedup must have run AND returned real data.
    #
    # This fixture starts with exactly one auto node (n_1, entity_id=None) and
    # produces exactly one annotation node.  After superseded_auto_ids dedup
    # (IoU of [0,0,10,10] vs [1,1,11,11] ≈ 0.82 > threshold 0.5), n_1 is
    # dropped and only the adopted annotation node survives.
    #
    # The assertion "len == 1" is the STRONGEST correct check for this fixture:
    # - proves the route returned real data (not an empty list)
    # - proves dedup ran (if dedup were removed, n_1 + annotation both appear → 2)
    # - proves no spurious extra nodes were introduced
    r = client.get(f"/api/v1/jobs/{job.id}/graph")
    assert r.status_code == 200, r.text
    graph = r.json()
    nodes = graph.get("nodes", [])

    assert len(nodes) == 1, (
        f"Expected exactly 1 node after dedup (orphan n_1 absorbed into the "
        f"annotation node); got {len(nodes)}: {[n.get('id') for n in nodes]}"
    )

    node_ids = [n.get("id") for n in nodes]
    node_entity_ids = [n.get("entity_id") for n in nodes]

    assert "n_1" not in node_ids, (
        f"Orphan node n_1 should have been deduped but is still present: {node_ids}"
    )
    assert entity_id in node_entity_ids, (
        f"Annotation node {entity_id!r} should appear in graph nodes; got {node_entity_ids}"
    )
