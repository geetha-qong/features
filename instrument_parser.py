"""
Stage 5b parser: raw instrument extractions → InstrumentRow dataclass → 21-column index.

Schema matches the deliverable in `ref/05011-CPP-01-00-4V-IIN-01-K-101-0001_M.pdf`.

Tag formats supported (per Ceyhan/Ebara legend YY-Z(N)NNN-XXnnn(SSS)):
  01-PT-01017     unit=01, type=PT,  serial=01017
  422-11-PT-006A  unit=422-11, type=PT, serial=006, suffix=A
  PT-006A         unit="",  type=PT,  serial=006, suffix=A
  PDT-101         unit="",  type=PDT, serial=101
"""
import re
from dataclasses import dataclass
from typing import Optional

# ── Type code lookup ───────────────────────────────────────────────────────────
# Format: type_code → instrument_type_description
TYPE_MAP = {
    # Pressure
    "PT":    "PRESSURE TRANSMITTER",
    "PIT":   "PRESSURE INDICATOR TRANSMITTER",
    "PI":    "PRESSURE INDICATOR",
    "PG":    "PRESSURE GAUGE",
    "PDT":   "DIFFERENTIAL PRESSURE TRANSMITTER",
    "PDIT":  "DIFFERENTIAL PRESSURE INDICATOR TRANSMITTER",
    "PDI":   "DIFFERENTIAL PRESSURE INDICATOR",
    "PS":    "PRESSURE SWITCH",
    "PSV":   "PRESSURE SAFETY VALVE",
    "PV":    "POSITIONER",
    "PIK":   "PRESSURE INDICATING CONTROLLER (FACEPLATE)",
    "PIC":   "PRESSURE INDICATING CONTROLLER",
    "PZSC":  "PRESSURE INTERLOCK SWITCH",
    "PZLC":  "PRESSURE LATCH CONTROLLER",
    # Temperature
    "TT":    "TEMPERATURE TRANSMITTER",
    "TIT":   "TEMPERATURE INDICATOR TRANSMITTER",
    "TI":    "TEMPERATURE INDICATOR",
    "TE":    "TEMPERATURE ELEMENT-RTD",
    "TW":    "THERMOWELL",
    "TG":    "TEMPERATURE GAUGE",
    "TZE":   "TEMPERATURE ELEMENT-RTD (MACHINERY)",
    "TZI":   "TEMPERATURE INDICATOR (MACHINERY)",
    "TZT":   "TEMPERATURE TRANSMITTER (MACHINERY)",
    "TAHH":  "TEMPERATURE ALARM HIGH-HIGH",
    # Flow
    "FT":    "FLOW TRANSMITTER",
    "FIT":   "FLOW INDICATOR TRANSMITTER",
    "FI":    "FLOW INDICATOR",
    "FE":    "FLOW ELEMENT-VENTURI",
    "FCV":   "FLOW CONTROL VALVE",
    "FY":    "SOLENOID VALVE (FCV)",
    "FO":    "RESTRICTION ORIFICE",
    # Level
    "LT":    "LEVEL TRANSMITTER (DP DIAPHRAGM SEAL)",
    "LIT":   "LEVEL INDICATOR TRANSMITTER",
    "LI":    "LEVEL INDICATOR",
    "LG":    "LEVEL GLASS",
    "LS":    "LEVEL / LEAKAGE DETECTOR",
    # Speed
    "ST":    "SPEED TRANSMITTER",
    "SE":    "SPEED ELEMENT",
    "SI":    "SPEED INDICATOR",
    "SIC":   "SPEED INDICATOR/CONTROLLER",
    # Vibration / Position (machinery monitoring)
    "ZT":    "POSITION TRANSMITTER",
    "ZI":    "POSITION INDICATOR",
    "ZE":    "AXIAL VIBRATION PROBE",
    "VXE":   "RADIAL VIBRATION PROBE (X)",
    "VYE":   "RADIAL VIBRATION PROBE (Y)",
    "VXT":   "RADIAL VIBRATION TRANSMITTER (X)",
    "VYT":   "RADIAL VIBRATION TRANSMITTER (Y)",
    "VE":    "ACCELEROMETER",
    "KE":    "KEY PHASOR",
    "KT":    "KEY PHASOR TRANSMITTER",
    # On-off / interlock / shutdown
    "XV":    "ANTI-SURGE VALVE",
    "XY":    "SOLENOID VALVE (XV)",
    "XYV":   "AUX SOLENOID VALVE",
    "XZSO":  "LIMIT SWITCH (OPEN)",
    "XZSC":  "LIMIT SWITCH (CLOSED)",
    "ZSO":   "LIMIT SWITCH (OPEN)",
    "ZSC":   "LIMIT SWITCH (CLOSED)",
    "MZSO":  "MOTORISED LIMIT SWITCH (OPEN)",
    "MZSC":  "MOTORISED LIMIT SWITCH (CLOSED)",
    "MZZSO": "MOTORISED LIMIT SWITCH ASSEMBLY (OPEN)",
    "MZZLO": "MOTORISED LIMIT SWITCH LATCH (OPEN)",
    "BZDV":  "BLOWDOWN VALVE",
    "IS":    "INTERLOCK SOLENOID",
    "IT":    "INSTRUMENT TRANSMITTER",
    "HZS":   "HAND SWITCH (SHUTDOWN)",
    "HZA":   "HAND ALARM (SHUTDOWN)",
    "HSI":   "HAND SWITCH INDICATOR",
    "HIC":   "HAND INDICATING CONTROLLER",
    "HY":    "HAND CONTROL RELAY",
    "UA":    "MULTIVARIABLE ALARM",
    # Volume tank / vessel-mounted gauges
    "XPG":   "PRESSURE GAUGE (VOLUME TANK)",
    "XPSV":  "PRESSURE RELIEF VALVE (VOLUME TANK)",
    "XAO":   "ANALYZER OUTPUT",
    "XIK":   "INDICATING CONTROLLER (FACEPLATE)",
    "XIO":   "INDICATING OUTPUT",
    "XZT":   "POSITION TRANSMITTER (ON-OFF)",
    "XPT":   "PRESSURE TRANSMITTER (ON-OFF)",
    # Sight glass
    "SG":    "SIGHT GLASS",
    # Identification (loop-shared faceplate-only)
    "II":    "CURRENT INDICATOR",
}

# Default (power_supply, signal_voltage_level) by type-code group.
# Used as fallback when Vision can't determine values from the bubble shape.
def default_power_signal(type_code: str) -> tuple:
    transmitters = {
        "PT", "PIT", "TT", "TIT", "TE", "PDT", "PDIT", "FT", "FIT", "LT", "LIT",
        "ZT", "ST", "IT", "SE", "TZT", "TZE", "XPT", "XZT",
    }
    vibration_t = {"VXT", "VYT", "VE"}
    keyphasor   = {"KE", "KT"}
    solenoids   = {"XYV", "FY", "XY", "IS"}
    limit_sw    = {"XZSO", "XZSC", "ZSO", "ZSC", "MZSO", "MZSC", "MZZSO", "MZZLO", "PZSC"}
    indicators  = {"PG", "PI", "TG", "TI", "FI", "LI", "LG", "XPG", "PDI", "ZI", "SI", "II"}
    mechanical  = {"TW", "FO", "SG", "XPSV", "PSV"}
    surge_ctrl  = {"XV", "FCV", "PV"}

    if type_code in transmitters:
        return ("24VDC LOOP POWERED", "4-20 mA HART")
    if type_code in vibration_t:
        return ("24VDC", "4-20 mA")
    if type_code in keyphasor:
        return ("24VDC", "mV")
    if type_code in solenoids or type_code in limit_sw:
        return ("24VDC", "24VDC")
    if type_code in indicators or type_code in mechanical:
        return ("NA", "NA")
    if type_code in surge_ctrl:
        return ("24VDC LOOP POWERED", "4-20 mA HART")
    return ("TBD", "TBD")


# ── Tag regex ──────────────────────────────────────────────────────────────────

# Matches:
#   01-PT-01017          unit=01,     type=PT,  serial=01017
#   422-11-PT-006A       unit=422-11, type=PT,  serial=006, suffix=A
#   10-PT-001A           unit=10,     type=PT,  serial=001, suffix=A
#   PT-006A              unit=None,   type=PT,  serial=006, suffix=A
#   PDT-101              unit=None,   type=PDT, serial=101
_INST_TAG_RE = re.compile(
    r"^"
    r"(?:(\d+(?:-\d+)*)-)?"   # optional unit prefix
    r"([A-Z]{2,5})"            # type code
    r"-"
    r"([\dX]{3,6})"            # serial: digits + optional literal X placeholders
                               # (Vision is instructed to emit X for unreadable digits;
                               #  we keep these rows so engineers can fill them in)
    r"([A-Z]{1,2})?"           # optional suffix (A, B, AA)
    r"$"
)


def parse_instrument_tag(tag: str) -> Optional[dict]:
    """
    Parse an instrument tag into components. Returns None if not parseable.
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
    loop_name = tag[: -len(suffix)] if suffix else tag
    return {
        "unit_prefix": unit_prefix,
        "type_code": type_code,
        "serial": serial,
        "suffix": suffix,
        "loop_name": loop_name,
    }


# ── InstrumentRow dataclass (21-column deliverable schema) ─────────────────────

@dataclass
class InstrumentRow:
    tag_number: str = ""
    instrument_type_description: str = ""
    tag_service: str = "TBD"
    line_number: str = "NA"
    equipment_no: str = "NA"
    vlv_fail: str = "NA"
    power_supply: str = "TBD"
    signal_voltage_level: str = "TBD"
    location: str = "TBD"
    pid_no: str = ""
    vendor_scope: str = "TBD"
    hazardous_area_classification: str = "TBD"
    electrical_area_certification: str = "TBD"
    range_min: str = "TBD"
    range_max: str = "TBD"
    range_uom: str = "TBD"
    data_sheet_requisition_no: str = "TBD"
    manufacturer: str = "TBD"
    model: str = "TBD"
    status: str = "TBD"
    remarks: str = ""
    page: int = 0  # 0-based source page index; CSV "Sheet" column = page + 1

    def to_csv_dict(self) -> dict:
        return {
            "TAG NUMBER":                       self.tag_number,
            "INSTRUMENT TYPE DESCRIPTION":      self.instrument_type_description,
            "TAG SERVICE":                      self.tag_service,
            "LINE NUMBER":                      self.line_number,
            "EQUIP NO":                         self.equipment_no,
            "VLV FAIL":                         self.vlv_fail,
            "POWER SUPPLY":                     self.power_supply,
            "SIGNAL VOLTAGE LEVEL":             self.signal_voltage_level,
            "LOCATION":                         self.location,
            "P&ID":                             self.pid_no,
            "VENDOR SCOPE":                     self.vendor_scope,
            "HAZARDOUS AREA CLASSIFICATION":    self.hazardous_area_classification,
            "ELECTRICAL AREA CERTIFICATION":    self.electrical_area_certification,
            "RANGE MIN":                        self.range_min,
            "RANGE MAX":                        self.range_max,
            "RANGE UOM":                        self.range_uom,
            "DATA SHEET / REQUISITION №":       self.data_sheet_requisition_no,
            "MANUFACTURER":                     self.manufacturer,
            "MODEL":                            self.model,
            "STATUS":                           self.status,
            "REMARKS":                          self.remarks,
            "Sheet":                            (self.page or 0) + 1,  # 1-based sheet number for multi-page jobs
        }


# ── Builder ────────────────────────────────────────────────────────────────────

def _norm(value: Optional[str], fallback: str) -> str:
    """Normalize Vision output: empty/null/'TBD' → fallback."""
    if value is None:
        return fallback
    s = str(value).strip()
    if not s or s.upper() in {"NULL", "NONE", "N/A"}:
        return fallback
    return s


def _measured_var(type_code: str) -> str:
    """Return the variable a type code measures (PRESS / TEMP / FLOW / ...)."""
    if type_code in {"PT", "PG", "PI", "PIT", "PIK", "PIC", "PS"}:
        return "PRESS"
    if type_code in {"PDT", "PDIT", "PDI"}:
        return "DIFF PRESS"
    if type_code in {"TT", "TIT", "TI", "TE", "TG", "TZE", "TZI", "TZT"}:
        return "TEMP"
    if type_code == "TW":
        return "THERMOWELL"
    if type_code in {"FT", "FIT", "FI", "FE"}:
        return "FLOW"
    if type_code in {"FCV", "FY"}:
        return "FLOW CONTROL"
    if type_code in {"LT", "LIT", "LI", "LG", "LS"}:
        return "LEVEL"
    if type_code in {"ZT", "ZI"}:
        return "POSITION"
    if type_code in {"ZE", "VXE", "VYE", "VXT", "VYT", "VE"}:
        return "VIBRATION"
    if type_code in {"ST", "SE", "SI", "SIC"}:
        return "SPEED"
    if type_code in {"KE", "KT"}:
        return "KEY PHASOR"
    if type_code in {"XV", "XYV", "XZSO", "XZSC"}:
        return "VALVE"
    if type_code in {"XPG"}:
        return "VOL TANK PRESS"
    if type_code in {"XPSV", "PSV"}:
        return "RELIEF VALVE"
    if type_code == "SG":
        return "SIGHT GLASS"
    if type_code == "FO":
        return "ORIFICE"
    return ""


# Fluid-code prefix → service hint (line numbers like "1.1/2"-LO-01-101405-S15WN-N"
# use the second token to identify the fluid system).
_FLUID_HINT = {
    "LO": "LUBE OIL",
    "PR": "PROCESS",
    "N2": "NITROGEN",
    "H2": "DRY GAS SEAL",
    "IA": "INSTRUMENT AIR",
    "BA": "BREATHING AIR",
    "PA": "PLANT AIR",
    "SA": "SERVICE AIR",
    "FW": "FRESHWATER",
    "CW": "COOLING WATER",
    "ST": "STEAM",
    "FG": "FUEL GAS",
    "VG": "VENT GAS",
}


def _fallback_tag_service(line_no: str, type_code: str, equipment_no: str) -> str:
    """Best-effort service descriptor when Vision returns TBD.

    Returns "TBD" only if we have nothing meaningful — never pretend to know
    the equipment/section if we don't.
    """
    var = _measured_var(type_code)
    if not line_no or line_no in ("NA", "TBD"):
        return "TBD"

    # Parse fluid code from line: <size>"-<FLUID>-<unit>-<seq>-<class>-<insul>
    parts = line_no.upper().replace('"', '').split("-")
    fluid = parts[1] if len(parts) >= 2 else ""
    hint = _FLUID_HINT.get(fluid, "")

    if hint and var:
        return f"{hint} {var}"
    if hint:
        return hint
    if var:
        return var
    return "TBD"


def build_instrument_row(raw: dict, pid_no: str = "") -> Optional[InstrumentRow]:
    """
    Build an InstrumentRow from a raw extraction dict.
    Raw keys consumed: tag_number, instrument_type_description, tag_service,
                       line_number, equipment_number, location,
                       power_supply, signal_voltage_level, pid_no
    """
    tag = (raw.get("tag_number") or "").strip()
    parsed = parse_instrument_tag(tag)
    if not parsed:
        return None

    type_code = parsed["type_code"]
    type_desc_default = TYPE_MAP.get(type_code, type_code)
    power_default, signal_default = default_power_signal(type_code)

    line_no = _norm(raw.get("line_number"), "NA")
    equipment_no = _norm(raw.get("equipment_number"), "NA")

    # Vision-supplied tag_service first; fall back to fluid-hint heuristic.
    # If Vision returned just a bare measured-variable like "FLOW" / "PRESS" / "TEMP"
    # (no equipment context), treat it as if Vision failed and synthesize a richer
    # service from line + equipment. We also cap at 30 chars to keep the column tidy.
    vision_service = _norm(raw.get("tag_service"), "TBD")
    _bare_vars = {"FLOW", "PRESS", "TEMP", "LEVEL", "POSITION", "SPEED", "VIBRATION",
                  "DIFF PRESS", "ANALYSER", "ANALYZER"}
    if vision_service == "TBD" or vision_service.upper().strip() in _bare_vars:
        tag_service = _fallback_tag_service(line_no, type_code, equipment_no)
    else:
        tag_service = vision_service
    if len(tag_service) > 30:
        tag_service = tag_service[:30].rstrip()

    return InstrumentRow(
        tag_number=tag,
        instrument_type_description=_norm(raw.get("instrument_type_description"), type_desc_default),
        tag_service=tag_service,
        line_number=line_no,
        equipment_no=equipment_no,
        vlv_fail="NA",
        power_supply=_norm(raw.get("power_supply"), power_default),
        signal_voltage_level=_norm(raw.get("signal_voltage_level"), signal_default),
        location=_norm(raw.get("location"), "FIELD" if power_default != "TBD" else "TBD"),
        # Per-page pid_no from raw dict wins over the function-level fallback
        pid_no=_norm(raw.get("pid_no"), pid_no),
        page=int(raw.get("page", 0) or 0),
    )


def deduplicate_instruments(rows: list) -> list:
    """
    Deduplicate by tag_number (exact match). Keep the row with more populated fields.
    """
    seen: dict = {}

    def score(r: InstrumentRow) -> int:
        return sum(
            1 for v in [r.line_number, r.equipment_no, r.tag_service, r.location]
            if v and v not in ("TBD", "NA", "")
        )

    for row in rows:
        key = row.tag_number
        if key not in seen or score(row) > score(seen[key]):
            seen[key] = row

    result = list(seen.values())
    result.sort(key=lambda r: r.tag_number)
    return result


def parse_raw_instruments(raw_list: list, pid_no: str = "") -> list:
    """
    Build InstrumentRow objects from raw Vision API extractions, deduplicate, sort.
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
