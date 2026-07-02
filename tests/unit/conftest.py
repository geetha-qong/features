"""Unit-test level fixtures shared across all tests/unit/ tests."""
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolated_job_output_dir(tmp_path: Path, monkeypatch):
    """Redirect JOB_OUTPUT_DIR to an isolated tmp directory for every unit test.

    Without this, a new test job that gets auto-assigned id=1 would look at the
    real /app/job_outputs/1/1/tmp/ which may contain tiles from production jobs,
    causing sheet-count assertions to fail (returns 9 instead of 0).
    """
    isolated = tmp_path / "job_outputs"
    isolated.mkdir()
    import webapp.config as cfg
    monkeypatch.setattr(cfg, "JOB_OUTPUT_DIR", isolated)


@pytest.fixture(autouse=True)
def no_live_vendor_api():
    """Suppress live vendor API calls across all unit tests.

    pipeline_emitter does `from vendor_match_client import fetch_vendor_fields`
    (a direct import), so the patch must target the consuming module's local
    name, not the source module.
    """
    with patch(
        "webapp.deliverables.pipeline_emitter.fetch_vendor_fields",
        return_value=None,
    ):
        yield
