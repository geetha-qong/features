"""Tests for the backfill_canonical --force re-emit path.

`--force` exists to repair jobs that already have a canonical.json written by an
older emitter (e.g. before the ALL-CAPS instrument-field map fix, whose instrument
rows came out with empty data fields). Without --force such a job is skipped
because the file is the source of truth; with --force it is re-emitted from the
CSVs. See FEATURES entry for the dev backfill.
"""
import json
import sys
from pathlib import Path

from webapp.scripts import backfill_canonical

# Instrument CSV uses the real ALL-CAPS column headers the emitter expects.
INST_CSV = (
    "TAG NUMBER,TAG SERVICE,LINE NUMBER,EQUIP NO,LOCATION\r\n"
    "62-FE-151010,SKIM OIL PUMP DISCHARGE FLOW,NA,62-P-151007,FIELD\r\n"
)

# A stale canonical.json shaped like the pre-fix output: instruments missing /
# empty. Minimal valid JobCanonical JSON with no entities.
STALE_CANONICAL = '{"job_id": %d, "canonical_schema_version": "1.0", "entities": []}'


def _make_job(root: Path, job_id: int) -> Path:
    d = root / str(job_id)
    d.mkdir(parents=True)
    (d / "instrumentation_index.csv").write_text(INST_CSV, encoding="utf-8")
    (d / "canonical.json").write_text(STALE_CANONICAL % job_id, encoding="utf-8")
    return d


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["backfill_canonical", *argv])
    return backfill_canonical.main()


def test_force_re_emits_over_stale_canonical(tmp_path, monkeypatch):
    job_dir = _make_job(tmp_path, 99)

    rc = _run(monkeypatch, ["--root", str(tmp_path), "--force"])

    assert rc == 0
    data = json.loads((job_dir / "canonical.json").read_text(encoding="utf-8"))
    insts = [e for e in data["entities"] if e["entity_class"] == "instrument"]
    assert insts, "force re-emit should have produced instrument entities"
    assert insts[0]["fields"]["service_description"] == "SKIM OIL PUMP DISCHARGE FLOW"
    assert insts[0]["fields"]["equipment_no"] == "62-P-151007"


def test_without_force_skips_existing_canonical(tmp_path, monkeypatch):
    job_dir = _make_job(tmp_path, 98)
    before = (job_dir / "canonical.json").read_text(encoding="utf-8")

    rc = _run(monkeypatch, ["--root", str(tmp_path)])

    assert rc == 0
    # untouched — the stale file is preserved when --force is absent
    assert (job_dir / "canonical.json").read_text(encoding="utf-8") == before


def test_dry_run_force_does_not_write(tmp_path, monkeypatch):
    job_dir = _make_job(tmp_path, 97)
    before = (job_dir / "canonical.json").read_text(encoding="utf-8")

    rc = _run(monkeypatch, ["--root", str(tmp_path), "--force", "--dry-run"])

    assert rc == 0
    assert (job_dir / "canonical.json").read_text(encoding="utf-8") == before
