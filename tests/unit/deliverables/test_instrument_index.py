import io
import json
from pathlib import Path

import openpyxl

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.instrument_index import (
    InstrumentIndexCSVGenerator,
    InstrumentIndexXLSXGenerator,
)
from webapp.deliverables.template_loader import TemplateLoader

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_sample() -> JobCanonical:
    raw = json.loads((FIXTURE_DIR / "canonical_sample.json").read_text())
    return JobCanonical.model_validate(raw)


def test_instrumentindex_csv_default():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl)
    expected = (FIXTURE_DIR / "expected_instrument_index_default.csv").read_bytes()
    assert out == expected


def test_instrumentindex_default_has_36_columns():
    """Default Instrument Index column count.

    Started at 32 (TNB customer sample); grew to 35 with the vendor-match
    enrichment columns; 36 when the Process Function (sub_class) column was
    added at the front (FEATURES #117). The Tag No. column already existed.
    """
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl).decode("utf-8")
    header = out.splitlines()[0]
    cols = header.split(",")
    assert len(cols) == 36
    assert cols[0] == "Process Function"


def test_instrumentindex_filters_to_instruments():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl).decode("utf-8")
    # Loop-centric format: no raw tag column — the PT-006A instrument is
    # identified by its loop number (instance suffix dropped) + service.
    assert "422-11-P-006" in out
    assert "COMP SUCTION PRESS" in out
    assert "Yokogawa" in out  # vendor manufacturer appears
    assert "62-GL-151000" not in out
    assert "V-101" not in out


def test_instrumentindex_xlsx_sheet_name():
    job = load_sample()
    tpl = TemplateLoader().load("ronesans")
    out_bytes = InstrumentIndexXLSXGenerator().generate(job, tpl)
    wb = openpyxl.load_workbook(io.BytesIO(out_bytes))
    assert "INSTRUMENT INDEX" in wb.sheetnames


def test_instrumentindex_class_attrs():
    assert InstrumentIndexCSVGenerator.deliverable_type == "instrument_index"
    assert InstrumentIndexCSVGenerator.file_format == "csv"
    assert InstrumentIndexXLSXGenerator.file_format == "xlsx"
