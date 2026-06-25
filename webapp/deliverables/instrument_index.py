"""Instrument Index deliverable generators (CSV + XLSX)."""

import csv
import io as _io
from typing import ClassVar, List

from openpyxl import Workbook
from openpyxl.styles import Font

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_instruments(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "instrument"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class InstrumentIndexCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "instrument_index"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["instrument_index"]
        columns = _ordered_columns(deliv)
        instruments = _filter_instruments(canonical.entities)
        buf = _io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.header for c in columns])
        for e in instruments:
            writer.writerow([resolve_field(e, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


class InstrumentIndexXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "instrument_index"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["instrument_index"]
        columns = _ordered_columns(deliv)
        instruments = _filter_instruments(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Instrument Index"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for e in instruments:
            ws.append([resolve_field(e, c.field) for c in columns])
        out = _io.BytesIO()
        wb.save(out)
        return out.getvalue()


REGISTRY.register(InstrumentIndexCSVGenerator)
REGISTRY.register(InstrumentIndexXLSXGenerator)
