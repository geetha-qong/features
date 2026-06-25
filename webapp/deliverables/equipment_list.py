"""Equipment List deliverable generator (XLSX)."""

import io as _io
from typing import ClassVar, List

from openpyxl import Workbook
from openpyxl.styles import Font

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import DeliverableConfig, TemplateConfig


def _filter_equipment(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    return [e for e in entities if e.entity_class == "equipment"]


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


class EquipmentListXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "equipment_list"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["equipment_list"]
        columns = _ordered_columns(deliv)
        equipment = _filter_equipment(canonical.entities)
        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Equipment List"
        ws.append([c.header for c in columns])
        header_font = Font(name=deliv.font, bold=True)
        for cell in ws[1]:
            cell.font = header_font
        for e in equipment:
            ws.append([resolve_field(e, c.field) for c in columns])
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


REGISTRY.register(EquipmentListXLSXGenerator)
