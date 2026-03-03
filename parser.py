"""
Stage 3: Parse raw Claude extractions into structured CSV rows.
- Deduplicates valves by (area_code + serial_no), merging line number data
- Parses valve tag → Category, Area Code, Serial No
- Parses line number → Size, Fluid Code, Piping Class (tiered patterns)
- Maps actuator → Dynamic Code + 3 actuator columns
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Tag pattern ───────────────────────────────────────────────────────────────
TAG_PATTERN = re.compile(
    r"(?P<area>\d{2})-(?P<type>[A-Z]{2,4})-(?P<serial>\d{5,6})",
    re.IGNORECASE,
)

# ── Line number patterns (tried in order, most → least specific) ──────────────

# Tier 1 — full format: 20"-W-62151019-BGA
_FULL = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?\s*-\s*(?P<fluid>[A-Z]{1,4})\s*-\s*\d+\s*-\s*(?P<piping>[A-Z][A-Z0-9\-]{1,10})',
    re.IGNORECASE,
)

# Tier 2 — size + fluid only (piping class missing): 2"-W-62151067
_SIZE_FLUID = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?\s*[-–]\s*(?P<fluid>[A-Z]{1,4})',
    re.IGNORECASE,
)

# Tier 3 — comma-separated partial: "10",LO  or  10",LO
_CSV_PARTIAL = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?,\s*(?P<fluid>[A-Z]{1,4})',
    re.IGNORECASE,
)

# Tier 4 — size only: 20" or 2"
_SIZE_ONLY = re.compile(
    r'^(?P<size>\d+(?:\.\d+)?)\s*["\']',
    re.IGNORECASE,
)

ACTUATOR_MAP = {
    "M":    {"dynamic": "M",  "motor": "x", "pneumatic": "-", "solenoid": "-"},
    "P":    {"dynamic": "P",  "motor": "-", "pneumatic": "x", "solenoid": "-"},
    "SL":   {"dynamic": "SL", "motor": "-", "pneumatic": "-", "solenoid": "x"},
    "none": {"dynamic": "-",  "motor": "-", "pneumatic": "-", "solenoid": "-"},
}


@dataclass
class ValveRow:
    pid_no: str = ""
    dynamic_code: str = "-"
    category: str = ""
    size: str = "NOT DEFINED"
    area_code: str = "-"
    serial_no: str = ""
    series_code: str = "-"
    fluid_code: str = ""
    piping_class: str = ""
    qty: int = 1
    motor_actuator: str = "-"
    pneumatic_actuator: str = "-"
    solenoid: str = "-"
    line: str = ""
    raw_tag: str = field(default="", repr=False)
    confidence: float = field(default=0.0, repr=False)

    def completeness(self) -> int:
        """Score: how many of the 3 key line fields are filled (0-3)."""
        return sum([
            self.size not in ("NOT DEFINED", "") and bool(self.size),
            bool(self.fluid_code),
            bool(self.piping_class),
        ])

    def to_csv_dict(self) -> dict:
        return {
            "P&ID No": self.pid_no,
            "Dynamic Code": self.dynamic_code,
            "Category": self.category,
            "Size": self.size,
            "Area Code": self.area_code,
            "Serial No": self.serial_no,
            "Series Code": self.series_code,
            "Fluid Code": self.fluid_code,
            "Piping Class": self.piping_class,
            "Qty": self.qty,
            "Motor Actuator": self.motor_actuator,
            "Pneumatic Actuator ": self.pneumatic_actuator,
            "Solenoid": self.solenoid,
            "line": self.line,
        }


def parse_valve_tag(tag: str) -> Optional[dict]:
    """Parse '62-BF-151031' → {area, type_code, serial}"""
    m = TAG_PATTERN.search(tag.strip().upper())
    if m:
        return {"area": m.group("area"), "type_code": m.group("type"), "serial": m.group("serial")}
    return None


def parse_line_number(line_no: str) -> dict:
    """
    Parse a pipe line number string into {size, fluid_code, piping_class}.
    Tries 4 tiers from most to least specific.
    Returns whatever it can extract; missing fields are absent from the dict.
    """
    if not line_no:
        return {}

    s = line_no.strip()

    # Tier 1 — full
    m = _FULL.search(s)
    if m:
        return {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
            "piping_class": m.group("piping").upper(),
        }

    # Tier 2 — size + fluid
    m = _SIZE_FLUID.search(s)
    if m:
        return {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
        }

    # Tier 3 — comma-separated partial: "10",LO
    m = _CSV_PARTIAL.search(s)
    if m:
        return {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
        }

    # Tier 4 — size only
    m = _SIZE_ONLY.match(s)
    if m:
        return {"size": m.group("size")}

    return {}


def merge_rows(base: ValveRow, extra: ValveRow) -> ValveRow:
    """
    Merge two rows for the same valve: fill gaps in base from extra.
    Keeps base tag/actuator/confidence if higher, fills in missing line data from extra.
    """
    winner = base if base.confidence >= extra.confidence else extra
    loser  = extra if base.confidence >= extra.confidence else base

    # Fill in missing line fields from the other detection
    if winner.size == "NOT DEFINED" and loser.size != "NOT DEFINED":
        winner.size = loser.size
    if not winner.fluid_code and loser.fluid_code:
        winner.fluid_code = loser.fluid_code
    if not winner.piping_class and loser.piping_class:
        winner.piping_class = loser.piping_class
    if not winner.line and loser.line:
        winner.line = loser.line

    return winner


def build_valve_row(raw: dict, pid_no: str = "MUK-62-1-15-1004-001-24C7") -> Optional[ValveRow]:
    tag = raw.get("valve_tag", "")
    tag_parts = parse_valve_tag(tag)
    if not tag_parts:
        return None

    line_parts = parse_line_number(raw.get("line_number") or "")
    actuator = raw.get("actuator", "none")
    act_cols = ACTUATOR_MAP.get(actuator, ACTUATOR_MAP["none"])

    return ValveRow(
        pid_no=pid_no,
        dynamic_code=act_cols["dynamic"],
        category=tag_parts["type_code"],
        size=line_parts.get("size", "NOT DEFINED"),
        area_code=tag_parts["area"],
        serial_no=tag_parts["serial"],
        series_code="-",
        fluid_code=line_parts.get("fluid_code", ""),
        piping_class=line_parts.get("piping_class", ""),
        qty=1,
        motor_actuator=act_cols["motor"],
        pneumatic_actuator=act_cols["pneumatic"],
        solenoid=act_cols["solenoid"],
        line=raw.get("line_number") or "",
        raw_tag=tag,
        confidence=float(raw.get("confidence", 0.0)),
    )


def deduplicate(rows: list) -> list:
    """
    Keep one row per (area_code, serial_no), merging data from all duplicates.
    Merge strategy: take highest-confidence row as base, fill gaps from others.
    """
    groups: dict = {}
    for row in rows:
        key = (row.area_code, row.serial_no)
        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    merged = []
    for key, group in groups.items():
        group.sort(key=lambda r: r.confidence, reverse=True)
        base = group[0]
        for extra in group[1:]:
            base = merge_rows(base, extra)
        merged.append(base)

    return sorted(merged, key=lambda r: (r.area_code, r.serial_no))


def parse_raw_extractions(raw_valves: list, pid_no: str = "MUK-62-1-15-1004-001-24C7") -> list:
    rows, skipped = [], 0
    for raw in raw_valves:
        row = build_valve_row(raw, pid_no=pid_no)
        if row:
            rows.append(row)
        else:
            skipped += 1

    print(f"  Parsed {len(rows)} rows, skipped {skipped} unparseable")
    deduped = deduplicate(rows)
    complete = sum(1 for r in deduped if r.completeness() == 3)
    print(f"  After dedup: {len(deduped)} unique | {complete} fully complete (size+fluid+piping)")
    return deduped


if __name__ == "__main__":
    import json
    with open("tmp/raw_extractions.json") as f:
        raw = json.load(f)
    print(f"Loaded {len(raw)} raw extractions")
    rows = parse_raw_extractions(raw)
    for r in rows:
        status = "OK" if r.completeness() == 3 else f"MISS:{3-r.completeness()}"
        print(f"  {r.raw_tag:25s} | {r.category:4s} | {r.size:5s} | {r.fluid_code:4s} | {r.piping_class:8s} {status}")
