"""Tests for webapp.scripts.export_annotations_for_yolo.

Covers:
  - Class mapping (valve sub_class -> YOLO id, instrument folding,
    unmappable rows skipped).
  - Page-pixel -> tile-local YOLO bbox math (deterministic via monkeypatched
    page dimensions).
  - Idempotent append behavior + dedupe.
  - --dry-run writes nothing.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp import models  # noqa: E402
from webapp.database import Base  # noqa: E402
from webapp.scripts import export_annotations_for_yolo as exp  # noqa: E402


# ── Test DB ──────────────────────────────────────────────────────────────────


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
    u = models.User(
        username="exp_tester",
        password_hash="x",
        is_active=True,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


@pytest.fixture()
def job(db_session, user, tmp_path):
    j = models.Job(
        user_id=user.id,
        original_filename="t.pdf",
        stored_filename="t.pdf",
        pid_no="T-001",
        status="done",
        output_csv_path=str(tmp_path / "valves.csv"),
    )
    db_session.add(j)
    db_session.commit()
    db_session.refresh(j)
    return j


# ── Class mapping ────────────────────────────────────────────────────────────


def test_map_to_class_id_valve_bv():
    assert exp.map_to_class_id("valve", "BV") == 0  # valve_bv = 0


def test_map_to_class_id_valve_bf():
    assert exp.map_to_class_id("valve", "BF") == 3  # valve_bf = 3


def test_map_to_class_id_valve_unmappable():
    # SB is not in v1-10's class list.
    assert exp.map_to_class_id("valve", "SB") is None


def test_map_to_class_id_instrument_folds_to_inst_field():
    # Generic instrument falls back to inst_field.
    assert exp.map_to_class_id("instrument", "FT") == 9  # inst_field = 9


def test_map_to_class_id_instrument_specific():
    assert exp.map_to_class_id("instrument", "bpcs") == 10  # inst_bpcs


def test_map_to_class_id_unknown_class():
    assert exp.map_to_class_id("widget", "x") is None


# ── Tile math ────────────────────────────────────────────────────────────────


def test_compute_tile_bounds_3x3_grid_1200x900():
    tiles = exp.compute_tile_bounds(1200, 900)
    assert len(tiles) == 9
    # Top-left tile starts at (0, 0)
    assert tiles[0]["x0"] == 0 and tiles[0]["y0"] == 0
    # Last tile reaches the page corner
    assert tiles[-1]["x1"] == 1200 and tiles[-1]["y1"] == 900


def test_find_owning_tile_picks_first_containing_center():
    tiles = exp.compute_tile_bounds(1200, 900)
    # bbox center at (100, 100) → in tile r=0 c=0
    own = exp.find_owning_tile([90, 90, 110, 110], tiles)
    assert own is not None
    assert (own["row"], own["col"]) == (0, 0)


def test_bbox_to_yolo_centered_in_tile():
    tiles = exp.compute_tile_bounds(1200, 900)
    t = tiles[0]
    tw = t["x1"] - t["x0"]
    th = t["y1"] - t["y0"]
    # Place a bbox whose center is at the tile center.
    cx_pg = t["x0"] + tw / 2
    cy_pg = t["y0"] + th / 2
    bbox = [cx_pg - 10, cy_pg - 5, cx_pg + 10, cy_pg + 5]
    cx, cy, w, h = exp.bbox_to_yolo(bbox, t)
    assert cx == pytest.approx(0.5, abs=1e-3)
    assert cy == pytest.approx(0.5, abs=1e-3)
    assert w == pytest.approx(20 / tw, abs=1e-3)
    assert h == pytest.approx(10 / th, abs=1e-3)


# ── End-to-end run ───────────────────────────────────────────────────────────


def _seed_annotation(db_session, job, user, **overrides):
    base = dict(
        job_id=job.id,
        entity_id="ent-1",
        user_id=user.id,
        source="user",
        status="user_added",
        entity_class="valve",
        sub_class="BV",
        bbox=[100.0, 100.0, 120.0, 110.0],
        sheet_number=1,
    )
    base.update(overrides)
    a = models.UserAnnotation(**base)
    db_session.add(a)
    db_session.commit()
    return a


def test_run_exports_yolo_lines(
    db_session, patch_sessionlocal, job, user, tmp_path, monkeypatch
):
    _seed_annotation(db_session, job, user)
    job_id = job.id
    # Stub the page-dim probe so we don't need a real PNG.
    monkeypatch.setattr(exp, "page_full_path_for_job", lambda j, s: tmp_path / "page.png")
    monkeypatch.setattr(exp, "page_dimensions", lambda p: (1200, 900))

    out_dir = tmp_path / "labels"
    exported, skipped, jobs_touched = exp.run(
        job_id=None, since=None, out_dir=out_dir, dry_run=False
    )
    assert exported == 1
    assert skipped == 0
    assert jobs_touched == 1

    label_path = out_dir / str(job_id) / "tile_p0_r0_c0.png.txt"
    assert label_path.exists()
    content = label_path.read_text().strip()
    parts = content.split()
    assert int(parts[0]) == 0  # valve_bv
    cx, cy, w, h = (float(p) for p in parts[1:])
    assert 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0
    assert 0.0 < w < 1.0 and 0.0 < h < 1.0


def test_run_skips_unmappable_sub_class(
    db_session, patch_sessionlocal, job, user, tmp_path, monkeypatch
):
    _seed_annotation(db_session, job, user, entity_id="ent-bad", sub_class="SB")
    job_id = job.id
    monkeypatch.setattr(exp, "page_full_path_for_job", lambda j, s: tmp_path / "page.png")
    monkeypatch.setattr(exp, "page_dimensions", lambda p: (1200, 900))

    out_dir = tmp_path / "labels"
    exported, skipped, _ = exp.run(
        job_id=None, since=None, out_dir=out_dir, dry_run=False
    )
    assert exported == 0
    assert skipped == 1
    assert not (out_dir / str(job_id)).exists()


def test_run_dry_run_writes_nothing(
    db_session, patch_sessionlocal, job, user, tmp_path, monkeypatch
):
    _seed_annotation(db_session, job, user)
    monkeypatch.setattr(exp, "page_full_path_for_job", lambda j, s: tmp_path / "page.png")
    monkeypatch.setattr(exp, "page_dimensions", lambda p: (1200, 900))

    out_dir = tmp_path / "labels"
    exported, skipped, _ = exp.run(
        job_id=None, since=None, out_dir=out_dir, dry_run=True
    )
    assert exported == 1
    assert skipped == 0
    # nothing on disk
    assert not out_dir.exists() or not any(out_dir.rglob("*.txt"))


def test_run_idempotent_dedupe(
    db_session, patch_sessionlocal, job, user, tmp_path, monkeypatch
):
    _seed_annotation(db_session, job, user)
    job_id = job.id
    monkeypatch.setattr(exp, "page_full_path_for_job", lambda j, s: tmp_path / "page.png")
    monkeypatch.setattr(exp, "page_dimensions", lambda p: (1200, 900))

    out_dir = tmp_path / "labels"
    exp.run(job_id=None, since=None, out_dir=out_dir, dry_run=False)
    exp.run(job_id=None, since=None, out_dir=out_dir, dry_run=False)
    label_path = out_dir / str(job_id) / "tile_p0_r0_c0.png.txt"
    # Second run should not duplicate the line.
    lines = [ln for ln in label_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_run_since_filters_old_rows(
    db_session, patch_sessionlocal, job, user, tmp_path, monkeypatch
):
    old = _seed_annotation(
        db_session, job, user, entity_id="old-1",
    )
    # Backdate by direct SQL update — onupdate=_utcnow stamps updated_at, but
    # created_at is a default-only column.
    db_session.query(models.UserAnnotation).filter(
        models.UserAnnotation.id == old.id
    ).update({"created_at": datetime(2024, 1, 1, tzinfo=timezone.utc)})
    db_session.commit()

    monkeypatch.setattr(exp, "page_full_path_for_job", lambda j, s: tmp_path / "page.png")
    monkeypatch.setattr(exp, "page_dimensions", lambda p: (1200, 900))

    out_dir = tmp_path / "labels"
    exported, _, _ = exp.run(
        job_id=None,
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        out_dir=out_dir,
        dry_run=False,
    )
    assert exported == 0
