"""The instrument emitter must read BOTH production CSV header schemas.

Two instrumentation_index.csv schemas exist in the wild:
  * ALL-CAPS   (current pipeline output): "TAG NUMBER", "TAG SERVICE", "EQUIP NO" ...
  * Title-Case (older MUK/Oman jobs):     "Tag Number", "Service Description", "Equipment No" ...

A prior change swapped the field map from Title-Case to ALL-CAPS, which silently
made the legacy Title-Case jobs re-emit with empty instrument fields. The emitter
now accepts either spelling (ALL-CAPS wins when both are present).
"""
import json
from pathlib import Path

from webapp.deliverables.pipeline_emitter import write_canonical_for_job

TITLE_CASE = (
    "Tag Number,Instrument Type,Service Description,P&ID No,Line No,"
    "Equipment No,Location,Manufacturer,Model No,Remark\r\n"
    "62-FE-151003,FE,COOLING WATER FLOW,MUK-62-1-15-1003-001-24C7-D,"
    "16-W-62151013-BGA,62-P-151003,FIELD,Endress,Promag,note1\r\n"
)

ALL_CAPS = (
    "TAG NUMBER,INSTRUMENT TYPE DESCRIPTION,TAG SERVICE,P&ID,LINE NUMBER,"
    "EQUIP NO,LOCATION,MANUFACTURER,MODEL,REMARKS\r\n"
    "62-AE-151008,ANALYSER ELEMENT,PW PUMP ANALYSER,MUK-62-1004,NA,"
    "62-P-151005,FIELD,Yokogawa,EXA,r\r\n"
)


def _emit(tmp_path: Path, csv_text: str) -> dict:
    (tmp_path / "instrumentation_index.csv").write_text(csv_text, encoding="utf-8")
    write_canonical_for_job(job_dir=tmp_path, job_id=1)
    data = json.loads((tmp_path / "canonical.json").read_text(encoding="utf-8"))
    insts = [e for e in data["entities"] if e["entity_class"] == "instrument"]
    assert len(insts) == 1
    return insts[0]


def test_title_case_schema_populates_fields(tmp_path):
    e = _emit(tmp_path, TITLE_CASE)
    assert e["tag"] == "62-FE-151003"
    assert e["sub_class"] == "FE"
    assert e["pid_number"] == "MUK-62-1-15-1003-001-24C7-D"
    f = e["fields"]
    assert f["service_description"] == "COOLING WATER FLOW"
    assert f["equipment_no"] == "62-P-151003"
    assert f["line_no"] == "16-W-62151013-BGA"
    assert f["location"] == "FIELD"
    assert f["manufacturer"] == "Endress"
    assert f["model_no"] == "Promag"


def test_all_caps_schema_still_populates_fields(tmp_path):
    """Regression: the current ALL-CAPS path must be unchanged."""
    e = _emit(tmp_path, ALL_CAPS)
    assert e["tag"] == "62-AE-151008"
    assert e["sub_class"] == "ANALYSER ELEMENT"
    assert e["pid_number"] == "MUK-62-1004"
    f = e["fields"]
    assert f["service_description"] == "PW PUMP ANALYSER"
    assert f["equipment_no"] == "62-P-151005"
    assert f["location"] == "FIELD"
    assert f["manufacturer"] == "Yokogawa"
    assert f["model_no"] == "EXA"
