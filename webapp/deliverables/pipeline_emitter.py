"""Convert valve_list.csv + instrumentation_index.csv into canonical.json.

This is a pure function — no DB access, no network calls. It reads CSVs from
a job directory, maps rows to CanonicalEntity objects, builds a JobCanonical,
and writes canonical.json next to the CSVs.

Usage (later wired into pipeline_runner.py):
    from webapp.deliverables.pipeline_emitter import write_canonical_for_job
    result = write_canonical_for_job(job_dir=Path(job_output_dir), job_id=job.id)
"""

import csv
import logging
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
from webapp.deliverables.vendor_match_client import fetch_vendor_fields

log = logging.getLogger(__name__)

# Values that indicate "no real vendor information"
_EMPTY_VENDOR_VALUES = {"TBD", "LATER", "-", ""}

# Placeholder values that mean "not yet filled in"
_PLACEHOLDER_VALUES = {"TBD", "T.B.D", "N/A", "NA", "NONE", "-", ""}

# ISA 5.1 measured-variable letter (first letter of instrument type code)
_ISA_VARIABLE: Dict[str, str] = {
    "A": "Analysis", "B": "Burner/Combustion", "C": "Conductivity",
    "D": "Density", "E": "Voltage", "F": "Flow",
    "G": "Gauging/Viewing", "H": "Hand/Manual", "I": "Current",
    "J": "Power", "K": "Time/Schedule", "L": "Level",
    "M": "Moisture/Humidity", "N": "User Defined", "P": "Pressure",
    "Q": "Quantity/Totalizer", "R": "Radiation", "S": "Speed/Frequency",
    "T": "Temperature", "U": "Multivariable", "V": "Vibration",
    "W": "Weight/Force", "X": "Unclassified", "Y": "Event/State",
    "Z": "Position/Dimension",
}

# ISA 5.1 readout/output function letters (subsequent letters)
_ISA_FUNCTION: Dict[str, str] = {
    "A": "Alarm", "C": "Controller", "E": "Primary Element",
    "G": "Gauge/Glass", "H": "High", "I": "Indicator",
    "K": "Control Station", "L": "Low", "R": "Recorder",
    "S": "Switch", "T": "Transmitter", "V": "Valve/Final Element",
    "W": "Well/Thermowell", "Y": "Relay/Converter", "Z": "Driver/Actuator",
}

# Tag type codes that are always part of the Safety Instrumented System
_SIS_TYPE_CODES = {
    "PSV", "TSV", "LSV", "FSV", "PRV",        # Safety/relief valves
    "ESV", "ESD", "SDV", "BDV",               # Emergency/blowdown/shutdown valves
    "PSHH", "PSLL", "TSHH", "TSLL",           # Safety high-high / low-low switches
    "LSHH", "LSLL", "FSHH", "FSLL",
    "PAHH", "PALL", "TAHH", "TALL",
    "LAHH", "LALL", "FAHH", "FALL",
    "XV",                                      # On/off safety valve
}

_SIS_DESC_KEYWORDS = {"SAFETY", "SHUTDOWN", "EMERGENCY", "RELIEF", "INTERLOCK", "SIS", "ESD", "TRIP"}

# --- IO type classification (instrument's signal perspective) ---
# AO = instrument transmits analog signal to DCS/PLC (4-20 mA out)
# AI = instrument receives analog signal from DCS/PLC (4-20 mA in)
# DO = instrument outputs discrete/digital signal to DCS/PLC
# DI = instrument receives discrete/digital signal from DCS/PLC

# Solenoids / on-off valves / actuators: controller sends digital command → DO
_DO_TYPE_CODES = {"XV", "SDV", "ESV", "BDV", "SOV", "AOV", "MOV"}

# Safety relief valves have a position-feedback switch wired back to controller → DI
_DI_TYPE_CODES = {"PSV", "TSV", "LSV", "FSV", "PRV", "RV", "SV"}

# Last ISA function letter → IO type (from CONTROLLER perspective)
# AI = Field → Controller (analog: 4-20mA, RTD/TC)
# AO = Controller → Field (analog: 4-20mA, 0-10V)
# DI = Field → Controller (discrete: dry contact, 24VDC, NAMUR)
# DO = Controller → Field (discrete: 24VDC, 120VAC, relay)
_LAST_LETTER_IO: Dict[str, str] = {
    "T": "AI",   # Transmitter — field sends 4-20 mA to controller (AI)
    "E": "AI",   # Primary element — analog sensing input to controller
    "R": "AI",   # Recorder — receives analog from field
    "W": "AI",   # Thermowell — temperature sensing input
    "C": "AO",   # Controller output — sends 4-20 mA to control valve
    "V": "AO",   # Control valve / positioner — receives 4-20 mA from controller
    "Z": "AO",   # Actuator/Driver — receives analog from controller
    "Y": "AO",   # Relay/Converter — analog output
    "S": "DI",   # Switch — discrete contact from field to controller
    "A": "DI",   # Alarm — discrete signal from field to controller
    "H": "DI",   # High switch (FSH, PSH …) — discrete from field
    "L": "DI",   # Low switch (FSL, PSL …) — discrete from field
    "I": "",     # Indicator — local display, leave blank
    "G": "",     # Gauge/glass — local/visual, leave blank
    "K": "",     # Control station — operator interface, leave blank
}


def _classify_io_type(type_code: str) -> str:
    """Return AI / AO / DI / DO (or '') from the controller/DCS perspective.

    AI  Field → Controller  4-20mA, RTD/TC  (transmitters, sensors)
    AO  Controller → Field  4-20mA, 0-10V   (control valves, VFDs, dampers)
    DI  Field → Controller  dry contact, 24VDC, NAMUR  (switches, alarms, PSV feedback)
    DO  Controller → Field  24VDC, 120VAC, relay  (solenoids, MCC starters, horns)
    ''  Local/visual instruments with no DCS IO (indicators, gauges)

    Vendor power data refines AI↔AO distinction later (mA = analog, V = digital).
    """
    code = (type_code or "").upper().strip()
    if not code:
        return ""
    if code in _DO_TYPE_CODES:
        return "DO"
    if code in _DI_TYPE_CODES:
        return "DI"
    # Compound switch / trip codes (PSHH, FSLL, LSHH, etc.) → DI
    if code.endswith(("HH", "LL", "SH", "SL")):
        return "DI"
    return _LAST_LETTER_IO.get(code[-1], "")


def _infer_service_description(type_code: str, line_no: str, equip_no: str) -> str:
    """Build a service description from the ISA tag code + nearest line/equipment."""
    if not type_code:
        return ""
    code = type_code.upper()
    variable = _ISA_VARIABLE.get(code[0], code[0])

    func_parts: list = []
    i = 1
    while i < len(code):
        two = code[i: i + 2] if i + 1 < len(code) else ""
        if two in ("HH", "LL", "AH", "AL"):
            func_parts.append(two)
            i += 2
        else:
            fn = _ISA_FUNCTION.get(code[i], code[i])
            func_parts.append(fn)
            i += 1

    desc = " ".join([variable] + func_parts)

    context = (line_no or equip_no or "").strip()
    if context:
        desc = f"{desc} on {context}"
    return desc


def _classify_system(type_code: str, instrument_description: str) -> str:
    """Return 'SIS' or 'BPCS' for this instrument.

    SIS instruments are safety-critical — pressure/level/temp safety valves,
    emergency shutdowns, high-high / low-low trip switches.  Everything else
    defaults to BPCS (Basic Process Control System / DCS).
    """
    code = (type_code or "").upper()
    desc = (instrument_description or "").upper()

    if code in _SIS_TYPE_CODES:
        return "SIS"
    if any(kw in desc for kw in _SIS_DESC_KEYWORDS):
        return "SIS"
    # Codes ending in SHH / SLL / SH / SL are safety trip switches
    if code.endswith(("SHH", "SLL", "SH", "SL")):
        return "SIS"
    return "BPCS"


# Instrument CSV column → canonical field name.
# Keys match the ALL-CAPS headers that instrument_validator.py writes via
# InstrumentRow.to_csv_dict(). Previously used Title-Case names that never
# matched, leaving all instrument fields empty in canonical.json.
# Each canonical instrument field maps to the CSV column names that may carry it.
# TWO export schemas exist in production and both must be read:
#   * ALL-CAPS  (current pipeline output, e.g. "TAG SERVICE", "EQUIP NO")
#   * Title-Case (older MUK/Oman jobs, e.g. "Service Description", "Equipment No")
# Candidates are tried in order, so ALL-CAPS wins when both are present — this
# preserves the exact behaviour for current jobs while letting legacy jobs
# (whose only difference is the header spelling) re-emit correctly.
_INSTRUMENT_FIELD_ALIASES: Dict[str, List[str]] = {
    "instrument_type":         ["INSTRUMENT TYPE DESCRIPTION", "Instrument Type"],
    "service_description":     ["TAG SERVICE", "Service Description"],
    "line_no":                 ["LINE NUMBER", "Line No"],
    "equipment_no":            ["EQUIP NO", "Equipment No"],
    "external_power_supply":   ["POWER SUPPLY", "External Power Supply"],
    "signal_level":            ["SIGNAL VOLTAGE LEVEL", "Signal Level"],
    "location":                ["LOCATION", "Location"],
    "analog_range_low_scale":  ["RANGE MIN", "Analog Range Low"],
    "analog_range_high_scale": ["RANGE MAX", "Analog Range High"],
    "analog_range_eu":         ["RANGE UOM", "Analog Range EU"],
    "datasheet_ref":           ["DATA SHEET / REQUISITION №", "Inst. Datasheet"],
    "manufacturer":            ["MANUFACTURER", "Manufacturer"],
    "model_no":                ["MODEL", "Model No"],
    "remark":                  ["REMARKS", "Remark"],
}
# Single-purpose columns read directly (also dual-schema).
_INSTRUMENT_TAG_COLS = ["TAG NUMBER", "Tag Number"]
_INSTRUMENT_SUBCLASS_COLS = ["INSTRUMENT TYPE DESCRIPTION", "Instrument Type"]
_INSTRUMENT_PID_COLS = ["P&ID", "P&ID No"]


def _first_col(row: dict, candidates: List[str], default: str = "") -> str:
    """First present column value among candidates (handles both CSV schemas)."""
    for col in candidates:
        if col in row and row[col] is not None:
            return row[col]
    return default


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


def _sheet_from_row(row: dict) -> int:
    """Read the 1-based "Sheet" column from a CSV row.

    Returns 1 when the column is absent, blank, or non-integer — this preserves
    correctness for legacy CSVs written before the multi-page "Sheet" column was
    added (single-page jobs were always sheet 1).
    """
    raw = row.get("Sheet")
    if raw is None or str(raw).strip() == "":
        return 1
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 1


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
                    sheet_number=_sheet_from_row(row),
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
            tag = _first_col(row, _INSTRUMENT_TAG_COLS) or None

            entity_id = _make_entity_uuid(job_id, "instrument", tag, idx)

            # Build fields dict using the canonical name mapping (dual-schema)
            fields: Dict[str, str] = {}
            for field_name, candidates in _INSTRUMENT_FIELD_ALIASES.items():
                fields[field_name] = _first_col(row, candidates)

            # --- Derived fields computed from tag ---
            tag_str = tag or ""
            tag_parts = tag_str.split("-") if tag_str else []

            # Unit Number: first hyphen-segment (e.g. "62" from "62-FE-151002B")
            fields["unit_number"] = tag_parts[0] if tag_parts else ""

            # Tag type code: purely alphabetic segment (e.g. "FE", "LIC", "PZIT")
            type_code = next((p for p in tag_parts if p.isalpha()), "")
            fields["tag_type_code"] = type_code

            # Loop Number: replace type code with its first letter only
            # "62-FE-151002B" → "62-F-151002B"  |  "62-LIC-151006" → "62-L-151006"
            if type_code and type_code in tag_parts:
                loop_parts = list(tag_parts)
                loop_parts[loop_parts.index(type_code)] = type_code[0]
                fields["loop_name"] = "-".join(loop_parts)
            else:
                fields["loop_name"] = tag_str

            # Service Description: if CSV value is a placeholder or empty,
            # infer from the ISA tag code + line/equipment context.
            svc = fields.get("service_description", "").strip()
            if svc.upper() in _PLACEHOLDER_VALUES:
                fields["service_description"] = _infer_service_description(
                    type_code,
                    fields.get("line_no", ""),
                    fields.get("equipment_no", ""),
                )

            # System: classify as BPCS or SIS based on tag code + description
            fields["system"] = _classify_system(type_code, fields.get("instrument_type", ""))

            # IO type: AI / AO / DI / DO from instrument signal-flow perspective
            fields["io_type"] = _classify_io_type(type_code)

            # --- Vendor Match API enrichment ---
            # Use analog range from CSV as hints to get a tighter API match.
            api_data = fetch_vendor_fields(
                inst_type=type_code,
                range_min=fields.get("analog_range_low_scale") or None,
                range_max=fields.get("analog_range_high_scale") or None,
                range_unit=fields.get("analog_range_eu") or None,
            )

            if api_data:
                # Overwrite spec fields with API values (non-empty values only)
                for fld in (
                    "piping_class", "calb_range_min", "calb_range_max", "calb_range_unit",
                    "measuring_range_min", "measuring_range_max", "measuring_range_unit",
                    "power_in", "power_out", "io_output",
                ):
                    val = api_data.get(fld, "")
                    if val and val.upper() not in _PLACEHOLDER_VALUES:
                        fields[fld] = val

            # Build VendorMatch: prefer API data, fall back to CSV
            manufacturer = (api_data or {}).get("_manufacturer") or _first_col(row, _INSTRUMENT_FIELD_ALIASES["manufacturer"]).strip()
            model_no = (api_data or {}).get("_model_number") or _first_col(row, _INSTRUMENT_FIELD_ALIASES["model_no"]).strip()
            vendor_name = (api_data or {}).get("_vendor_name") or manufacturer

            vendor_match: Optional[VendorMatch] = None
            if manufacturer not in _EMPTY_VENDOR_VALUES and model_no not in _EMPTY_VENDOR_VALUES:
                vendor_id = uuid.uuid5(uuid.NAMESPACE_DNS, vendor_name or manufacturer)
                vendor_match = VendorMatch(
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                    product_name=model_no,
                    part_number="",
                    catalog_fields={},
                )

            entities.append(
                CanonicalEntity(
                    entity_id=entity_id,
                    entity_class="instrument",
                    sub_class=_first_col(row, _INSTRUMENT_SUBCLASS_COLS),
                    tag=tag,
                    pid_number=_first_col(row, _INSTRUMENT_PID_COLS),
                    sheet_number=_sheet_from_row(row),
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
