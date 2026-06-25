import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from webapp.deliverables.canonical import CanonicalEntity, JobCanonical, VendorMatch

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_jobcanonical_parses_sample_fixture():
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    job = JobCanonical.model_validate(raw)
    assert job.job_id == 41
    assert job.canonical_schema_version == "1.0.0"
    assert job.customer_template_slug == "default"
    assert len(job.entities) == 4
    valves = [e for e in job.entities if e.entity_class == "valve"]
    assert len(valves) == 2
    first_valve = valves[0]
    assert first_valve.tag == "62-GL-151000"
    assert first_valve.fields["category"] == "GL"
    assert first_valve.fields["size"] == "8"
    instr = next(e for e in job.entities if e.entity_class == "instrument")
    assert instr.tag == "422-11-PT-006A"
    assert instr.fields["loop_name"] == "422-11-P-006"
    assert instr.vendor_match is not None
    assert instr.vendor_match.vendor_name == "Yokogawa"
    equipment = next(e for e in job.entities if e.entity_class == "equipment")
    assert equipment.tag == "V-101"


def test_jobcanonical_rejects_unknown_entity_class():
    bad = {
        "job_id": 1,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [
            {
                "entity_id": "00000000-0000-0000-0000-000000000001",
                "entity_class": "alien",
                "sub_class": "ufo",
                "tag": "X-1",
                "pid_number": "P-001",
                "sheet_number": 1,
                "bbox": [0, 0, 10, 10],
                "fields": {},
            }
        ],
    }
    with pytest.raises(ValidationError):
        JobCanonical.model_validate(bad)


def test_canonicalentity_optional_vendormatch():
    entity = CanonicalEntity(
        entity_id="00000000-0000-0000-0000-000000000002",
        entity_class="valve",
        sub_class="gate_valve",
        tag="GV-002",
        pid_number="P-001",
        sheet_number=1,
        bbox=(0, 0, 10, 10),
        fields={"size": "2in"},
    )
    assert entity.vendor_match is None
