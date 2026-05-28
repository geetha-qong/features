import json
from pathlib import Path

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.template_loader import TemplateLoader
from webapp.deliverables.valve_list import ValveListCSVGenerator

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def test_valvelist_csv_default_template_matches_production_format():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = ValveListCSVGenerator().generate(job, tpl)
    expected = (FIXTURE_DIR / "expected_valve_list_default.csv").read_bytes()
    assert out == expected


def test_valvelist_csv_filters_to_valves_only():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = ValveListCSVGenerator().generate(job, tpl).decode("utf-8")
    assert "62-GL-151000" in out or "151000" in out
    assert "62-BV-151001" in out or "151001" in out
    assert "422-11-PT-006A" not in out
    assert "V-101" not in out


def test_valvelist_csv_preserves_trailing_space_in_pneumatic_actuator_header():
    """Production header "Pneumatic Actuator " has a trailing space. Some agency
    tooling parses by exact column name. Must be preserved verbatim."""
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = ValveListCSVGenerator().generate(job, tpl).decode("utf-8")
    header_line = out.splitlines()[0]
    assert "Pneumatic Actuator " in header_line  # note trailing space
    assert "Pneumatic Actuator," not in header_line  # the no-space version must NOT appear


def test_valvelist_csv_class_attrs():
    assert ValveListCSVGenerator.deliverable_type == "valve_list"
    assert ValveListCSVGenerator.file_format == "csv"
