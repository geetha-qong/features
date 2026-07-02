"""Locate and load the canonical JSON for a job, alongside its CSV output."""

import json
import os
from pathlib import Path

from webapp.deliverables.canonical import JobCanonical


class JobCanonicalNotFound(FileNotFoundError):
    pass


def canonical_path_for_job(output_csv_path: str) -> str:
    """Map a job's existing output_csv_path to its canonical.json sibling."""
    parent = Path(output_csv_path).parent
    return str(parent / "canonical.json")


def load_canonical_for_job(output_csv_path: str) -> JobCanonical:
    """Load and parse canonical.json that sits next to the job's CSV output.

    Raises JobCanonicalNotFound if the file does not exist.
    """
    path = canonical_path_for_job(output_csv_path)
    if not os.path.exists(path):
        raise JobCanonicalNotFound(path)
    raw = json.loads(Path(path).read_text())
    if "entities" in raw:
        raw["entities"] = [e for e in raw["entities"] if e.get("entity_class") in ("valve", "instrument", "equipment")]
    return JobCanonical.model_validate(raw)
