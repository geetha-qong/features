"""
Stage 3: Parse raw Claude extractions into structured CSV rows.
- Supports multiple tag/line formats (Format 1: Oman, Format 2: compact)
- Deduplicates valves by (area_code + serial_no), merging series codes
- Parses valve tag → Category, Area Code, Serial No, (optionally Size, Series)
- Parses line number → Size, Fluid Code, Piping Class
- Maps actuator → Dynamic Code + 3 actuator columns
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Tag patterns ─────────────────────────────────────────────────────────────

# Format 1: [Area(2d)]-[Type(2-4L)]-[Serial(5-6d)]  e.g. 62-BF-151031
TAG_PATTERN_1 = re.compile(
    r"(?P<area>\d{2})-(?P<type>[A-Z]{2,4})-(?P<serial>\d{5,6})",
    re.IGNORECASE,
)

# Format 2: [Actuator?][Type][Size]-[Area(1d)][Serial(3d)][Series?]
# e.g. VB15-2011A, VF300-2057, AVF250-2016
TAG_PATTERN_2 = re.compile(
    r"^(?P<actuator>[A-Z])?(?P<type>V[A-Z]{0,2})(?P<size>\d{2,4})-(?P<area>\d)(?P<serial>\d{3})(?P<series>[A-Z])?$",
    re.IGNORECASE,
)

# Format 3: WTP / non-MUK — whitespace between size and area+serial (Format 2's dashed cousin).
# Same semantic shape as Format 2: leading 1-digit area embedded in the serial group.
# e.g. "VB15 7007" -> area=7, serial=007 ; "VB15 81631A" -> area=8, serial=1631, series=A.
# Vision non-deterministically emits Format 2 (dash) or Format 3 (space/newline) for the same tag.
TAG_PATTERN_3 = re.compile(
    r"^(?P<actuator>[AMP])?(?P<type>V[A-Z]{0,2})(?P<size>\d{2,4})\s+(?P<area>\d)(?P<serial>\d{3,4})(?P<series>[A-Z])?$",
    re.IGNORECASE,
)

# Format 4: client convention with NO area-code prefix — [Type][sep][Serial].
# Job 41 (MUK-62-0-0002) / job 40 use this: PV-01156, BV-32062, DV-01157, XV-01052, VG 01-1034.
# Type is whitelisted to known valve codes so we don't match random TYPE-NUMBER noise
# like "TUB-01", "S30-BSN", or pipe-size labels.
TAG_PATTERN_4 = re.compile(
    r"^(?P<type>BF|BV|VB|VF|DB|CK|GL|CV|VM|VG|NV|SV|PV|XV|DV|GV)[\s\-]*(?P<serial>\d{3,6})$",
    re.IGNORECASE,
)

# Format 5: KKS plant coding (Kraftwerks-Kennzeichensystem) — power/process
# clients (the 70310-20-* drawings). Shape:
#   [unit 2d][system 3L][aggregate 1-4d]  [optional component 2L + counter 1-4d]
#   e.g. 20LCM40 BR401, 20GHB446 AA005, 20LCM17AA001, 20GHB4461.
# The Vision pass reads these tags fine, but Formats 1-4 all expect a Western
# valve-type abbreviation, so every KKS tag fell through → parse returned None
# → the valve list came out empty. This pattern accepts them so the data is
# preserved. Tried LAST (after 1-4) and its shape (2 leading digits + 3 letters,
# no dashes) doesn't collide with the earlier formats.
TAG_PATTERN_5 = re.compile(
    r"^(?P<unit>\d{2})(?P<system>[A-Z]{3})(?P<aggregate>\d{1,4})"
    r"(?:\s?(?P<component>[A-Z]{2})(?P<counter>\d{1,4}))?$",
    re.IGNORECASE,
)

# ── Line number patterns (tried in order, most → least specific) ──────────────

# Format 2 line: 250-WAP-XXXX-AS1LC → fluid=WAP, piping=AS1LC (no size extraction)
_LINE_FMT2 = re.compile(
    r"\d+-(?P<fluid>[A-Z]{2,4})-[A-Z0-9]+-(?P<piping>[A-Z0-9]{3,10})",
    re.IGNORECASE,
)

# Format 1 Tier 1 — full format: 20"-W-62151019-BGA
_FULL = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?\s*-\s*(?P<fluid>[A-Z]{1,4})\s*-\s*\d+\s*-\s*(?P<piping>[A-Z][A-Z0-9\-]{1,10})',
    re.IGNORECASE,
)

# Format 1 Tier 2 — size + fluid only (piping class missing): 2"-W-62151067
_SIZE_FLUID = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?\s*[-–]\s*(?P<fluid>[A-Z]{1,4})',
    re.IGNORECASE,
)

# Format 1 Tier 3 — comma-separated partial: "10",LO  or  10",LO
_CSV_PARTIAL = re.compile(
    r'(?P<size>\d+(?:\.\d+)?)\s*["\']?,\s*(?P<fluid>[A-Z]{1,4})',
    re.IGNORECASE,
)

ACTUATOR_MAP = {
    "M":    {"dynamic": "M",  "motor": "x", "pneumatic": "-", "solenoid": "-"},
    "P":    {"dynamic": "P",  "motor": "-", "pneumatic": "x", "solenoid": "-"},
    "SL":   {"dynamic": "SL", "motor": "-", "pneumatic": "-", "solenoid": "x"},
    "A":    {"dynamic": "A",  "motor": "-", "pneumatic": "-", "solenoid": "-"},
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
    page: int = 0  # 0-based source page index; CSV "Sheet" column = page + 1
    raw_tag: str = field(default="", repr=False)
    confidence: float = field(default=0.0, repr=False)
    _series_codes: list = field(default_factory=list, repr=False)

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
            "Sheet": (self.page or 0) + 1,  # 1-based sheet number for multi-page jobs
        }


def parse_valve_tag(tag: str) -> Optional[dict]:
    """
    Parse a valve tag string into its components.
    Tries Format 1 (62-BF-151031), then Format 2 (VB15-2011A), then Format 3 (VB15 7007).
    Returns dict with keys: area, type_code, serial, and optionally:
      size, series_code, actuator_from_tag, format
    """
    if not tag:
        return None
    # Collapse any internal whitespace (Vision sometimes splits tags across newlines)
    s = re.sub(r"\s+", " ", tag.strip().upper())

    # Format 1: 62-BF-151031
    m = TAG_PATTERN_1.search(s)
    if m:
        return {
            "area": m.group("area"),
            "type_code": m.group("type"),
            "serial": m.group("serial"),
            "format": 1,
        }

    # Format 2: VB15-2011A, AVF250-2016
    m = TAG_PATTERN_2.match(s)
    if m:
        result = {
            "area": m.group("area"),
            "type_code": m.group("type").upper(),
            "serial": m.group("serial"),
            "size": m.group("size"),
            "format": 2,
        }
        if m.group("series"):
            result["series_code"] = m.group("series").upper()
        if m.group("actuator"):
            result["actuator_from_tag"] = m.group("actuator").upper()
        return result

    # Format 3: VB15 7007, VF125 8142, AVF125 81631A — space variant of Format 2
    m = TAG_PATTERN_3.match(s)
    if m:
        result = {
            "area": m.group("area"),
            "type_code": m.group("type").upper(),
            "serial": m.group("serial"),
            "size": m.group("size"),
            "format": 3,
        }
        if m.group("series"):
            result["series_code"] = m.group("series").upper()
        if m.group("actuator"):
            result["actuator_from_tag"] = m.group("actuator").upper()
        return result

    # Format 4: TYPE-SERIAL with no area-code prefix — e.g. PV-01156, BV-32062
    m = TAG_PATTERN_4.match(s)
    if m:
        return {
            "area": "-",
            "type_code": m.group("type").upper(),
            "serial": m.group("serial"),
            "format": 4,
        }

    # Format 5: KKS plant coding — preserve all fields so the valve isn't dropped.
    m = TAG_PATTERN_5.match(s)
    if m:
        system = m.group("system").upper()
        aggregate = m.group("aggregate")
        component = (m.group("component") or "").upper()
        counter = m.group("counter") or ""
        # serial = everything after the 2-digit unit (system+aggregate+component
        # +counter, spaces already collapsed). The leading unit is the only part
        # shared across the whole drawing, so encoding the rest into `serial`
        # guarantees distinct KKS tags get distinct dedup keys (area+serial) and
        # don't merge.
        serial = f"{system}{aggregate}{component}{counter}"
        return {
            "area": m.group("unit"),
            # Category = the KKS component code when present (AA/BR/BS/…), else
            # the 3-letter system code. FIRST-PASS mapping — the KKS component →
            # valve-type mapping should be refined per client; this keeps the
            # data visible rather than dropping it.
            "type_code": component or system,
            "serial": serial,
            "format": 5,
        }

    return None


def parse_line_number(line_no: str) -> dict:
    """
    Parse a pipe line number string into {size, fluid_code, piping_class}.
    Tries multiple formats from most to least specific.
    Returns whatever it can extract; missing fields are absent from the dict.
    """
    if not line_no:
        return {}

    s = line_no.strip()

    # Format 2 line: 250-WAP-XXXX-AS1LC
    m = _LINE_FMT2.search(s)
    if m:
        return {
            "fluid_code": m.group("fluid").upper(),
            "piping_class": m.group("piping").upper(),
        }

    # Format 1 Tier 1 — full: 20"-W-62151019-BGA
    m = _FULL.search(s)
    if m:
        result = {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
            "piping_class": m.group("piping").upper(),
        }
        return result

    # Format 1 Tier 2 — size + fluid only: 2"-W-62151067
    m = _SIZE_FLUID.search(s)
    if m:
        return {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
        }

    # Format 1 Tier 3 — comma-separated partial: "10",LO
    m = _CSV_PARTIAL.search(s)
    if m:
        return {
            "size": m.group("size"),
            "fluid_code": m.group("fluid").upper(),
        }

    return {}


def merge_rows(base: ValveRow, extra: ValveRow) -> ValveRow:
    """
    Merge two rows for the same valve: fill gaps in base from extra.
    Keeps base tag/actuator/confidence if higher, fills in missing line data from extra.
    Collects series codes from both.
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

    # Merge series codes
    all_series = set(winner._series_codes + loser._series_codes)
    winner._series_codes = sorted(all_series)

    return winner


def _format_series_codes(codes: list[str]) -> tuple[str, int]:
    """
    Format a list of series codes into a display string and quantity.
    ['A', 'B', 'C'] → ("A-C", 3)
    ['A', 'C'] → ("A,C", 2)
    [] → ("-", 1)
    """
    if not codes:
        return "-", 1

    codes = sorted(set(codes))
    qty = len(codes)

    if qty == 1:
        return codes[0], 1

    # Check if consecutive
    if all(ord(codes[i]) == ord(codes[i-1]) + 1 for i in range(1, len(codes))):
        return f"{codes[0]}-{codes[-1]}", qty
    else:
        return ",".join(codes), qty


def build_valve_row(raw: dict, pid_no: str = "") -> Optional[ValveRow]:
    tag = raw.get("valve_tag", "")
    tag_parts = parse_valve_tag(tag)
    if not tag_parts:
        return None

    line_parts = parse_line_number(raw.get("line_number") or "")

    # Determine actuator: tag prefix overrides raw.actuator for Format 2
    actuator_key = "none"
    if "actuator_from_tag" in tag_parts:
        actuator_key = tag_parts["actuator_from_tag"]
    else:
        actuator_key = raw.get("actuator", "none")
    act_cols = ACTUATOR_MAP.get(actuator_key, ACTUATOR_MAP["none"])

    # Size: from tag (Format 2), then line number (Format 1), then NOT DEFINED
    size = tag_parts.get("size") or line_parts.get("size") or "NOT DEFINED"
    # DB (Double Block & Bleed) valves are always on 2" instrument taps
    if tag_parts.get("type_code", "").upper() == "DB" and size == "NOT DEFINED":
        size = "2"

    # Series codes tracking
    series_codes = []
    if "series_code" in tag_parts:
        series_codes = [tag_parts["series_code"]]

    series_display, _ = _format_series_codes(series_codes)

    return ValveRow(
        pid_no=pid_no,
        dynamic_code=act_cols["dynamic"],
        category=tag_parts["type_code"],
        size=size,
        area_code=tag_parts["area"],
        serial_no=tag_parts["serial"],
        series_code=series_display,
        fluid_code=line_parts.get("fluid_code", ""),
        piping_class=line_parts.get("piping_class", ""),
        qty=1,
        motor_actuator=act_cols["motor"],
        pneumatic_actuator=act_cols["pneumatic"],
        solenoid=act_cols["solenoid"],
        line=raw.get("line_number") or "",
        page=int(raw.get("page", 0) or 0),
        raw_tag=tag,
        confidence=float(raw.get("confidence", 0.0)),
        _series_codes=series_codes,
    )


def deduplicate(rows: list) -> list:
    """
    Keep one row per (area_code, serial_no), merging data from all duplicates.
    Series codes (A, B, C) get merged — qty reflects distinct series count.
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

        # Finalize series code display and qty
        if base._series_codes:
            base.series_code, base.qty = _format_series_codes(base._series_codes)
        merged.append(base)

    return sorted(merged, key=lambda r: (r.area_code, r.serial_no))


def parse_raw_extractions(
    raw_valves: list,
    pid_no: str = "",
    tmp_dir: Optional[Path] = None,
) -> list:
    rows, skipped_raws = [], []
    for raw in raw_valves:
        row = build_valve_row(raw, pid_no=pid_no)
        if row:
            rows.append(row)
        else:
            skipped_raws.append({
                "valve_tag": raw.get("valve_tag", ""),
                "line_number": raw.get("line_number", ""),
                "actuator": raw.get("actuator", ""),
                "tile": raw.get("tile", ""),
                "pid_no": pid_no,
            })

    skipped = len(skipped_raws)
    print(f"  Parsed {len(rows)} rows, skipped {skipped} unparseable")

    # Log unparseable detections so we can mine them for new tag-format regexes.
    # This file is the source for parser improvements over time — each run accumulates
    # the patterns we still can't handle.
    if tmp_dir is not None and skipped_raws:
        tmp_dir = Path(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out = tmp_dir / "unparseable_valves.json"
        out.write_text(json.dumps(skipped_raws, indent=2))
        print(f"  → unparseable detections written to {out}")
        print(f"    (mine this file to add new regex patterns to parser.py)")

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
        print(f"  {r.raw_tag:25s} | {r.category:4s} | {r.size:5s} | {r.fluid_code:4s} | {r.piping_class:8s} | series={r.series_code} qty={r.qty} {status}")
