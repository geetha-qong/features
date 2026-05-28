"""Tests for webapp.deliverables.backfill_canonical — backfills canonical.json
for existing jobs in job_outputs/."""

import csv
import json
from pathlib import Path

import pytest

from webapp.deliverables import backfill_canonical


def _make_legacy_job(root: Path, job_id: int) -> Path:
    job_dir = root / str(job_id)
    job_dir.mkdir(parents=True)
    with (job_dir / "valve_list.csv").open("w", newline="") as f:
        csv.writer(f).writerows([
            ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line'],
            ['P-001','-','GL','4','62',str(100000 + job_id),'-','G','AC-PP','1','-','-','-','4"-G-1-AC-PP'],
        ])
    return job_dir


def _make_orgscoped_job(root: Path, org_id: int, job_id: int) -> Path:
    job_dir = root / str(org_id) / str(job_id)
    job_dir.mkdir(parents=True)
    with (job_dir / "valve_list.csv").open("w", newline="") as f:
        csv.writer(f).writerows([
            ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line'],
            ['P-002','-','BV','2','62',str(200000 + job_id),'-','LO','AC','1','-','-','-','2"-LO-2-AC'],
        ])
    return job_dir


def test_discover_jobs_finds_legacy_and_orgscoped(tmp_path):
    _make_legacy_job(tmp_path, 5)
    _make_legacy_job(tmp_path, 39)
    _make_orgscoped_job(tmp_path, 12, 41)
    _make_orgscoped_job(tmp_path, 12, 42)
    # A directory with no valve_list.csv must be ignored
    (tmp_path / "garbage").mkdir()
    (tmp_path / "garbage" / "random.txt").write_text("not a job")

    jobs = list(backfill_canonical.discover_jobs(tmp_path))
    job_ids = sorted(j.job_id for j in jobs)
    assert job_ids == [5, 39, 41, 42]


def test_backfill_writes_canonical_for_legacy(tmp_path):
    job_dir = _make_legacy_job(tmp_path, 7)
    results = backfill_canonical.backfill_all(tmp_path)
    assert len(results) == 1
    assert results[0].job_id == 7
    assert results[0].canonical_path == job_dir / "canonical.json"
    assert results[0].canonical_path.exists()


def test_backfill_skips_existing_canonical(tmp_path):
    """Jobs that ALREADY have canonical.json are skipped (idempotent)."""
    job_dir = _make_legacy_job(tmp_path, 10)
    # Pre-write a sentinel canonical.json
    (job_dir / "canonical.json").write_text('{"sentinel": "untouched"}')

    results = backfill_canonical.backfill_all(tmp_path)
    skipped = [r for r in results if r.skipped]
    assert len(skipped) == 1
    # Sentinel must NOT have been overwritten
    raw = json.loads((job_dir / "canonical.json").read_text())
    assert raw == {"sentinel": "untouched"}


def test_backfill_force_overwrites_existing(tmp_path):
    """--force overwrites existing canonical.json."""
    job_dir = _make_legacy_job(tmp_path, 11)
    (job_dir / "canonical.json").write_text('{"sentinel": "untouched"}')

    results = backfill_canonical.backfill_all(tmp_path, force=True)
    skipped = [r for r in results if r.skipped]
    assert len(skipped) == 0  # nothing skipped under --force
    raw = json.loads((job_dir / "canonical.json").read_text())
    assert "sentinel" not in raw
    assert raw["job_id"] == 11
