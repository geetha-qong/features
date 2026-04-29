"""
Stage 5b parser: raw instrument extractions → InstrumentRow dataclass → 30-column index.

Tag format supported:
  {UnitPrefix}-{TypeCode}-{Serial}{Suffix}  e.g. 422-11-PT-006A
  {TypeCode}-{Serial}{Suffix}               e.g. PT-006A, PDT-101
  {AreaCode}-{TypeCode}-{Serial}{Suffix}    e.g. 10-PT-001A
"""
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Type code lookup ───────────────────────────────────────────────────────────

# Maps type_code → (instrument_type_name, io_type, signal_type)
TYPE_MAP = {
    "PT":   ("Pressure Transmitter",               "AI", "4-20mA HART"),
    "PIT":  ("Pressure Indicator Transmitter",     "AI", "4-20mA HART"),
    "PI":   ("Pressure Indicator",                 "NA", "NA"),
    "TT":   ("Temperature Transmitter",            "AI", "4-20mA HART"),
    "TIT":  ("Temperature Indicator Transmitter",  "AI", "4-20mA HART"),
    "TI":   ("Temperature Indicator",              "NA", "NA"),
    "TE":   ("Temperature Element",                "AI", "RTD RESISTANCE"),
    "TW":   ("Thermowell",                         "NA", "NA"),
    "TG":   ("Temperature Gauge",                  "NA", "NA"),
    "FT":   ("Flow Transmitter",                   "AI", "4-20mA HART"),
    "FIT":  ("Flow Indicator Transmitter",         "AI", "4-20mA HART"),
    "FI":   ("Flow Indicator",                     "NA", "NA"),
    "PDT":  ("Diff. Pressure Transmitter",         "AI", "4-20mA HART"),
    "PDIT": ("Diff. Pressure Indicator Transmitter","AI","4-20mA HART"),
    "PDI":  ("Diff. Pressure Indicator",           "NA", "NA"),
    "LT":   ("Level Transmitter",                  "AI", "4-20mA HART"),
    "LIT":  ("Level Indicator Transmitter",        "AI", "4-20mA HART"),
    "LI":   ("Level Indicator",                    "NA", "NA"),
    "LG":   ("Level Glass",                        "NA", "NA"),
    "FCV":  ("Flow Control Valve",                 "AO", "4-20mA HART"),
    "FY":   ("Solenoid Valve (FCV)",               "DO", "DRY(NO)"),
    "XV":   ("Shutdown Valve",                     "DO", "DRY(NO)"),
    "XY":   ("Solenoid Valve (XV)",                "DO", "DRY(NO)"),
    "ZT":   ("Control Valve Positioner",           "AI", "4-20mA HART"),
    "ZSO":  ("Limit Switch (Open)",                "DI", "DRY(NO)"),
    "ZSC":  ("Limit Switch (Closed)",              "DI", "DRY(NC)"),
    "VXT":  ("Vibration Transmitter (X)",          "AI", "4-20mA"),
    "VYT":  ("Vibration Transmitter (Y)",          "AI", "4-20mA"),
    "KT":   ("Keyphasor",                          "AI", "mV"),
    "PS":   ("Pressure Switch",                    "DI", "DRY(NO)"),
    "LS":   ("Level / Leakage Detector",           "DI", "DRY(NO)"),
    "SG":   ("Sight Glass",                        "NA", "NA"),
}

# ── Tag regex ──────────────────────────────────────────────────────────────────

# Matches:
#   422-11-PT-006A      unit=422-11, type=PT, serial=006, suffix=A
#   10-PT-001A          unit=10,     type=PT, serial=001, suffix=A
#   PT-006A             unit=None,   type=PT, serial=006, suffix=A
#   PDT-101             unit=None,   type=PDT, serial=101, suffix=None
_INST_TAG_RE = re.compile(
    r"^"
    r"(?:(\d+(?:-\d+)*)-)"   # optional unit prefix (e.g. 422-11 or 10), greedy up to type code
    r"?"
    r"([A-Z]{2,5})"           # type code
    r"-"
    r"(\d{3,6})"              # serial number
    r"([A-Z]{1,2})?"          # optional suffix (A, B, AA, AB)
    r"$"
)


def parse_instrument_tag(tag: str) -> Optional[dict]:
    """
    Parse an instrument tag string into its components.
    Returns dict with keys: unit_prefix, type_code, serial, suffix, loop_name
    or None if not parseable.
    """
    if not tag:
        return None
    tag = tag.strip()
    m = _INST_TAG_RE.match(tag)
    if not m:
        return None
    unit_prefix, type_code, serial, suffix = m.groups()
    unit_prefix = unit_prefix or ""
    suffix = suffix or ""
    # loop_name = tag without the suffix (instruments in same loop share loop_name)
    loop_name = tag[: -len(suffix)] if suffix else tag
    return {
        "unit_prefix": unit_prefix,
        "type_code": type_code,
        "serial": serial,
        "suffix": suffix,
        "loop_name": loop_name,
    }


# ── InstrumentRow dataclass ────────────────────────────────────────────────────

@dataclass
class InstrumentRow:
    # 30-column Instrumentation Index (matches ref doc column order)
    rev_no: str = ""
    unit_number: str = ""
    loop_name: str = ""
    tag_number: str = ""
    instrument_type: str = ""
    service_description: str = "TBD"
    pid_no: str = ""
    line_no: str = ""
    equipment_no: str = ""
    location: str = "TBD"
    system: str = ""
    technical_room: str = "TBD"
    io_type: str = ""
    signal_type: str = ""
    signal_level: str = "TBD"
    io_grouping: str = "TBD"
    external_power_supply: str = "TBD"
    analog_range_low: str = "TBD"
    analog_range_high: str = "TBD"
    analog_range_eu: str = "TBD"
    hh_alarm_limit: str = "-"
    h_alarm_limit: str = "-"
    l_alarm_limit: str = "-"
    ll_alarm_limit: str = "-"
    junction_box: str = "TBD"
    multi_cable_pair_no: str = "TBD"
    manufacturer: str = "LATER"
    model_no: str = "LATER"
    inst_datasheet: str = "LATER"
    hookup_drawing: str = "TBD"
    remark: str = ""

    def to_csv_dict(self) -> dict:
        return {
            "Rev No":                  self.rev_no,
            "Unit Number":             self.unit_number,
            "Loop Name":               self.loop_name,
            "Tag Number":              self.tag_number,
            "Instrument Type":         self.instrument_type,
            "Service Description":     self.service_description,
            "P&ID No":                 self.pid_no,
            "Line No":                 self.line_no,
            "Equipment No":            self.equipment_no,
            "Location":                self.location,
            "System":                  self.system,
            "Technical Room":          self.technical_room,
            "IO Type":                 self.io_type,
            "Signal Type":             self.signal_type,
            "Signal Level":            self.signal_level,
            "IO Grouping":             self.io_grouping,
            "External Power Supply":   self.external_power_supply,
            "Analog Range Low":        self.analog_range_low,
            "Analog Range High":       self.analog_range_high,
            "Analog Range EU":         self.analog_range_eu,
            "HH Alarm Limit":          self.hh_alarm_limit,
            "H Alarm Limit":           self.h_alarm_limit,
            "L Alarm Limit":           self.l_alarm_limit,
            "LL Alarm Limit":          self.ll_alarm_limit,
            "Junction Box/Panel":      self.junction_box,
            "Multi-Cable Pair No":     self.multi_cable_pair_no,
            "Manufacturer":            self.manufacturer,
            "Model No":                self.model_no,
            "Inst. Datasheet":         self.inst_datasheet,
            "Hook-up Drawing":         self.hookup_drawing,
            "Remark":                  self.remark,
        }


# ── Builder ────────────────────────────────────────────────────────────────────

def build_instrument_row(raw: dict, pid_no: str = "") -> Optional[InstrumentRow]:
    """
    Build an InstrumentRow from a raw extraction dict.
    raw keys: tag_number, line_number, equipment_number, service_description, system, confidence
    """
    tag = (raw.get("tag_number") or "").strip()
    parsed = parse_instrument_tag(tag)
    if not parsed:
        return None

    type_code = parsed["type_code"]
    inst_type, io_type, signal_type = TYPE_MAP.get(type_code, (type_code, "TBD", "TBD"))

    row = InstrumentRow(
        tag_number=tag,
        unit_number=parsed["unit_prefix"],
        loop_name=parsed["loop_name"],
        instrument_type=inst_type,
        pid_no=pid_no,
        line_no=(raw.get("line_number") or "").strip(),
        equipment_no=(raw.get("equipment_number") or "").strip(),
        service_description=(raw.get("service_description") or "TBD").strip() or "TBD",
        system=(raw.get("system") or "").strip(),
        io_type=io_type,
        signal_type=signal_type,
    )
    return row


def deduplicate_instruments(rows: list) -> list:
    """
    Deduplicate by tag_number (exact match).
    When duplicates exist, keep the one with more non-empty fields.
    """
    seen: dict[str, InstrumentRow] = {}
    for row in rows:
        key = row.tag_number
        if key not in seen:
            seen[key] = row
        else:
            existing = seen[key]
            def score(r):
                return sum(1 for v in [r.line_no, r.equipment_no, r.system, r.service_description]
                           if v and v not in ("TBD", "LATER", "-", ""))
            if score(row) > score(existing):
                seen[key] = row
    result = list(seen.values())
    result.sort(key=lambda r: (r.unit_number, r.tag_number))
    return result


def parse_raw_instruments(raw_list: list, pid_no: str = "") -> list:
    """
    Build InstrumentRow objects from raw Vision API extractions, deduplicate.
    Returns sorted list of InstrumentRow.
    """
    rows = []
    skipped = 0
    for raw in raw_list:
        row = build_instrument_row(raw, pid_no=pid_no)
        if row:
            rows.append(row)
        else:
            skipped += 1
    rows = deduplicate_instruments(rows)
    print(f"  Parsed {len(rows)} instruments (skipped {skipped} unparseable tags)")
    return rows
