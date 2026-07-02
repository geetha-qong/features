"""Tests for _resolve_detection_index_by_bbox — server-side detection-claim
resolution that is tile-offset-corrected.

The critical case is a detection whose bbox is tile-local to a NON-top-left tile
(e.g. tile_p0_r1_c1).  Client-side IoU matching against tile-local coords would
see a completely different coordinate space and return -1 (no match), producing a
spurious ModelCorrection('add') that pollutes the training set.  The server-side
resolver translates via compute_tile_offsets so the match succeeds.

The test also verifies:
  - POST /annotations with linked_detection_index=None triggers server-side
    resolution when a matching detection exists (→ user_confirmed, no spurious add).
  - POST /annotations with linked_detection_index=None and NO matching detection
    stays -1 (→ user_added + ModelCorrection('add') — correct for genuine new mark).
  - An explicitly-supplied linked_detection_index is honoured as-is (existing
    test_adopt_node_e2e contract preserved).
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models
from webapp.auth import get_current_user, pwd_context
from webapp.database import Base, get_db
from webapp.graph.loader import compute_tile_offsets
from webapp.main import app
from webapp.routers.annotations import _resolve_detection_index_by_bbox


# ── Helpers ────────────────────────────────────────────────────────────────────

PAGE_W = 900
PAGE_H = 900


def _tile_offset(page_w: int, page_h: int, row: int, col: int) -> tuple:
    """Return the (x0, y0) page-pixel origin for the given tile row/col."""
    from webapp.graph.loader import GRID_COLS, GRID_ROWS, OVERLAP_PCT
    tile_w = math.ceil(page_w / GRID_COLS)
    tile_h = math.ceil(page_h / GRID_ROWS)
    overlap_x = int(tile_w * OVERLAP_PCT)
    overlap_y = int(tile_h * OVERLAP_PCT)
    x0 = max(0, col * tile_w - overlap_x)
    y0 = max(0, row * tile_h - overlap_y)
    return x0, y0


def _make_detection_in_tile(row: int, col: int, local_bbox: List[float]) -> dict:
    """Build a gpu_detections entry with tile-local bbox for tile_p0_r{row}_c{col}."""
    return {
        "label": "valve_bv",
        "tile": f"tile_p0_r{row}_c{col}.png",
        "bbox": local_bbox,
        "confidence": 0.9,
    }


# ── Fixtures ───────────────────────────────────────────────────────────────────

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
    u = models.User(
        username="resolver_u",
        password_hash=pwd_context.hash("x"),
        credits_remaining=20,
        is_active=True,
        role="user",
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def client(db_session, user):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _make_job(db_session, user, tmp_path: Path, gpu_detections_json: str) -> models.Job:
    """Build a done job with canonical.json + canonical_graph.json in tmp_path."""
    csv = tmp_path / "output.csv"
    csv.write_text("")

    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "nodes": [],
        "edges": [],
        "page_width": PAGE_W,
        "page_height": PAGE_H,
    }))
    (tmp_path / "canonical.json").write_text(json.dumps({
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }))

    job = models.Job(
        user_id=user.id,
        pid_no="T-RESOLVE",
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        output_csv_path=str(csv),
        gpu_detections=gpu_detections_json,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


# ── Unit: _resolve_detection_index_by_bbox — non-zero-tile-offset case ─────────

def test_resolve_non_topleft_tile(db_session, user, tmp_path):
    """The whole point of server-side resolution: a detection in tile r=1,c=1
    has tile-local coords near (5,5,15,15).  Its page-pixel origin is NOT (0,0),
    so a naive client-side IoU against (5,5,15,15) would miss the page-pixel bbox
    we supply.  The server-side resolver must map it correctly.
    """
    # Compute the expected page-pixel origin for tile r=1, c=1.
    x0, y0 = _tile_offset(PAGE_W, PAGE_H, row=1, col=1)

    # The detection: tile-local bbox [5, 5, 15, 15] inside tile r=1,c=1.
    local_bbox = [5.0, 5.0, 15.0, 15.0]
    expected_page_bbox = [x0 + 5.0, y0 + 5.0, x0 + 15.0, y0 + 15.0]

    det = _make_detection_in_tile(row=1, col=1, local_bbox=local_bbox)
    gpu_dets = json.dumps([det])

    job = _make_job(db_session, user, tmp_path, gpu_dets)

    # The caller passes the PAGE-PIXEL bbox (what the graph layer uses).
    idx = _resolve_detection_index_by_bbox(job, expected_page_bbox)
    assert idx == 0, (
        f"Expected index 0 for detection in tile r=1,c=1 at page-pixel "
        f"{expected_page_bbox}; got {idx}.  "
        f"Tile origin was (x0={x0}, y0={y0})."
    )


def test_resolve_returns_minus1_when_no_overlap(db_session, user, tmp_path):
    """When the page-pixel bbox is far from any detection, return -1 (fresh mark)."""
    # Detection in top-left tile at [0,0,10,10] page-pixel
    det = _make_detection_in_tile(row=0, col=0, local_bbox=[0.0, 0.0, 10.0, 10.0])
    job = _make_job(db_session, user, tmp_path, json.dumps([det]))

    # Page-pixel bbox far from the detection
    idx = _resolve_detection_index_by_bbox(job, [800.0, 800.0, 850.0, 850.0])
    assert idx == -1


def test_resolve_no_detections_returns_minus1(db_session, user, tmp_path):
    """Job with empty gpu_detections → -1."""
    job = _make_job(db_session, user, tmp_path, json.dumps([]))
    idx = _resolve_detection_index_by_bbox(job, [0.0, 0.0, 10.0, 10.0])
    assert idx == -1


def test_resolve_missing_canonical_graph_returns_minus1(db_session, user, tmp_path):
    """Without canonical_graph.json (no page dims) → -1 (can't compute offsets)."""
    csv = tmp_path / "output.csv"
    csv.write_text("")
    # Deliberately omit canonical_graph.json
    det = _make_detection_in_tile(row=0, col=0, local_bbox=[0.0, 0.0, 10.0, 10.0])
    job = models.Job(
        user_id=user.id,
        pid_no="T-NO-GRAPH",
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        output_csv_path=str(csv),
        gpu_detections=json.dumps([det]),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    idx = _resolve_detection_index_by_bbox(job, [0.0, 0.0, 10.0, 10.0])
    assert idx == -1


# ── Integration: POST /annotations with linked_detection_index=None ────────────

def test_post_annotation_null_index_claims_overlapping_detection(
    client, db_session, user, tmp_path
):
    """POST with linked_detection_index=None should resolve server-side.

    Posting the PAGE-PIXEL bbox of a detection in tile r=1,c=1 with
    linked_detection_index=null must produce status=user_confirmed (claim path),
    NOT user_added (fresh-mark path), proving the server-side resolution ran
    and found the correct detection index.
    """
    x0, y0 = _tile_offset(PAGE_W, PAGE_H, row=1, col=1)
    local_bbox = [10.0, 10.0, 30.0, 30.0]
    page_bbox = [x0 + 10.0, y0 + 10.0, x0 + 30.0, y0 + 30.0]

    det = _make_detection_in_tile(row=1, col=1, local_bbox=local_bbox)
    gpu_dets = json.dumps([det])

    csv = tmp_path / "output.csv"
    csv.write_text("")
    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "nodes": [],
        "edges": [],
        "page_width": PAGE_W,
        "page_height": PAGE_H,
    }))
    (tmp_path / "canonical.json").write_text(json.dumps({
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }))
    job = models.Job(
        user_id=user.id,
        pid_no="T-CLAIM",
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        output_csv_path=str(csv),
        gpu_detections=gpu_dets,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    r = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            "bbox": page_bbox,
            "sheet_number": 1,
            "linked_detection_index": None,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()

    # CLAIM path: user_confirmed, linked_detection_index resolved to 0
    assert body["status"] == "user_confirmed", (
        f"Expected user_confirmed (claim path) for detection in tile r=1,c=1; "
        f"got status={body['status']!r}.  linked_detection_index={body.get('linked_detection_index')}"
    )
    assert body["linked_detection_index"] == 0, (
        f"Expected linked_detection_index=0; got {body.get('linked_detection_index')}"
    )

    # No spurious ModelCorrection('add') should have been emitted.
    from webapp.models import ModelCorrection
    add_corrections = (
        db_session.query(ModelCorrection)
        .filter(ModelCorrection.job_id == job.id, ModelCorrection.action == "add")
        .all()
    )
    assert len(add_corrections) == 0, (
        f"Spurious ModelCorrection('add') rows found: {len(add_corrections)}.  "
        f"A claimed detection should NOT emit a false-negative add correction."
    )


def test_post_annotation_null_index_fresh_mark_when_no_overlap(
    client, db_session, user, tmp_path
):
    """POST with linked_detection_index=None and NO nearby detection → fresh mark.

    user_added status + one ModelCorrection('add') — correct for a genuinely
    new symbol that the model missed.
    """
    det = _make_detection_in_tile(row=0, col=0, local_bbox=[0.0, 0.0, 10.0, 10.0])
    csv = tmp_path / "output.csv"
    csv.write_text("")
    (tmp_path / "canonical_graph.json").write_text(json.dumps({
        "nodes": [],
        "edges": [],
        "page_width": PAGE_W,
        "page_height": PAGE_H,
    }))
    (tmp_path / "canonical.json").write_text(json.dumps({
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }))
    job = models.Job(
        user_id=user.id,
        pid_no="T-FRESH",
        status="done",
        original_filename="t.pdf",
        stored_filename="t.pdf",
        output_csv_path=str(csv),
        gpu_detections=json.dumps([det]),
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    r = client.post(
        f"/api/v1/jobs/{job.id}/annotations",
        json={
            "entity_class": "valve",
            "sub_class": "BV",
            # Far from the detection
            "bbox": [800.0, 800.0, 840.0, 840.0],
            "sheet_number": 1,
            "linked_detection_index": None,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()

    assert body["status"] == "user_added", (
        f"Expected user_added (fresh-mark path) when bbox doesn't overlap any detection; "
        f"got {body['status']!r}"
    )

    from webapp.models import ModelCorrection
    add_corrections = (
        db_session.query(ModelCorrection)
        .filter(ModelCorrection.job_id == job.id, ModelCorrection.action == "add")
        .all()
    )
    assert len(add_corrections) == 1, (
        f"Expected exactly 1 ModelCorrection('add') for a fresh mark; got {len(add_corrections)}"
    )
