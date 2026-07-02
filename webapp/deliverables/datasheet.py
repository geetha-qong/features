"""Instrument Datasheet deliverable generator (XLSX, sectioned).

Output structure matches the customer reference 23E065AJ01_ASV_IDS.xlsx:
- One sheet per instrument, sheet name = instrument tag.
- 11 industry-standard IDS sections, each with a merged-cell header.
- Within each section: column A = field number, column B = field name,
  column C = value (resolved from the canonical entity via dot notation).

The section structure (IDS_SECTIONS) is intentionally hardcoded — these are
industry-standard sections defined per ISA/IEC conventions. Per-customer
variations land as template overrides in v1.5.
"""

import io
from typing import ClassVar, List, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.ids_schema import (
    get_ids_sections_for_type,
    normalize_subclass,
)
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.template import TemplateConfig

# IDS_SECTIONS: list of (section_name, [(field_label, canonical_path), ...]).
# Field labels are the human-readable names shown in the XLSX; canonical paths
# are dot-notation lookups against CanonicalEntity (see field_resolver.py).
IDS_SECTIONS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("General Data", [
        ("Tag Number", "tag"),
        ("Service", "fields.service_description"),
        ("P&ID No.", "pid_number"),
        ("Line Number", "fields.line_no"),
        ("SIL Level Required", "fields.ids_sil_level_required"),
        ("Nace Applicable", "fields.ids_nace_applicable"),
    ]),
    ("Inlet line", [
        ("Line Size", "fields.ids_inlet_line_size"),
        ("Line Material", "fields.ids_inlet_line_material"),
        ("Piping Class", "fields.ids_inlet_line_class"),
    ]),
    ("Outlet line", [
        ("Line Size", "fields.ids_outlet_line_size"),
        ("Line Material", "fields.ids_outlet_line_material"),
        ("Piping Class", "fields.ids_outlet_line_class"),
    ]),
    ("Operating Conditions", [
        ("Fluid", "fields.ids_fluid"),
        ("Phase", "fields.ids_phase"),
    ]),
    ("Calculation Results", [
        ("Required CV", "fields.ids_required_cv"),
        ("Selected CV", "fields.ids_selected_cv"),
    ]),
    ("Valve Body", [
        ("Body Type", "vendor_match.catalog_fields.ids_body_type"),
        ("Body Material", "vendor_match.catalog_fields.body_material"),
        ("Design Pressure Max", "fields.ids_design_pressure_max"),
        ("Design Pressure Unit", "fields.ids_design_pressure_unit"),
        ("Design Temperature Max", "fields.ids_design_temperature_max"),
        ("Design Temperature Unit", "fields.ids_design_temperature_unit"),
    ]),
    ("Actuator", [
        ("Actuator Type", "vendor_match.catalog_fields.ids_actuator_type"),
        ("Supply Pressure", "vendor_match.catalog_fields.ids_actuator_supply"),
    ]),
    ("Positioner", [
        ("Input Signal", "vendor_match.catalog_fields.ids_input_signal"),
        ("Electrical Connection", "vendor_match.catalog_fields.ids_electrical_connection"),
        ("Enclosure Protection", "vendor_match.catalog_fields.ids_enclosure_protection"),
    ]),
    ("Accessories", [
        ("Handwheel", "vendor_match.catalog_fields.ids_handwheel"),
        ("Solenoid Valve", "vendor_match.catalog_fields.ids_solenoid_valve"),
    ]),
    ("Position Transmitter", [
        ("Position Transmitter Tag", "fields.ids_position_transmitter_tag"),
        ("Air Volume Tank", "fields.ids_air_volume_tank"),
    ]),
    ("Purchase", [
        ("Manufacturer", "vendor_match.vendor_name"),
        ("Model No.", "vendor_match.product_name"),
        ("Part Number", "vendor_match.part_number"),
    ]),
]

SECTION_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")


def _filter_datasheet_entities(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    """Entities that get a datasheet sheet.

    Includes every instrument plus the datasheet-bearing valves — control
    valves and relief/safety valves (entity_class == "valve" with a sub_class
    that normalizes to a known IDS type: CV / PT / PSV).
    """
    return [
        e
        for e in entities
        if normalize_subclass(e.sub_class) is not None or e.entity_class == "instrument"
    ]


# Backwards-compat alias — older callers/tests import the previous name.
_filter_instruments = _filter_datasheet_entities


def _sheet_name_for(entity: CanonicalEntity) -> str:
    """Excel sheet names: max 31 chars, no [ ] : * ? / \\."""
    raw = entity.tag or str(entity.entity_id)
    safe = "".join(c if c not in "[]:*?/\\" else "_" for c in raw)
    return safe[:31]


class DatasheetXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "datasheet"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        entities = _filter_datasheet_entities(canonical.entities)
        deliv = template.deliverables.get("datasheet")
        font_name = (deliv.font if deliv else None) or "Calibri"

        wb = Workbook()
        wb.remove(wb.active)  # remove default empty sheet

        if not entities:
            wb.create_sheet("Datasheet")  # empty placeholder if no entities

        for entity in entities:
            ws = wb.create_sheet(_sheet_name_for(entity))
            ws.column_dimensions["A"].width = 6
            ws.column_dimensions["B"].width = 32
            ws.column_dimensions["C"].width = 40

            row = 1
            # Title row (merged A:C)
            ws.cell(row=row, column=1, value=f"Instrument Datasheet — {entity.tag or ''}")
            ws.cell(row=row, column=1).font = Font(name=font_name, bold=True, size=14)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
            row += 2  # blank gap after title

            # Per-entity section set, dispatched on its sub_class.
            sections = get_ids_sections_for_type(entity.sub_class)

            field_num = 1
            for section in sections:
                # Section header row (merged A:C, bold, grey fill)
                ws.cell(row=row, column=1, value=section.name)
                ws.cell(row=row, column=1).font = Font(name=font_name, bold=True)
                ws.cell(row=row, column=1).fill = SECTION_FILL
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
                row += 1

                for field in section.fields:
                    ws.cell(row=row, column=1, value=field_num)
                    ws.cell(row=row, column=2, value=field.header)
                    ws.cell(row=row, column=2).font = Font(name=font_name)
                    ws.cell(row=row, column=3, value=resolve_field(entity, field.path))
                    ws.cell(row=row, column=3).font = Font(name=font_name)
                    ws.cell(row=row, column=3).alignment = Alignment(wrap_text=True)
                    row += 1
                    field_num += 1

                row += 1  # blank row between sections

        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()


REGISTRY.register(DatasheetXLSXGenerator)
