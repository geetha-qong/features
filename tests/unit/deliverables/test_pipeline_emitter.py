import csv
import json
from pathlib import Path

import pytest

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.pipeline_emitter import (
    write_canonical_for_job,
    EmitResult,
)


def _write_valve_csv(path: Path) -> None:
    rows = [
        ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line'],
        ['MUK-62-1-15-1001-001-24C7-D','-','GL','8','62','151000','-','G','AC-PP','1','-','-','-','8"-G-62151004-AC-PP'],
        ['MUK-62-1-15-1001-001-24C7-D','-','BV','2','62','151001','-','LO','AC','1','-','-','-','2"-LO-62151004-AC'],
    ]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_instrument_csv(path: Path) -> None:
    headers = ['Rev No','Unit Number','Loop Name','Tag Number','Instrument Type','Service Description','P&ID No','Line No','Equipment No','Location','System','Technical Room','IO Type','Signal Type','Signal Level','IO Grouping','External Power Supply','Analog Range Low','Analog Range High','Analog Range EU','HH Alarm Limit','H Alarm Limit','L Alarm Limit','LL Alarm Limit','Junction Box/Panel','Multi-Cable Pair No','Manufacturer','Model No','Inst. Datasheet','Hook-up Drawing','Remark']
    rows = [
        headers,
        ['0','422-11','422-11-P-006','422-11-PT-006A','PT','COMP SUCTION PRESS','VEN-M5BC-6-50-0002','LATER','422-11-K-001A','FIELD','UCP','','AI','4-20mA','','','','0','150','bar','-','-','-','-','','','Yokogawa','EJX130A','','',''],
        ['0','422-11','422-11-AIT-0001','422-11-AIT-0001','AIT','Nitrates','WS-25-WTP-01','','','TBD','','TBD','TBD','TBD','TBD','TBD','TBD','TBD','TBD','TBD','-','-','-','-','TBD','TBD','TBD','TBD','LATER','LATER','TBD'],
    ]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def _write_valve_csv_with_sheet(path: Path) -> None:
    """valve_list.csv WITH the multi-page 'Sheet' column (1-based)."""
    rows = [
        ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line','Sheet'],
        ['MUK','-','GL','8','62','151000','-','G','AC-PP','1','-','-','-','8"-G-62151004-AC-PP','1'],
        ['MUK','-','BV','2','62','151001','-','LO','AC','1','-','-','-','2"-LO-62151004-AC','3'],
    ]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def test_emit_valves_with_sheet_column(tmp_path):
    """valve_list.csv WITH a 'Sheet' column → entities carry the right sheet_number."""
    job_dir = tmp_path / "50"
    job_dir.mkdir()
    _write_valve_csv_with_sheet(job_dir / "valve_list.csv")

    result = write_canonical_for_job(job_dir=job_dir, job_id=50)
    job = JobCanonical.model_validate(json.loads(result.canonical_path.read_text()))
    sheets = {e.tag: e.sheet_number for e in job.entities}
    assert sheets["62-GL-151000"] == 1
    assert sheets["62-BV-151001"] == 3


def test_emit_valves_without_sheet_column_defaults_to_1(tmp_path):
    """Legacy valve_list.csv WITHOUT a 'Sheet' column → sheet_number defaults to 1."""
    job_dir = tmp_path / "51"
    job_dir.mkdir()
    _write_valve_csv(job_dir / "valve_list.csv")  # no Sheet column

    result = write_canonical_for_job(job_dir=job_dir, job_id=51)
    job = JobCanonical.model_validate(json.loads(result.canonical_path.read_text()))
    assert job.entities  # sanity
    for e in job.entities:
        assert e.sheet_number == 1


def _write_instrument_csv_with_sheet(path: Path, sheet: str) -> None:
    """instrumentation_index.csv (emitter schema) WITH a 'Sheet' column."""
    headers = ['TAG NUMBER','INSTRUMENT TYPE DESCRIPTION','P&ID','Sheet']
    rows = [headers, ['422-11-PT-006A','PT','VEN-M5BC-6-50-0002', sheet]]
    with path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def test_emit_instruments_with_sheet_column(tmp_path):
    """instrumentation_index.csv WITH a 'Sheet' column → sheet_number honoured."""
    job_dir = tmp_path / "52"
    job_dir.mkdir()
    _write_instrument_csv_with_sheet(job_dir / "instrumentation_index.csv", "4")

    result = write_canonical_for_job(job_dir=job_dir, job_id=52)
    job = JobCanonical.model_validate(json.loads(result.canonical_path.read_text()))
    instruments = [e for e in job.entities if e.entity_class == "instrument"]
    assert instruments
    assert all(e.sheet_number == 4 for e in instruments)


def test_emit_instruments_without_sheet_column_defaults_to_1(tmp_path):
    """Legacy instrumentation_index.csv WITHOUT 'Sheet' → sheet_number defaults to 1."""
    job_dir = tmp_path / "53"
    job_dir.mkdir()
    _write_instrument_csv(job_dir / "instrumentation_index.csv")  # no Sheet column

    result = write_canonical_for_job(job_dir=job_dir, job_id=53)
    job = JobCanonical.model_validate(json.loads(result.canonical_path.read_text()))
    instruments = [e for e in job.entities if e.entity_class == "instrument"]
    assert instruments
    for e in instruments:
        assert e.sheet_number == 1


def test_emit_valves_only(tmp_path):
    """If only valve_list.csv exists, canonical.json has only valve entities."""
    job_dir = tmp_path / "42"
    job_dir.mkdir()
    _write_valve_csv(job_dir / "valve_list.csv")

    result = write_canonical_for_job(job_dir=job_dir, job_id=42)
    assert isinstance(result, EmitResult)
    assert result.canonical_path == job_dir / "canonical.json"
    assert result.canonical_path.exists()

    data = json.loads(result.canonical_path.read_text())
    job = JobCanonical.model_validate(data)
    assert job.job_id == 42
    assert job.canonical_schema_version == "1.0.0"
    assert len(job.entities) == 2
    for e in job.entities:
        assert e.entity_class == "valve"
    first = job.entities[0]
    assert first.sub_class == "GL"
    assert first.tag == "62-GL-151000"
    assert first.fields["pneumatic_actuator"] == "-"
    assert first.fields["line"] == '8"-G-62151004-AC-PP'


def test_emit_instruments_with_synthetic_vendor_match(tmp_path):
    """Instrument with real Manufacturer + Model gets a synthetic VendorMatch.
    Instrument with TBD/blank gets vendor_match=None."""
    job_dir = tmp_path / "43"
    job_dir.mkdir()
    _write_instrument_csv(job_dir / "instrumentation_index.csv")

    result = write_canonical_for_job(job_dir=job_dir, job_id=43)
    data = json.loads(result.canonical_path.read_text())
    job = JobCanonical.model_validate(data)
    instruments = [e for e in job.entities if e.entity_class == "instrument"]
    assert len(instruments) == 2

    # First instrument: Yokogawa + EJX130A → stored in fields (vendor_match is set via UI)
    pt = next(e for e in instruments if e.tag == "422-11-PT-006A")
    assert pt.vendor_match is None  # vendor_match only set via UI acceptance
    assert pt.fields.get("manufacturer") == "Yokogawa"
    assert pt.fields.get("model_no") == "EJX130A"
    assert pt.fields["loop_name"] == "422-11-P-006A"  # derived from tag (PT→P, suffix kept)
    assert pt.fields["instrument_type"] == "PT"
    assert pt.fields["service_description"] == "COMP SUCTION PRESS"
    assert pt.fields["signal_type"] == "4-20mA"

    # Second instrument: Manufacturer=TBD → no vendor_match
    ait = next(e for e in instruments if e.tag == "422-11-AIT-0001")
    assert ait.vendor_match is None


def test_emit_both_csvs_combined(tmp_path):
    """When both CSVs exist, canonical.json has both valve + instrument entities."""
    job_dir = tmp_path / "44"
    job_dir.mkdir()
    _write_valve_csv(job_dir / "valve_list.csv")
    _write_instrument_csv(job_dir / "instrumentation_index.csv")

    result = write_canonical_for_job(job_dir=job_dir, job_id=44)
    data = json.loads(result.canonical_path.read_text())
    job = JobCanonical.model_validate(data)
    classes = sorted({e.entity_class for e in job.entities})
    assert classes == ["instrument", "valve"]
    assert len([e for e in job.entities if e.entity_class == "valve"]) == 2
    assert len([e for e in job.entities if e.entity_class == "instrument"]) == 2


def test_emit_empty_job_dir(tmp_path):
    """No CSVs in job dir → canonical.json with empty entities list (still written)."""
    job_dir = tmp_path / "45"
    job_dir.mkdir()

    result = write_canonical_for_job(job_dir=job_dir, job_id=45)
    data = json.loads(result.canonical_path.read_text())
    job = JobCanonical.model_validate(data)
    assert job.entities == []


def test_emit_is_deterministic(tmp_path):
    """Re-running on the same input produces byte-identical canonical.json."""
    job_dir = tmp_path / "46"
    job_dir.mkdir()
    _write_valve_csv(job_dir / "valve_list.csv")

    write_canonical_for_job(job_dir=job_dir, job_id=46)
    first = (job_dir / "canonical.json").read_bytes()
    write_canonical_for_job(job_dir=job_dir, job_id=46)
    second = (job_dir / "canonical.json").read_bytes()
    assert first == second


def test_emit_customer_template_slug_param(tmp_path):
    """Caller can pass a template slug (otherwise defaults to 'default')."""
    job_dir = tmp_path / "47"
    job_dir.mkdir()
    _write_valve_csv(job_dir / "valve_list.csv")

    write_canonical_for_job(job_dir=job_dir, job_id=47, customer_template_slug="muk")
    data = json.loads((job_dir / "canonical.json").read_text())
    assert data["customer_template_slug"] == "muk"
