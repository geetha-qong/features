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


def test_discover_jobs_handles_dual_use_path(tmp_path):
    """Regression test: production job_outputs/2/ is BOTH a legacy job
    (has its own valve_list.csv from the era of flat layout) AND an
    org dir for org_id=2's later jobs (job_outputs/2/{6,7,8}/).

    `discover_jobs` must yield BOTH the parent job AND the children."""
    # Job 2 lives at the parent (legacy)
    _make_legacy_job(tmp_path, 2)
    # Org 2's jobs 6, 7, 8 live underneath it
    (tmp_path / "2" / "6").mkdir()
    (tmp_path / "2" / "7").mkdir()
    (tmp_path / "2" / "8").mkdir()
    for jid in (6, 7, 8):
        with (tmp_path / "2" / str(jid) / "valve_list.csv").open("w", newline="") as f:
            csv.writer(f).writerows([
                ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line'],
                ['P-X','-','GL','2','62',str(300000 + jid),'-','G','AC-PP','1','-','-','-','2"-G-X-AC-PP'],
            ])

    jobs = list(backfill_canonical.discover_jobs(tmp_path))
    job_ids = sorted(j.job_id for j in jobs)
    assert job_ids == [2, 6, 7, 8], f"expected [2, 6, 7, 8], got {job_ids}"


def test_discover_jobs_ignores_exports_and_tmp_subdirs(tmp_path):
    """exports/ and tmp/ subdirectories (created by deliverables generator
    + pipeline scratch space) must NOT be confused with job dirs even if
    they contain a valve_list.csv."""
    job_dir = _make_legacy_job(tmp_path, 1)
    (job_dir / "exports").mkdir()
    # The deliverables generator legitimately writes valve_list.csv into exports/
    with (job_dir / "exports" / "valve_list.csv").open("w") as f:
        f.write("does not matter")
    (job_dir / "tmp").mkdir()
    with (job_dir / "tmp" / "valve_list.csv").open("w") as f:
        f.write("does not matter")

    jobs = list(backfill_canonical.discover_jobs(tmp_path))
    job_ids = sorted(j.job_id for j in jobs)
    assert job_ids == [1]  # 'exports' and 'tmp' must not appear as job ids


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
