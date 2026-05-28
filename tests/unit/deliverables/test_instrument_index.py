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


def test_instrumentindex_default_has_32_columns():
    """Matches the TNB customer Instrument Index sample column count."""
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl).decode("utf-8")
    header = out.splitlines()[0]
    assert len(header.split(",")) == 32


def test_instrumentindex_filters_to_instruments():
    job = load_sample()
    tpl = TemplateLoader().load("default")
    out = InstrumentIndexCSVGenerator().generate(job, tpl).decode("utf-8")
    assert "422-11-PT-006A" in out
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
