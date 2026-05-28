"""Valve List deliverable generators (CSV + XLSX)."""

import csv
import io as _io  # avoid shadowing local 'io' usage in functions
from typing import ClassVar, List

from openpyxl import Workbook
from openpyxl.styles import Font

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_valves(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "valve"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class ValveListCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["valve_list"]
        columns = _ordered_columns(deliv)
        valves = _filter_valves(canonical.entities)
        buf = _io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([c.header for c in columns])
        for v in valves:
            writer.writerow([resolve_field(v, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


class ValveListXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "valve_list"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["valve_list"]
        columns = _ordered_columns(deliv)
        valves = _filter_valves(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Valve List"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for v in valves:
            ws.append([resolve_field(v, c.field) for c in columns])
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


REGISTRY.register(ValveListCSVGenerator)
REGISTRY.register(ValveListXLSXGenerator)
