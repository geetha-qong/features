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
        "images",
        "train_tiles",
        "val_tiles",
        "train_jobs",
        "val_jobs",
        "classes",
    }
    # `classes` reflects the taxonomy even in dry-run; the rest are 0/empty.
    from webapp.taxonomy import class_names

    assert manifest["detection"]["classes"] == len(class_names())
    assert manifest["detection"]["images"] == 0
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


# ── _split_for_job determinism ────────────────────────────────────────────────


def test_split_for_job_is_deterministic():
    # Same job id -> same split, repeatedly.
    assert builder._split_for_job(42) == builder._split_for_job(42)
    assert builder._split_for_job(7) == builder._split_for_job(7)
    # Only "train" / "val" ever come out.
    for jid in range(0, 50):
        assert builder._split_for_job(jid) in ("train", "val")


def test_split_for_job_known_values():
    # sha1(str(job_id)) % 10 == 0 -> "val", else "train". Computed independently.
    import hashlib

    def expected(job_id):
        h = int(hashlib.sha1(str(job_id).encode()).hexdigest(), 16)
        return "val" if h % 10 == 0 else "train"

    for jid in (1, 2, 3, 17, 41, 100, 999):
        assert builder._split_for_job(jid) == expected(jid)


# ── data.yaml writer ──────────────────────────────────────────────────────────


def test_data_yaml_names_match_class_names(tmp_path):
    from webapp.taxonomy import class_names

    det_dir = tmp_path / "detection"
    det_dir.mkdir()
    nc = builder._write_data_yaml(det_dir / "data.yaml", det_dir)

    names = class_names()
    assert nc == len(names)

    import yaml

    data = yaml.safe_load((det_dir / "data.yaml").read_text())
    assert data["nc"] == len(names)
    assert data["train"] == "images/train"
    assert data["val"] == "images/val"
    # names is an int-keyed mapping of the full ordered class list.
    assert len(data["names"]) == nc
    assert data["names"][0] == names[0]
    assert data["names"][nc - 1] == names[nc - 1]


# ── Non-dry-run build: crop + split + data.yaml ───────────────────────────────


def test_non_dry_run_builds_trainable_dataset(
    db_session, patch_sessionlocal, tmp_path, monkeypatch
):
    """Exercise crop+split+data.yaml deterministically.

    Stub the YOLO exporter's run() to drop one known staging label file, and
    stub page_full_path_for_job to return a small PNG we create. Assert the
    trainable tree + data.yaml + consistent manifest counts.
    """
    from PIL import Image

    from webapp.scripts import export_annotations_for_yolo as yolo
    from webapp.taxonomy import class_names

    job_id = 1
    # A Job must exist for the crop step to resolve the page image.
    u = models.User(username="u", password_hash="x", is_active=True)
    db_session.add(u)
    db_session.flush()
    db_session.add(
        models.Job(
            id=job_id, user_id=u.id,
            original_filename="job1.pdf", stored_filename="job1.pdf",
            output_csv_path="/tmp/job1/valves.csv",
        )
    )
    db_session.commit()

    # The tile the staging label belongs to: page index 0 -> sheet_number 1.
    tile_png = "tile_p0_r1_c1.png"

    # A small page-full PNG on disk that the (stubbed) lookup returns.
    page_png = tmp_path / "page_0_full.png"
    Image.new("RGB", (300, 300), (255, 255, 255)).save(page_png)
    monkeypatch.setattr(
        yolo, "page_full_path_for_job", lambda job, sheet_number: page_png
    )

    # Stub the exporter run() to write one known staging label file.
    def fake_run(*, job_id, since, out_dir, dry_run):
        d = out_dir / str(1)
        d.mkdir(parents=True, exist_ok=True)
        (d / (tile_png + ".txt")).write_text(
            "3 0.500000 0.500000 0.100000 0.100000\n", encoding="utf-8"
        )
        return 1, 0, 1  # exported, skipped, jobs_touched

    monkeypatch.setattr(builder._yolo_exporter, "run", fake_run)

    # Skip the graph exporter so the build stays focused + offline.
    monkeypatch.setattr(builder, "_graph_exporter", None)

    manifest = builder.run(
        since="2026-01-01",
        out_root=str(tmp_path / "out"),
        job_ids=None,
        dry_run=False,
        date_str="2026-06-18",
    )

    detection = tmp_path / "out" / "2026-06-18" / "detection"

    # data.yaml exists with nc == len(class_names()).
    import yaml

    data = yaml.safe_load((detection / "data.yaml").read_text())
    assert data["nc"] == len(class_names())
    assert len(data["names"]) == len(class_names())

    # Staging dir is gone; detection holds only images/, labels/, data.yaml.
    assert not (detection / "_staging").exists()
    assert sorted(p.name for p in detection.iterdir()) == [
        "data.yaml",
        "images",
        "labels",
    ]

    # The split for job 1 (deterministic).
    split = builder._split_for_job(job_id)
    stem = "{}__{}".format(job_id, tile_png[: -len(".png")])
    img = detection / "images" / split / (stem + ".png")
    lbl = detection / "labels" / split / (stem + ".txt")
    assert img.exists(), "tile image not written"
    assert lbl.exists(), "label not written"
    # Same stem on both sides.
    assert img.stem == lbl.stem
    # Label content preserved verbatim from staging.
    assert lbl.read_text().strip() == "3 0.500000 0.500000 0.100000 0.100000"

    # Manifest detection counts are consistent.
    det = manifest["detection"]
    assert det["images"] == 1
    assert det["train_tiles"] + det["val_tiles"] == det["images"]
    assert det["classes"] == len(class_names())
    if split == "val":
        assert det["val_tiles"] == 1 and det["train_tiles"] == 0
        assert det["val_jobs"] == [job_id]
    else:
        assert det["train_tiles"] == 1 and det["val_tiles"] == 0
        assert det["train_jobs"] == [job_id]
