"""Line List deliverable generators (CSV + XLSX).

Shows one row per unique pipe line, derived from valve entities
(entity_class == "valve") deduplicated on fields.line in entities.py.
"""

import csv
import io as _io
from typing import ClassVar, Dict, List, Set

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from webapp.deliverables.base import Generator
from webapp.deliverables.canonical import CanonicalEntity, JobCanonical
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.line_fluids import propagate_line_fluids
from webapp.deliverables.registry import REGISTRY
from webapp.deliverables.sort_utils import instrument_sort_key
from webapp.deliverables.template import DeliverableConfig, TemplateConfig

import re

# A valid line number: <digits> optional " then - then a letter/digit. The "
# is optional so both inch-format (3"-P-62151007-BGA) and mm/numeric format
# (50-ABL-XXXX-AS2LC) are accepted — mirrors entities.py._VALID_LINE_RE.
_VALID_LINE_RE = re.compile(r'^\d+(/\d+)?"?-[A-Z0-9]', re.IGNORECASE)

# Stricter engineering-line guard for recovered (line_list_data.json-only)
# pipelines that have NO backing entity: require a numeric size prefix and at
# least 3 dash segments so we never emit a junk row from a stray OCR fragment.
_LINE_PREFIX_RE = re.compile(r'^\d+(?:/\d+)?"?$')


def _is_engineering_line(line_no: str) -> bool:
    parts = (line_no or "").strip().upper().split("-")
    if len(parts) < 3:
        return False
    if not _LINE_PREFIX_RE.match(parts[0]):
        return False
    return all(p for p in parts)


def _norm_line(line_no: str) -> str:
    """Canonical comparison key for a line number (upper, no whitespace)."""
    return re.sub(r"\s+", "", (line_no or "").strip().upper())


def _recovered_remark(ocr: dict) -> str:
    """Remarks label for a recovered pipeline, reflecting its confidence.
    Low-confidence recoveries are flagged NEEDS REVIEW rather than presented
    as confirmed engineering lines."""
    ocr = ocr or {}
    status = (ocr.get("_status") or "confirmed").lower()
    srcs = ocr.get("_source") or []
    conf = ocr.get("_confidence")
    label = ("NEEDS REVIEW — recovered (orientation OCR)"
             if status == "needs_review"
             else "Recovered (orientation OCR)")
    if isinstance(srcs, list) and srcs:
        label += f" [{', '.join(srcs)}]"
    if conf is not None:
        label += f" (conf {conf})"
    amb = ocr.get("_ambiguous_with")
    if amb:
        label += f" — ambiguous vs {', '.join(amb)}"
    return label


def _filter_lines(entities: List[CanonicalEntity]) -> List[CanonicalEntity]:
    """Return one entity per unique valid line designation (dedup on fields.line)."""
    # Fill blank Fluid/Phase via drawing-scoped evidence before projecting rows,
    # so the exported deliverable matches the UI (entities API does the same).
    propagate_line_fluids(entities)
    seen: Set[str] = set()
    result: List[CanonicalEntity] = []
    for e in entities:
        if e.entity_class != "valve":
            continue
        line = (e.fields or {}).get("line", "") or ""
        line = line.strip()
        if not line or not _VALID_LINE_RE.match(line):
            continue
        if line in seen:
            continue
        seen.add(line)
        result.append(e)
    return result


def _ordered_columns(cfg: DeliverableConfig):
    return sorted(cfg.columns, key=lambda c: c.order)


# line_list_data.json field → CanonicalEntity.fields key (template field names).
_OCR_TO_FIELD = {
    "fluid":            "fluid_type",
    "pipe_size":        "size",
    "piping_class":     "piping_class",
    "op_pressure":      "working_pressure",
    "op_temp":          "working_temp",
    "design_pressure":  "design_press",
    "design_temp":      "design_temp",
    "material":         "material",
    "insulation":       "insulation_type",
    "phase":            "phase",
}


def synthesize_recovered_line_entities(
    existing: List[CanonicalEntity], ocr_data: dict
) -> List[CanonicalEntity]:
    """Build pseudo valve-class entities for engineering line numbers present
    ONLY in line_list_data.json (recovered by Pass 4 / Pass 4.5 orientation OCR)
    with no backing canonical entity, so the export Line List shows them too.

    Scope: callers must append the result to a request-local copy of the line
    list's entities ONLY — never to shared canonical (these are not real valves
    and must not leak into the Valve List).
    """
    import uuid as _uuid

    have = {
        _norm_line((e.fields or {}).get("line", "") or "")
        for e in existing
        if (e.fields or {}).get("line")
    }
    # Learn the convention from the WHOLE project (existing + recovered lines),
    # per-job only.
    all_lines = [
        (e.fields or {}).get("line", "") for e in existing if (e.fields or {}).get("line")
    ] + [k for k in (ocr_data or {}) if isinstance(k, str)]
    convention = None
    try:
        from line_parser import learn_convention
        convention = learn_convention(all_lines)
    except Exception:
        convention = None

    out: List[CanonicalEntity] = []
    for line_no, data in (ocr_data or {}).items():
        if not (isinstance(line_no, str) and isinstance(data, dict)):
            continue
        norm = _norm_line(line_no)
        if not norm or norm in have:
            continue
        if not _is_engineering_line(line_no):
            continue
        have.add(norm)
        parsed = _parse_line_full(line_no, convention)
        fields: Dict[str, str] = {"line": line_no}
        for ocr_key, field_key in _OCR_TO_FIELD.items():
            val = (data.get(ocr_key) or "")
            if isinstance(val, str) and val.strip():
                fields[field_key] = val.strip()
        fields.setdefault("fluid_type", parsed["fluid_code"])
        fields.setdefault("size", parsed["size"])
        fields.setdefault("piping_class", parsed["piping_class"])
        if parsed["insulation_type"]:
            fields.setdefault("insulation_type", parsed["insulation_type"])
        fields["service_description"] = _recovered_remark(data)
        out.append(CanonicalEntity(
            entity_id=_uuid.uuid5(_uuid.NAMESPACE_URL, f"recovered-line:{norm}"),
            entity_class="valve",
            sub_class="",
            tag=None,
            pid_number="",
            sheet_number=0,
            bbox=(0.0, 0.0, 0.0, 0.0),
            fields=fields,
        ))
    return out


class LineListCSVGenerator(Generator):
    deliverable_type: ClassVar[str] = "line_list"
    file_format: ClassVar[str] = "csv"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        deliv = template.deliverables["line_list"]
        columns = _ordered_columns(deliv)
        lines = _filter_lines(canonical.entities)
        lines.sort(key=lambda e: instrument_sort_key(
            (e.fields or {}).get("line", "") or e.tag or ""
        ))
        buf = _io.StringIO()
        writer = csv.writer(buf)
        flat_headers = [
            f"{c.group} - {c.header}" if c.group else c.header
            for c in columns
        ]
        writer.writerow(flat_headers)
        for line_entity in lines:
            writer.writerow([resolve_field(line_entity, c.field) for c in columns])
        return buf.getvalue().encode("utf-8")


class LineListXLSXGenerator(Generator):
    deliverable_type: ClassVar[str] = "line_list"
    file_format: ClassVar[str] = "xlsx"

    def generate(self, canonical: JobCanonical, template: TemplateConfig) -> bytes:
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Border, Side

        deliv = template.deliverables["line_list"]
        columns = _ordered_columns(deliv)
        lines = _filter_lines(canonical.entities)
        lines.sort(key=lambda e: instrument_sort_key(
            (e.fields or {}).get("line", "") or e.tag or ""
        ))

        wb = Workbook()
        ws = wb.active
        ws.title = deliv.sheet_name or "Line List"

        yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
        blue_fill = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
        bold = Font(name=deliv.font or "Calibri", bold=True)
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin = Side(style="thin")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # ── Build group spans ──────────────────────────────────────────────
        # group_spans: {group_name: [col_indices (1-based)]}
        group_spans: Dict[str, List[int]] = {}
        for col_idx, col in enumerate(columns, 1):
            if col.group:
                group_spans.setdefault(col.group, []).append(col_idx)

        # Row 1 — group headers (for grouped cols) or sub-header (for ungrouped)
        # Row 2 — sub-headers for grouped cols only; ungrouped cols left blank in row 2
        for col_idx, col in enumerate(columns, 1):
            col_letter = get_column_letter(col_idx)
            if col.group:
                # sub-header goes in row 2
                cell2 = ws.cell(row=2, column=col_idx, value=col.header)
                cell2.font = bold
                cell2.fill = blue_fill
                cell2.alignment = center
                cell2.border = border
            else:
                # ungrouped — header in row 1, row 2 stays empty; merge rows 1+2
                cell1 = ws.cell(row=1, column=col_idx, value=col.header)
                cell1.font = bold
                cell1.fill = yellow_fill
                cell1.alignment = center
                cell1.border = border
                ws.merge_cells(f"{col_letter}1:{col_letter}2")

        # Write group labels in row 1 (merged across their span)
        for group_name, indices in group_spans.items():
            first_col = min(indices)
            last_col = max(indices)
            first_letter = get_column_letter(first_col)
            last_letter = get_column_letter(last_col)
            cell1 = ws.cell(row=1, column=first_col, value=group_name)
            cell1.font = bold
            cell1.fill = blue_fill
            cell1.alignment = center
            cell1.border = border
            if first_col != last_col:
                ws.merge_cells(f"{first_letter}1:{last_letter}1")
            # apply border to all cells in the merged range (openpyxl only styles top-left)
            for ci in range(first_col, last_col + 1):
                ws.cell(row=1, column=ci).border = border

        # ── Data rows (start at row 3) ─────────────────────────────────────
        for line_entity in lines:
            ws.append([resolve_field(line_entity, c.field) for c in columns])

        # ── Column widths ──────────────────────────────────────────────────
        for col_idx, col in enumerate(columns, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = max(12, len(col.header) + 2)

        # ── Row heights ────────────────────────────────────────────────────
        ws.row_dimensions[1].height = 28
        ws.row_dimensions[2].height = 36

        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


REGISTRY.register(LineListCSVGenerator)
REGISTRY.register(LineListXLSXGenerator)


# ── API-facing line list generator ────────────────────────────────────────────

_LINE_LIST_COLUMNS = [
    "Line No", "From", "To", "Fluid", "Phase",
    "Pressure (psig)", "Temp (°F)", "Density (lb/ft³)", "Vise (cP)",
    "Flow Rate BPD", "Flow Rate MMSCFD", "Flow Rate lb/h",
    "Velocity (ft/s)", "Nominal Pipe Size", "Piping Class",
    "Design Press", "Design T.Max", "Material",
    "Insulation Type", "Insulation/Protection",
    "P&ID Number", "Test Pressure", "Remarks", "Rev",
]

_LIQUID_FLUID_CODES = {"W", "WAP", "FW", "CW", "SW", "O", "LO", "HO", "P", "GO"}
_GAS_FLUID_CODES    = {"G", "GAS", "NG", "FG"}


def _infer_phase(fluid_code: str) -> str:
    fc = (fluid_code or "").strip().upper()
    if fc in _LIQUID_FLUID_CODES:
        return "Liquid"
    if fc in _GAS_FLUID_CODES:
        return "Gas"
    return ""


def _parse_line_no(line_no: str, convention=None):
    """Return (size, fluid_code, piping_class) via the adaptive project-aware
    parser (line_parser.parse_line). Backward-compatible 3-tuple shape; pass a
    learned ``convention`` for project-consistent parsing."""
    try:
        from line_parser import parse_line
        p = parse_line(line_no, convention)
        return p["size"], p["fluid_code"], p["piping_class"]
    except Exception:
        parts = (line_no or "").split("-")
        if len(parts) < 2:
            return "", "", ""
        return parts[0], (parts[1] if len(parts) > 1 else ""), (parts[-1] if len(parts) >= 3 else "")


def _parse_line_full(line_no: str, convention=None) -> dict:
    """Full adaptive parse (size, fluid, sequence, piping_class, insulation)."""
    try:
        from line_parser import parse_line
        return parse_line(line_no, convention)
    except Exception:
        s, f, p = _parse_line_no(line_no, convention)
        return {"line": line_no, "size": s, "fluid_code": f, "sequence": "",
                "piping_class": p, "insulation_type": "", "_low_confidence": []}


_NON_VALUES = {"", "-", "—", "n/a", "na", "tbd", "none", "null", "not defined",
               "notdefined", "xxxx"}


def _real(v) -> str:
    """Treat placeholder/junk extractions as empty so they never override a
    confidently-parsed value (spec: never present a non-value as engineering data)."""
    s = (v or "").strip()
    return "" if s.lower() in _NON_VALUES else s


def _build_line_row(line_no: str, fields: dict, ocr: dict, *,
                    recovered: bool = False, convention=None) -> dict:
    """Build one Line List row. ``fields`` is the backing entity's fields (``{}``
    for a recovered, entity-less pipeline). ``ocr`` is the line_list_data.json
    record for this line.

    Precedence (per adaptive-parser spec):
      * Nominal Pipe Size — the confidently-parsed first segment of the Line No
        is authoritative (rule 2); explicit/OCR only fill when parse is unsure.
      * Fluid / Piping Class / Insulation — an explicit, REAL entity value wins;
        otherwise OCR, then the adaptive parse. Placeholder non-values
        ("NOT DEFINED", "XXXX", "-", …) never override real data, and nothing is
        ever guessed."""
    fields = fields or {}
    ocr = ocr or {}
    parsed = _parse_line_full(line_no, convention)
    parsed_size, parsed_fluid, parsed_piping = (
        parsed["size"], parsed["fluid_code"], parsed["piping_class"])
    parsed_insul = parsed["insulation_type"]
    size_confident = "size" not in parsed.get("_low_confidence", [])

    # Size: parsed first segment is authoritative when confident (rule 2).
    if parsed_size and size_confident:
        size = parsed_size
    else:
        size = _real(fields.get("size")) or _real(ocr.get("pipe_size")) or parsed_size

    fluid_code   = _real(fields.get("fluid_code")) or parsed_fluid
    piping_class = _real(fields.get("piping_class")) or parsed_piping
    pid_number   = (fields.get("pid_number")    or "").strip()
    from_loc     = (fields.get("from_location") or "").strip()
    to_loc       = (fields.get("to_location")   or "").strip()
    if from_loc == "-":
        from_loc = ""
    if to_loc == "-":
        to_loc = ""

    phase = _infer_phase(fluid_code)

    # OCR fills fluid/piping/phase only where still blank (size already resolved
    # above with the parsed first segment authoritative).
    fluid_code   = fluid_code   or _real(ocr.get("fluid"))
    piping_class = piping_class or _real(ocr.get("piping_class"))
    # Insulation Type: explicit REAL entity field → OCR → adaptive parse (only a
    # separate trailing segment counts; never pulled from inside class parens).
    insulation   = (_real(fields.get("insulation_type"))
                    or _real(ocr.get("insulation"))
                    or parsed_insul)
    if not phase:
        ocr_phase = (ocr.get("phase") or "").strip()
        if ocr_phase.lower() in ("liquid", "gas", "vapor", "steam"):
            phase = ocr_phase.capitalize()

    blank = ""
    # Recovered pipelines have no engineering entity — note their provenance and
    # confidence so QA can tell a confirmed recovery from one needing review.
    remarks = blank
    if recovered:
        remarks = _recovered_remark(ocr)

    return {
        "Line No":               line_no,
        "From":                  from_loc,
        "To":                    to_loc,
        "Fluid":                 fluid_code,
        "Phase":                 phase,
        "Pressure (psig)":       (ocr.get("op_pressure")     or "").strip() or blank,
        "Temp (°F)":             (ocr.get("op_temp")          or "").strip() or blank,
        "Density (lb/ft³)":      blank,
        "Vise (cP)":             blank,
        "Flow Rate BPD":         blank,
        "Flow Rate MMSCFD":      blank,
        "Flow Rate lb/h":        blank,
        "Velocity (ft/s)":       blank,
        "Nominal Pipe Size":     size,
        "Piping Class":          piping_class,
        "Design Press":          (ocr.get("design_pressure")  or "").strip() or blank,
        "Design T.Max":          (ocr.get("design_temp")      or "").strip() or blank,
        "Material":              (ocr.get("material")         or "").strip() or blank,
        "Insulation Type":       insulation or blank,
        "Insulation/Protection": blank,
        "P&ID Number":           pid_number,
        "Test Pressure":         blank,
        "Remarks":               remarks,
        "Rev":                   blank,
    }


def generate_line_list(job_dir: str, job_id: int, db) -> List[dict]:
    """Return one dict per unique pipe line for the given job.

    The Line List represents engineering PIPELINES, not valve entities, so rows
    come from the UNION of two sources, keyed on Line No:
      1. canonical entities with a valid ``fields.line``;
      2. recovered pipelines from line_list_data.json (Pass 4 / Pass 4.5
         orientation OCR) — emitted even when no valve/instrument entity backs
         them, so orientation-recovered lines are visible in the deliverable.
    When the same Line No appears in both, the row merges (explicit entity
    fields preferred), and no duplicate is emitted.
    """
    import json
    from pathlib import Path

    canonical_path = Path(job_dir) / "canonical.json"
    if not canonical_path.exists():
        return []

    with canonical_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    # Load Pass 4 / Pass 4.5 OCR data — graceful no-op if file missing
    ocr_data: dict = {}
    ocr_path = Path(job_dir) / "line_list_data.json"
    if ocr_path.exists():
        try:
            with ocr_path.open(encoding="utf-8") as fh:
                ocr_data = json.load(fh) or {}
        except Exception:
            ocr_data = {}

    # Map each OCR record by normalized Line No so entity rows can merge it and
    # leftovers become recovered rows.
    ocr_by_norm: Dict[str, tuple] = {}
    for ln, data in ocr_data.items():
        if isinstance(ln, str) and "-" in ln and isinstance(data, dict):
            ocr_by_norm.setdefault(_norm_line(ln), (ln, data))

    entities = raw.get("entities", [])

    # ── Learn this project's numbering convention from ALL its line numbers ──
    # (entity lines + recovered lines). Per-job only — never reused across jobs.
    all_lines = [
        (e.get("fields") or {}).get("line", "")
        for e in entities
        if (e.get("fields") or {}).get("line")
    ] + [ln for (ln, _d) in ocr_by_norm.values()]
    convention = None
    try:
        from line_parser import learn_convention
        convention = learn_convention(all_lines)
    except Exception:
        convention = None

    seen: Set[str] = set()      # normalized Line No keys already emitted
    rows: List[dict] = []

    # ── Source 1: canonical entities with a valid line ──────────────────────
    for entity in entities:
        fields = entity.get("fields") or {}
        line_no = (fields.get("line") or "").strip()
        if not line_no or "-" not in line_no:
            continue
        norm = _norm_line(line_no)
        if norm in seen:
            continue
        seen.add(norm)
        # entity may carry pid at the top level
        if not (fields.get("pid_number")):
            fields = {**fields, "pid_number": entity.get("pid_number") or ""}
        ocr = (ocr_by_norm.get(norm) or (None, {}))[1]
        rows.append(_build_line_row(line_no, fields, ocr, convention=convention))

    # ── Source 2: recovered pipelines present only in line_list_data.json ───
    for norm, (line_no, data) in ocr_by_norm.items():
        if norm in seen:
            continue
        if not _is_engineering_line(line_no):
            continue
        seen.add(norm)
        rows.append(_build_line_row(line_no, {}, data, recovered=True,
                                    convention=convention))

    rows.sort(key=lambda r: r["Line No"])
    return rows
