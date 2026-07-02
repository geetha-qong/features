import json
from pathlib import Path

import pytest

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.job_loader import (
    JobCanonicalNotFound,
    canonical_path_for_job,
    load_canonical_for_job,
)


def test_canonical_path_orgscoped(tmp_path):
    csv_path = tmp_path / "12" / "41" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    assert canonical_path_for_job(str(csv_path)) == str(csv_path.parent / "canonical.json")


def test_canonical_path_legacy(tmp_path):
    csv_path = tmp_path / "33" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    assert canonical_path_for_job(str(csv_path)) == str(csv_path.parent / "canonical.json")


def test_load_canonical_missing(tmp_path):
    csv_path = tmp_path / "1" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    with pytest.raises(JobCanonicalNotFound):
        load_canonical_for_job(str(csv_path))


def test_load_canonical_present(tmp_path):
    csv_path = tmp_path / "1" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")
    canonical = {
        "job_id": 1,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [],
    }
    (csv_path.parent / "canonical.json").write_text(json.dumps(canonical))
    result = load_canonical_for_job(str(csv_path))
    assert isinstance(result, JobCanonical)
    assert result.job_id == 1
