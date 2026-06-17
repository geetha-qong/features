"""Tests for webapp.scripts.export_graph_for_training.

Covers JSONL output shape + filtering by --since.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models  # noqa: E402
from webapp.database import Base  # noqa: E402
from webapp.scripts import export_graph_for_training as exp  # noqa: E402


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
def patch_sessionlocal(db_session):
    with mock.patch.object(exp, "SessionLocal", return_value=db_session):
        yield


@pytest.fixture()
def user(db_session):
    u = models.User(username="u", password_hash="x", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user):
    j = models.Job(
        user_id=user.id,
        original_filename="t.pdf",
        stored_filename="t.pdf",
        pid_no="T-1",
        status="done",
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


def _seed_edge(db_session, job, user, **overrides):
    base = dict(
        job_id=job.id,
        edge_id="edge-1",
        user_id=user.id,
        source="user",
        status="user_added",
        line_type="process_pipe",
        relation_type="carries",
        source_entity_id="A",
        target_entity_id="B",
        polyline=[[0, 0], [10, 10]],
        sheet_number=1,
        group_id=None,
        metadata_json={"spec": "CS150"},
    )
    base.update(overrides)
    e = models.GraphCorrection(**base)
    db_session.add(e)
    db_session.commit()
    return e


def test_exports_jsonl_shape(db_session, patch_sessionlocal, job, user, tmp_path):
    _seed_edge(db_session, job, user)
    job_id = job.id
    out = tmp_path / "edges.jsonl"
    n = exp.run(job_id=None, since=None, out_path=out)
    assert n == 1
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["job_id"] == job_id
    assert rec["edge_id"] == "edge-1"
    assert rec["line_type"] == "process_pipe"
    assert rec["relation_type"] == "carries"
    assert rec["source_entity_id"] == "A"
    assert rec["target_entity_id"] == "B"
    assert rec["polyline"] == [[0, 0], [10, 10]]
    assert rec["group_id"] is None
    assert rec["metadata"] == {"spec": "CS150"}


def test_export_includes_directed_flag(db_session, patch_sessionlocal, job, user, tmp_path):
    """DoD: the `directed` flag must flow to the graph-extraction training set."""
    _seed_edge(db_session, job, user, edge_id="dir-1", directed=False)
    out = tmp_path / "edges.jsonl"
    exp.run(job_id=None, since=None, out_path=out)
    rec = json.loads(out.read_text().splitlines()[0])
    assert "directed" in rec
    assert rec["directed"] is False


def test_status_filter_skips_rejected(db_session, patch_sessionlocal, job, user, tmp_path):
    _seed_edge(db_session, job, user, edge_id="ok-1", status="user_confirmed")
    _seed_edge(db_session, job, user, edge_id="rej-1", status="user_rejected")
    out = tmp_path / "edges.jsonl"
    n = exp.run(job_id=None, since=None, out_path=out)
    assert n == 1
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec["edge_id"] == "ok-1"


def test_since_filter(db_session, patch_sessionlocal, job, user, tmp_path):
    old = _seed_edge(db_session, job, user, edge_id="old-1")
    db_session.query(models.GraphCorrection).filter(
        models.GraphCorrection.id == old.id
    ).update({"created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})
    db_session.commit()
    _seed_edge(db_session, job, user, edge_id="new-1")

    out = tmp_path / "edges.jsonl"
    n = exp.run(
        job_id=None,
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        out_path=out,
    )
    assert n == 1
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec["edge_id"] == "new-1"


def test_job_id_filter(db_session, patch_sessionlocal, job, user, tmp_path):
    other = models.Job(
        user_id=user.id,
        original_filename="o.pdf",
        stored_filename="o.pdf",
        pid_no="T-2",
        status="done",
    )
    db_session.add(other)
    db_session.commit()
    _seed_edge(db_session, job, user, edge_id="here-1")
    _seed_edge(db_session, other, user, edge_id="there-1")
    job_id = job.id

    out = tmp_path / "edges.jsonl"
    n = exp.run(job_id=job_id, since=None, out_path=out)
    assert n == 1
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec["edge_id"] == "here-1"
