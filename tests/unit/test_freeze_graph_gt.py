"""Unit tests for webapp/scripts/freeze_graph_gt.py::build_frozen_graph.

The GT-freeze tool snapshots a job's hand-corrected MERGED graph (auto extraction
+ user node/edge corrections) as the clean ground truth:
  - rejected (removed) nodes are DROPPED, not flagged
  - an auto edge touching a rejected node is dropped EVEN THOUGH auto edges key on
    node id (n_NNN), not entity_id  (the #129 reject-keys fix)
  - user-added annotation nodes + user-drawn edges are included

In-memory SQLite, mirrors tests/unit/test_node_corrections.py fixtures.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models
from webapp.database import Base
from webapp.scripts.freeze_graph_gt import build_frozen_graph

EID_A = str(uuid.UUID("11111111111111111111111111111111"))  # auto, kept
EID_B = str(uuid.UUID("22222222222222222222222222222222"))  # auto, rejected
EID_C = "cccccccccccccccccccccccccccccccc"                    # user-added node


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def job(db_session, tmp_path):
    u = models.User(username="g", password_hash="x", role="user", is_active=True)
    db_session.add(u)
    db_session.commit()
    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "job_id": 1, "version": "0.1", "page": 1, "page_width": 1000, "page_height": 800,
        "nodes": [
            {"id": "n_000", "entity_id": EID_A, "tag": "BV-1", "class": "valve_bv", "bbox": [10, 10, 30, 30], "tile": "page", "confidence": 0.9},
            {"id": "n_001", "entity_id": EID_B, "tag": "FT-2", "class": "inst_field", "bbox": [100, 100, 130, 130], "tile": "page", "confidence": 0.8},
        ],
        # auto edge keys on node id (n_000/n_001), NOT entity_id
        "edges": [{"id": "e_000", "source": "n_000", "target": "n_001", "polyline": [[20, 20], [115, 115]], "tile": "page", "method": "opencv", "confidence": 0.7, "directed": False}],
        "stats": {"nodes": 2, "edges": 1},
    }))
    j = models.Job(user_id=u.id, original_filename="t.pdf", stored_filename="t.pdf",
                   pid_no="T-1", status="done", output_csv_path=str(tmp_path / "valve_list.csv"))
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


def _add_user_node(db, job):
    db.add(models.UserAnnotation(
        job_id=job.id, user_id=job.user_id, entity_id=EID_C, source="user", status="user_added",
        entity_class="valve", sub_class="BV", bbox=[200, 200, 230, 230],
        tag="BV-9", sheet_number=1,
    ))
    db.commit()


def _reject(db, job, entity_id):
    db.add(models.EntityOverride(job_id=job.id, entity_id=entity_id, field_name="__rejected__",
                                 new_value=True, edited_by=job.user_id))
    db.commit()


def _add_user_edge(db, job, src, tgt):
    db.add(models.GraphCorrection(
        job_id=job.id, user_id=job.user_id, edge_id=uuid.uuid4().hex, source="user",
        status="user_added", source_entity_id=src, target_entity_id=tgt,
        polyline=[[20, 20], [215, 215]], line_type="process_pipe", directed=True,
    ))
    db.commit()


def test_baseline_frozen_graph_matches_extraction(db_session, job):
    g = build_frozen_graph(job.id, db_session)
    assert {n["entity_id"] for n in g["nodes"]} == {EID_A, EID_B}
    assert len(g["edges"]) == 1
    assert g["stats"]["nodes"] == 2 and g["stats"]["edges"] == 1


def test_user_added_node_included(db_session, job):
    _add_user_node(db_session, job)
    g = build_frozen_graph(job.id, db_session)
    eids = {n["entity_id"] for n in g["nodes"]}
    assert EID_C in eids
    user = next(n for n in g["nodes"] if n["entity_id"] == EID_C)
    assert user["source"] == "user" and "rejected" not in user


def test_rejected_node_dropped_with_its_auto_edge(db_session, job):
    # Reject B (a detected node). Its auto edge keys on node id n_001, not EID_B.
    _reject(db_session, job, EID_B)
    g = build_frozen_graph(job.id, db_session)
    assert {n["entity_id"] for n in g["nodes"]} == {EID_A}        # B dropped
    assert g["edges"] == []                                        # auto edge n_000->n_001 dropped via node-id
    assert g["stats"]["edges"] == 0


def test_user_drawn_edge_included_and_clean_truth(db_session, job):
    _add_user_node(db_session, job)
    _reject(db_session, job, EID_B)
    _add_user_edge(db_session, job, EID_A, EID_C)
    g = build_frozen_graph(job.id, db_session)
    assert {n["entity_id"] for n in g["nodes"]} == {EID_A, EID_C}  # B gone, C added
    # the A-B auto edge is gone; the A-C user edge remains
    pairs = [{e.get("source"), e.get("target")} for e in g["edges"]]
    assert {EID_A, EID_C} in pairs
    assert all("n_001" not in p for p in pairs)


def test_missing_graph_raises(db_session, job, tmp_path):
    os.remove(tmp_path / "canonical_graph.json")
    with pytest.raises(FileNotFoundError):
        build_frozen_graph(job.id, db_session)


# ---------------------------------------------------------------------------
# Helpers for the orphan-dedup test
# ---------------------------------------------------------------------------

def _job_with_graph(db, tmp_path, nodes, edges):
    """Create a Job with canonical_graph.json containing given nodes/edges."""
    u = models.User(username="h_" + str(uuid.uuid4().hex[:6]),
                    password_hash="x", role="user", is_active=True)
    db.add(u)
    db.commit()
    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "job_id": 99, "version": "0.1", "page": 1,
        "page_width": 1000, "page_height": 800,
        "nodes": nodes,
        "edges": edges,
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }))
    j = models.Job(
        user_id=u.id, original_filename="t.pdf", stored_filename="t.pdf",
        pid_no="T-2", status="done",
        output_csv_path=str(tmp_path / "valve_list.csv"),
    )
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _add_annotation(db, job, entity_id, bbox, entity_class, sub_class, status, tag):
    """Insert a UserAnnotation row (adopted / user-confirmed node)."""
    db.add(models.UserAnnotation(
        job_id=job.id, user_id=job.user_id, entity_id=entity_id,
        source="user", status=status,
        entity_class=entity_class, sub_class=sub_class,
        bbox=bbox, tag=tag, sheet_number=1,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# Orphan-dedup test
# ---------------------------------------------------------------------------

def test_freeze_drops_orphan_superseded_by_adopted_node(db_session, tmp_path):
    # build_frozen_graph reads canonical_graph.json + annotations; adopted
    # annotation at same bbox as an orphan auto node -> only one node frozen.
    from webapp.scripts.freeze_graph_gt import build_frozen_graph
    job = _job_with_graph(db_session, tmp_path, nodes=[
        {"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10], "class": "valve_bv"},
    ], edges=[{"id": "e1", "source": "n_1", "target": "n_1"}])
    _add_annotation(db_session, job, entity_id="e-x", bbox=[1, 1, 11, 11],
                    entity_class="valve", sub_class="BV", status="user_confirmed", tag="62-BV-1")
    g = build_frozen_graph(job.id, db_session)
    ids = [n["id"] for n in g["nodes"]]
    assert "n_1" not in ids
    assert any(n.get("entity_id") == "e-x" for n in g["nodes"])
    assert all(e.get("source") != "n_1" and e.get("target") != "n_1" for e in g["edges"])
