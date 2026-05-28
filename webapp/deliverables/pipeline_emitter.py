"""Convert valve_list.csv + instrumentation_index.csv into canonical.json.

This is a pure function — no DB access, no network calls. It reads CSVs from
a job directory, maps rows to CanonicalEntity objects, builds a JobCanonical,
and writes canonical.json next to the CSVs.

Usage (later wired into pipeline_runner.py):
    from webapp.deliverables.pipeline_emitter import write_canonical_for_job
    result = write_canonical_for_job(job_dir=Path(job_output_dir), job_id=job.id)
"""

import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from webapp.deliverables.canonical import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalEntity,
    JobCanonical,
    VendorMatch,
)

# Values that indicate "no real vendor information"
_EMPTY_VENDOR_VALUES = {"TBD", "LATER", "-", ""}

# Instrument CSV column → canonical field name
_INSTRUMENT_FIELD_MAP: Dict[str, str] = {
    "Rev No": "rev_no",
    "Unit Number": "unit_number",
    "Loop Name": "loop_name",
    "Tag Number": "tag_number",
    "Instrument Type": "instrument_type",
    "Service Description": "service_description",
    "P&ID No": "pid_number",
    "Line No": "line_no",
    "Equipment No": "equipment_no",
    "Location": "location",
    "System": "system",
    "Technical Room": "technical_room",
    "IO Type": "io_type",
    "Signal Type": "signal_type",
    "Signal Level": "signal_level",
    "IO Grouping": "io_grouping",
    "External Power Supply": "external_power_supply",
    "Analog Range Low": "analog_range_low_scale",
    "Analog Range High": "analog_range_high_scale",
    "Analog Range EU": "analog_range_eu",
    "HH Alarm Limit": "alarm_high_high",
    "H Alarm Limit": "alarm_high",
    "L Alarm Limit": "alarm_low",
    "LL Alarm Limit": "alarm_low_low",
    "Junction Box/Panel": "junction_box_panel",
    "Multi-Cable Pair No": "multi_cable_pair_no",
    "Manufacturer": "manufacturer",
    "Model No": "model_no",
    "Inst. Datasheet": "datasheet_ref",
    "Hook-up Drawing": "hookup_drawing",
    "Remark": "remark",
}


@dataclass
class EmitResult:
    """Result of a write_canonical_for_job call."""

    canonical_path: Path
    valve_count: int
    instrument_count: int


def _make_entity_uuid(job_id: int, entity_class: str, tag: Optional[str], idx: int) -> uuid.UUID:
    """Deterministic UUID5 for a canonical entity."""
    key = f"{job_id}:{entity_class}:{tag or ''}:{idx}"
    return uuid.uuid5(uuid.NAMESPACE_DNS, key)


def _build_valve_entities(valve_csv: Path, job_id: int) -> List[CanonicalEntity]:
    """Parse valve_list.csv and return a list of CanonicalEntity objects."""
    entities: List[CanonicalEntity] = []
    with valve_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            area = (row.get("Area Code") or "").strip()
            category = (row.get("Category") or "").strip()
            serial = (row.get("Serial No") or "").strip()

            # Compose tag only when all parts are present
            if area and category and serial:
                tag: Optional[str] = f"{area}-{category}-{serial}"
            else:
                tag = None

            entity_id = _make_entity_uuid(job_id, "valve", tag, idx)

            fields = {
                "dynamic_code": row.get("Dynamic Code", ""),
                "category": row.get("Category", ""),
                "size": row.get("Size", ""),
                "area_code": row.get("Area Code", ""),
                "serial_no": row.get("Serial No", ""),
                "series_code": row.get("Series Code", ""),
                "fluid_code": row.get("Fluid Code", ""),
                "piping_class": row.get("Piping Class", ""),
                "qty": row.get("Qty", ""),
                "motor_actuator": row.get("Motor Actuator", ""),
                # Note: trailing space in CSV header
                "pneumatic_actuator": row.get("Pneumatic Actuator ", ""),
                "solenoid": row.get("Solenoid", ""),
                "line": row.get("line", ""),
            }

            entities.append(
                CanonicalEntity(
                    entity_id=entity_id,
                    entity_class="valve",
                    sub_class=category,
                    tag=tag,
                    pid_number=row.get("P&ID No", ""),
                    sheet_number=1,
                    bbox=(0.0, 0.0, 0.0, 0.0),
                    fields=fields,
                    vendor_match=None,
                )
            )
    return entities


def _build_instrument_entities(instrument_csv: Path, job_id: int) -> List[CanonicalEntity]:
    """Parse instrumentation_index.csv and return a list of CanonicalEntity objects."""
    entities: List[CanonicalEntity] = []
    with instrument_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            tag = row.get("Tag Number") or None

            entity_id = _make_entity_uuid(job_id, "instrument", tag, idx)

            # Build fields dict using the canonical name mapping
            fields: Dict[str, str] = {}
            for csv_col, field_name in _INSTRUMENT_FIELD_MAP.items():
                fields[field_name] = row.get(csv_col, "")

            # Synthesize VendorMatch only when Manufacturer + Model No are real values
            manufacturer = (row.get("Manufacturer") or "").strip()
            model_no = (row.get("Model No") or "").strip()
            vendor_match: Optional[VendorMatch] = None
            if manufacturer not in _EMPTY_VENDOR_VALUES and model_no not in _EMPTY_VENDOR_VALUES:
                vendor_id = uuid.uuid5(uuid.NAMESPACE_DNS, manufacturer)
                vendor_match = VendorMatch(
                    vendor_id=vendor_id,
                    vendor_name=manufacturer,
                    product_name=model_no,
                    part_number="",
                    catalog_fields={},
                )

            entities.append(
                CanonicalEntity(
                    entity_id=entity_id,
                    entity_class="instrument",
                    sub_class=row.get("Instrument Type", ""),
                    tag=tag,
                    pid_number=row.get("P&ID No", ""),
                    sheet_number=1,
                    bbox=(0.0, 0.0, 0.0, 0.0),
                    fields=fields,
                    vendor_match=vendor_match,
                )
            )
    return entities


def write_canonical_for_job(
    job_dir: Path,
    job_id: int,
    customer_template_slug: str = "default",
) -> EmitResult:
    """Convert CSVs in job_dir into canonical.json.

    Reads valve_list.csv and instrumentation_index.csv if present (missing files
    are silently skipped — no exception raised). Writes canonical.json into the
    same directory and returns an EmitResult.

    Args:
        job_dir: Directory containing the CSVs (and where canonical.json is written).
        job_id: Numeric job ID stored in JobCanonical.job_id.
        customer_template_slug: Identifies which customer template is in use.

    Returns:
        EmitResult with the path to the written canonical.json.
    """
    entities: List[CanonicalEntity] = []

    valve_csv = job_dir / "valve_list.csv"
    if valve_csv.exists():
        entities.extend(_build_valve_entities(valve_csv, job_id))

    instrument_csv = job_dir / "instrumentation_index.csv"
    if instrument_csv.exists():
        entities.extend(_build_instrument_entities(instrument_csv, job_id))

    job_canonical = JobCanonical(
        job_id=job_id,
        canonical_schema_version=CANONICAL_SCHEMA_VERSION,
        customer_template_slug=customer_template_slug,
        entities=entities,
    )

    canonical_path = job_dir / "canonical.json"
    canonical_path.write_text(job_canonical.model_dump_json(indent=2), encoding="utf-8")

    valve_count = sum(1 for e in entities if e.entity_class == "valve")
    instrument_count = sum(1 for e in entities if e.entity_class == "instrument")

    return EmitResult(
        canonical_path=canonical_path,
        valve_count=valve_count,
        instrument_count=instrument_count,
    )
