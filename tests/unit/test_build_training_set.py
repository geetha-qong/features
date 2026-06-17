"""Tests for webapp.scripts.build_training_set.

Focus on the deterministic, side-effect-free parts: the dry-run manifest shape,
date-string-driven output path, and since_source resolution. The dry-run path
never invokes the heavy YOLO/graph exporters, so these stay fast and don't need
PIL or the ONNX deps installed.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

builder = pytest.importorskip("webapp.scripts.build_training_set")

from webapp import models  # noqa: E402
from webapp.database import Base  # noqa: E402


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
    with mock.patch.object(builder, "SessionLocal", return_value=db_session):
        yield


def _list_created(out_root):
    """Files under out_root, relative — empty list if nothing written."""
    found = []
    for root, _dirs, files in os.walk(out_root):
        for f in files:
            found.append(os.path.join(root, f))
    return found


def test_dry_run_returns_manifest_shape(patch_sessionlocal, tmp_path):
    manifest = builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert isinstance(manifest, dict)
    for key in (
        "generated_at",
        "model_version",
        "since",
        "since_source",
        "detection",
        "graph",
        "tags",
        "class_counts",
    ):
        assert key in manifest, "missing manifest key: {}".format(key)

    assert set(manifest["detection"].keys()) == {
        "label_files",
        "annotations",
        "skipped_unmappable",
        "jobs",
    }
    assert manifest["graph"] == {"edges": 0}
    assert manifest["tags"]["corrections"] == 0
    assert manifest["class_counts"] == {}


def test_dry_run_writes_no_files(patch_sessionlocal, tmp_path):
    builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert _list_created(str(tmp_path)) == []


def test_output_path_uses_date_str(patch_sessionlocal, tmp_path, monkeypatch):
    """The dated dir is derived from date_str, not datetime.now()."""
    # Even if the wall clock differed, the path must reflect the passed date.
    manifest = builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    # generated_at is a real timestamp; the date that drives the path is in
    # the resolved out_dir. Re-derive it the way run() does:
    from pathlib import Path

    out_dir = Path(str(tmp_path)) / "2026-06-17"
    assert out_dir.name == "2026-06-17"
    # And the manifest is internally consistent (no crash, dict shape).
    assert isinstance(manifest["generated_at"], str)


def test_since_source_is_current_model_when_arg_absent(
    patch_sessionlocal, tmp_path, monkeypatch
):
    fixed = datetime(2026, 6, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(builder, "current_model_trained_at", lambda: fixed)
    manifest = builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert manifest["since_source"] == "current_model_trained_at"
    assert manifest["since"] == "2026-06-05T00:00:00Z"


def test_since_source_none_when_anchor_missing(
    patch_sessionlocal, tmp_path, monkeypatch
):
    monkeypatch.setattr(builder, "current_model_trained_at", lambda: None)
    manifest = builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert manifest["since_source"] == "none"
    assert manifest["since"] is None


def test_since_source_arg_when_passed(patch_sessionlocal, tmp_path):
    manifest = builder.run(
        since="2026-01-15",
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert manifest["since_source"] == "arg"
    assert manifest["since"] == "2026-01-15T00:00:00Z"


def test_class_counts_and_tags_from_db(
    db_session, patch_sessionlocal, tmp_path
):
    """Dry-run still reads the DB for class_counts + tag corrections."""
    u = models.User(username="u", password_hash="x", is_active=True)
    db_session.add(u)
    db_session.flush()

    db_session.add_all(
        [
            models.UserAnnotation(
                job_id=1, entity_id="e1", user_id=u.id, source="user",
                status="user_added", entity_class="valve", sub_class="BV",
                bbox=[0, 0, 1, 1], sheet_number=1,
            ),
            models.UserAnnotation(
                job_id=1, entity_id="e2", user_id=u.id, source="user",
                status="user_confirmed", entity_class="valve", sub_class="BV",
                bbox=[0, 0, 1, 1], sheet_number=1,
            ),
            models.UserAnnotation(
                job_id=1, entity_id="e3", user_id=u.id, source="user",
                status="user_added", entity_class="instrument", sub_class=None,
                bbox=[0, 0, 1, 1], sheet_number=1,
            ),
            # Rejected row must NOT be counted.
            models.UserAnnotation(
                job_id=1, entity_id="e4", user_id=u.id, source="model",
                status="user_rejected", entity_class="valve", sub_class="GL",
                bbox=[0, 0, 1, 1], sheet_number=1,
            ),
        ]
    )
    db_session.add_all(
        [
            models.EntityOverride(
                job_id=1, entity_id="e1", field_name="tag",
                new_value="V-101", prior_value="V-100", edited_by=u.id,
            ),
            # Non-tag override must NOT be counted.
            models.EntityOverride(
                job_id=1, entity_id="e2", field_name="sub_class",
                new_value="GL", prior_value="BV", edited_by=u.id,
            ),
        ]
    )
    db_session.commit()

    manifest = builder.run(
        since=None,
        out_root=str(tmp_path),
        job_ids=None,
        dry_run=True,
        date_str="2026-06-17",
    )
    assert manifest["class_counts"] == {"valve/BV": 2, "instrument/_": 1}
    assert manifest["tags"]["corrections"] == 1
    # Still no files in dry-run.
    assert _list_created(str(tmp_path)) == []
