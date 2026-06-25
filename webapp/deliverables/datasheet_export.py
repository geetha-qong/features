"""Generate formatted Instrument Data Sheet Excel for a single entity.

For PG (Pressure Gauge): loads pg_template.xlsx and fills live field values
into it — preserving all borders, merges, fonts, and fills exactly.
Falls back to a clean generic tabular layout for unsupported types.

Canonical path rules (from ids_schema.py docstring):
  tag_no              -> "tag"
  service_description -> "fields.service_description"
  pid_no              -> "pid_number"
  location            -> "fields.location"
  equipment_no        -> "fields.equipment_no"
  line_no             -> "fields.line_no"
  other process/user  -> "fields.ids_<col>"
  manufacturer        -> "vendor_match.vendor_name"
  model_no            -> "vendor_match.product_name"
  other vendor        -> "vendor_match.catalog_fields.<col>"
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

_TEMPLATE_DIR = Path(__file__).parent
_PG_TEMPLATE  = _TEMPLATE_DIR / "pg_template.xlsx"

_SPEC_API_URL = "https://dill-payday-chirping.ngrok-free.dev/api/instrument-datasheet"
_SPEC_API_KEY = "qong-local-dev-key-0000000000000000"

# Spec API key → canonical shortname (for lookup in spec_data dict)
# The spec API returns keys like "case_type", "dial_size_value", "connection_size" …
_SPEC_KEY = {
    # vendor catalog fields
    "case_type":              "case_type",
    "case_style":             "case_style",
    "mounting_type":          "mounting_type",
    "enclosure_ip_rating":    "enclosure_ip_rating",
    "liquid_fill_material":   "liquid_fill_material",
    "proc_conn_size":         "connection_size",
    "proc_conn_type":         "connection_type",
    "proc_conn_location":     "connection_position",
    "case_press_relief_type": "case_press_relief_type",
    "window_material":        "window_material",
    "bolting_material":       "bolting_material",
    "ring_material":          "ring_material",
    "case_material":          "case_material",
    "stem_material":          "stem_material",
    "lower_housing_material": "lower_housing_material",
    "elastic_element_type":   "elastic_element_type",
    "movement_style":         "movement_style",
    "nom_accuracy_grade":     "nom_accuracy_grade",
    "element_material":       "element_material",
    "movement_material":      "movement_material",
    "dial_scale_type":        "dial_scale_type",
    "pointer_adjustment":     "pointer_adjustment",
    "graduation_color":       "graduation_color",
    "scale_range_type":       "scale_range_type",
    "dial_material":          "dial_material",
    "dial_size":              "dial_size_value",
    "accessory":              "accessory",
    "accessory_code":         "accessory_code",
    "accessory_material":     "accessory_material",
    "seal_type":              "seal_type",
    "gasket_oring_material":  "gasket_oring_material",
    "fill_fluid_material":    "fill_fluid_material",
    # process fields also provided by spec
    "ambient_temp_min":       "ambient_temp_min",
    "ambient_temp_max":       "ambient_temp_max",
    "ambient_temp_unit":      "ambient_temp_unit",
    "instrument_range_min":   "instrument_range_min",
    "instrument_range_max":   "instrument_range_max",
    "instrument_range_unit":  "instrument_range_unit",
    "model_no":               "model_number",
}


def _fetch_spec(inst_type: str) -> Dict[str, str]:
    """Call the external spec API server-side. Returns {} on any failure."""
    try:
        import requests as _req
        resp = _req.post(
            _SPEC_API_URL,
            json={"instType": inst_type},
            headers={"Content-Type": "application/json", "X-API-KEY": _SPEC_API_KEY},
            timeout=8,
        )
        if resp.ok:
            body = resp.json()
            data = body.get("data", body)
            return {k: str(v).strip() for k, v in data.items() if v is not None}
    except Exception:
        pass
    return {}


def _fv(ds: Any) -> Dict[str, str]:
    """Build flat {canonical_path: str_value} from all datasheet sections."""
    out: Dict[str, str] = {}
    for sec in ds.sections:
        for f in sec.fields:
            val = f.value
            out[f.field] = str(val).strip() if val is not None else ""
    return out


def _fill_pg(ws, ds: Any, spec: Dict[str, str]) -> None:
    """Fill dynamic values into the pre-loaded PG template worksheet."""
    fv = _fv(ds)

    def v(canonical_path: str, spec_shortname: str = "", default: str = "-") -> str:
        """Return value from canonical, falling back to spec API, then default."""
        val = fv.get(canonical_path, "")
        if val:
            return val
        if spec_shortname:
            spec_key = _SPEC_KEY.get(spec_shortname, spec_shortname)
            sv = spec.get(spec_key, "")
            if sv:
                return sv
        return default

    def s(coord: str, value: str) -> None:
        ws[coord] = value

    # ── Row 1: company banner — keep as-is from template ────────────────────

    # ── GENERAL (rows 2–7) ───────────────────────────────────────────────────
    tag = ds.tag or v("tag", "", "-")
    s("F2", tag)
    s("F3", v("fields.service_description"))
    s("E4", v("pid_number", "", ds.pid_number or "-"))
    s("J4", v("fields.location"))
    s("E5", v("fields.ids_area_classification"))
    s("J5", v("fields.ids_ignition_group", "", v("fields.ids_temp_class")))
    s("F6", v("fields.ids_ambient_temp_min", "ambient_temp_min"))
    s("H6", v("fields.ids_ambient_temp_max", "ambient_temp_max"))
    s("I6", "-")
    s("E7", v("fields.equipment_no"))
    s("J7", v("fields.ids_equipment_system"))

    # ── CERTIFICATION (rows 8–9) ─────────────────────────────────────────────
    s("E8", v("fields.ids_nace_requirement"))
    s("J8", v("fields.ids_ibr_requirement"))
    s("E9", v("fields.ids_certification_special_requirement"))
    s("J9", "-")

    # ── PIPE LINE (rows 10–12) ───────────────────────────────────────────────
    s("F10", v("fields.line_no"))
    line_size = v("fields.ids_line_size")
    line_sch  = v("fields.ids_line_schedule")
    s("F11", " / ".join(p for p in [line_size, line_sch] if p != "-") or "-")
    pipe_parts = [v("fields.ids_pipe_class"), v("fields.ids_pipe_material"), v("fields.ids_insulation")]
    s("F12", " | ".join(p for p in pipe_parts if p != "-") or "-")

    # ── PROCESS CONDITIONS (rows 13–16) ─────────────────────────────────────
    s("F13", "-")  # Case — no API field
    fluid_parts = [v("fields.ids_fluid_name"), v("fields.ids_fluid_state"), v("fields.ids_fluid_phase")]
    s("F14", " | ".join(p for p in fluid_parts if p != "-") or "-")

    s("F15", v("fields.ids_corrosive"))
    s("G15", v("fields.ids_erosive"))
    s("H15", v("fields.ids_toxic"))
    s("I15", v("fields.ids_build_up"))

    s("F16", v("fields.ids_solidifying"))
    s("G16", v("fields.ids_pulsation"))
    s("H16", v("fields.ids_coagulation"))
    s("I16", v("fields.ids_contains_particles"))

    # ── DESIGN CONDITIONS (rows 18–19) ───────────────────────────────────────
    s("D18", v("fields.ids_design_pressure_unit", "", "kg/cm2G"))
    s("E18", v("fields.ids_design_pressure_min"))
    s("F18", "-")
    s("G18", v("fields.ids_design_pressure_max"))

    s("D19", v("fields.ids_design_temp_unit", "", "deg C"))
    s("E19", v("fields.ids_design_temp_min"))
    s("F19", "-")
    s("G19", v("fields.ids_design_temp_max"))

    # ── OPERATING CONDITIONS (rows 21–22) ────────────────────────────────────
    s("D21", v("fields.ids_operating_pressure_unit", "", "kg/cm2G"))
    s("E21", v("fields.ids_operating_pressure_min"))
    s("F21", v("fields.ids_operating_pressure_nor"))
    s("G21", v("fields.ids_operating_pressure_max"))

    s("D22", v("fields.ids_operating_temp_unit", "", "deg C"))
    s("E22", v("fields.ids_operating_temp_min"))
    s("F22", v("fields.ids_operating_temp_nor"))
    s("G22", v("fields.ids_operating_temp_max"))

    # Row 23: Viscosity | Density
    s("F23", v("fields.ids_viscosity"))
    s("H23", v("fields.ids_density"))
    s("J23", "-")

    # ── RANGE (rows 25–27) ───────────────────────────────────────────────────
    rng_unit = v("fields.ids_instrument_range_unit", "instrument_range_unit", "bar")
    rng_min  = v("fields.ids_instrument_range_min",  "instrument_range_min")
    rng_max  = v("fields.ids_instrument_range_max",  "instrument_range_max")

    for row in [25, 26, 27]:
        ws[f"D{row}"] = rng_unit
        ws[f"E{row}"] = rng_min
        ws[f"F{row}"] = rng_unit
        ws[f"G{row}"] = rng_max

    # ── DUAL-PANEL BODY (rows 28–53) ─────────────────────────────────────────
    _C = "vendor_match.catalog_fields."   # shorthand prefix

    rng_min_u = f"{rng_min} {rng_unit}".strip() if rng_min != "-" else "-"
    rng_max_u = f"{rng_max} {rng_unit}".strip() if rng_max != "-" else "-"

    amb_min = v("fields.ids_ambient_temp_min", "ambient_temp_min")
    amb_max = v("fields.ids_ambient_temp_max", "ambient_temp_max")
    amb_unit = spec.get("ambient_temp_unit", "°C") or "°C"
    amb_min_u = f"{amb_min} {amb_unit}" if amb_min != "-" else "-"
    amb_max_u = f"{amb_max} {amb_unit}" if amb_max != "-" else "-"

    def cv(col: str, spec_key: str = "") -> str:
        """Look up a vendor catalog field."""
        return v(_C + col, spec_key or col)

    left = [
        (28, cv("case_type")),
        (29, cv("case_style")),
        (30, cv("mounting_type")),
        (31, cv("proc_conn_size")),
        (32, cv("proc_conn_type")),
        (33, cv("proc_conn_location")),
        (34, cv("case_press_relief_type")),
        (35, cv("window_material")),
        (36, cv("ring_material")),
        (37, cv("case_material")),
        (38, cv("stem_material")),
        (39, cv("enclosure_ip_rating")),
        (40, cv("elastic_element_type")),
        (41, cv("movement_style")),
        (42, cv("nom_accuracy_grade")),
        (43, cv("element_material")),
        (44, cv("movement_material")),
        (45, cv("dial_scale_type")),
        (46, cv("pointer_adjustment")),
        (47, cv("graduation_color")),
        (48, cv("scale_range_type")),
        (49, cv("dial_material")),
        (50, cv("dial_size")),
        (51, cv("lower_housing_material")),
        (52, cv("liquid_fill_material")),
        (53, cv("fill_fluid_material")),
    ]

    right = [
        (28, cv("bolting_material")),
        (29, cv("gasket_oring_material")),
        (30, cv("seal_type")),
        (31, cv("accessory")),
        (32, cv("accessory_code")),
        (33, cv("accessory_material")),
        (34, cv("fill_fluid_material")),
        (35, cv("liquid_fill_material")),
        (36, cv("window_material")),
        (37, cv("ring_material")),
        (38, cv("lower_housing_material")),
        (39, cv("stem_material")),
        (40, cv("enclosure_ip_rating")),
        (41, cv("case_press_relief_type")),
        (42, rng_min_u),
        (43, rng_max_u),
        (44, amb_min_u),
        (45, amb_max_u),
        (46, cv("proc_conn_size")),
        (47, cv("proc_conn_type")),
        (48, cv("proc_conn_location")),
        (49, cv("case_press_relief_type")),
        (50, cv("enclosure_ip_rating")),
        (51, cv("nom_accuracy_grade")),
        (52, "-"),
        (53, "-"),
    ]

    for row, val in left:
        ws[f"E{row}"] = val
    for row, val in right:
        ws[f"J{row}"] = val

    # ── PURCHASE (rows 54–57) ────────────────────────────────────────────────
    mfr = fv.get("vendor_match.vendor_name", "")
    if not mfr:
        mfr = spec.get("manufacturer", "-")
    s("E54", mfr or "-")

    mdl = fv.get("vendor_match.product_name", "")
    if not mdl:
        mdl = spec.get("model_number", "-")
    s("E55", mdl or "-")

    s("E56", v("fields.ids_mr_no"))
    s("E57", v("fields.ids_po_no"))

    # ── NOTES (rows 58–64) — static, keep from template ─────────────────────

    # ── TITLE BLOCK ─────────────────────────────────────────────────────────
    moc = v("fields.ids_moc_no")
    if moc != "-":
        ws["A66"] = f"MOC No.  {moc}"

    job_ref = v("fields.ids_job_id_ref")
    if job_ref != "-":
        ws["F66"] = f"JOB ID  {job_ref}"

    ws["A72"] = v("fields.ids_rev", "", "")
    ws["B72"] = v("fields.ids_prepared_by", "", "")
    ws["C72"] = v("fields.ids_checked_by", "", "")
    ws["D72"] = v("fields.ids_approved_by", "", "")
    ws["E72"] = v("fields.ids_doc_date", "", "")


# ── Generic fallback (non-PG types) ───────────────────────────────────────────

def _build_generic(wb, ds: Any) -> None:
    ws = wb.active
    ws.title = (ds.tag or "Datasheet")[:31]

    _THIN = Side(style="thin")
    _BOX  = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)
    _FN   = Font(name="Arial", size=8)
    _FB   = Font(name="Arial", size=8, bold=True)
    _FTB  = Font(name="Arial", size=11, bold=True)
    _GRAY = PatternFill(fill_type="solid", fgColor="D9D9D9")
    _BLUE = PatternFill(fill_type="solid", fgColor="BDD7EE")
    _AL   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
    _AC   = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 36

    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    ws.merge_cells("A1:C1")
    ws["A1"] = f"INSTRUMENT DATASHEET — {ds.type_label}"
    ws["A1"].font = _FTB; ws["A1"].fill = _BLUE
    ws["A1"].border = _BOX; ws["A1"].alignment = _AC
    ws.row_dimensions[1].height = 20

    row = 2
    for label, val in [
        ("Tag No.",   ds.tag or "-"),
        ("Type",      ds.type_label),
        ("P&ID No.",  ds.pid_number or "-"),
        ("Sheet No.", str(ds.sheet_number) if ds.sheet_number else "-"),
    ]:
        ws.row_dimensions[row].height = 13
        c = ws.cell(row=row, column=1, value=label)
        c.font = _FB; c.border = _BOX; c.alignment = _AL
        ws.merge_cells(f"B{row}:C{row}")
        c2 = ws.cell(row=row, column=2, value=val)
        c2.font = _FN; c2.border = _BOX; c2.alignment = _AL
        ws.cell(row=row, column=3).border = _BOX
        row += 1

    row += 1
    for sec in ds.sections:
        ws.merge_cells(f"A{row}:C{row}")
        c = ws.cell(row=row, column=1, value=sec.name)
        c.font = _FB; c.fill = _GRAY; c.border = _BOX; c.alignment = _AL
        ws.cell(row=row, column=2).border = _BOX
        ws.cell(row=row, column=3).border = _BOX
        ws.row_dimensions[row].height = 13
        row += 1
        for f in sec.fields:
            val = str(f.value).strip() if f.value is not None else "-"
            c1 = ws.cell(row=row, column=1, value=f.header)
            c1.font = _FB; c1.border = _BOX; c1.alignment = _AL
            ws.merge_cells(f"B{row}:C{row}")
            c2 = ws.cell(row=row, column=2, value=val)
            c2.font = _FN; c2.border = _BOX; c2.alignment = _AL
            ws.cell(row=row, column=3).border = _BOX
            ws.row_dimensions[row].height = 13
            row += 1


# ── Public API ────────────────────────────────────────────────────────────────

def generate_datasheet_excel(ds: Any, spec: Optional[Dict[str, str]] = None) -> bytes:
    """Return a formatted Excel workbook as bytes.

    For PG instruments, loads the template and fills in live values,
    supplementing with spec API data where canonical fields are empty.
    """
    from webapp.deliverables.ids_schema import normalize_subclass

    type_key = normalize_subclass(ds.sub_class)

    if type_key == "PG" and _PG_TEMPLATE.exists():
        # Fetch spec API values if not already provided
        if spec is None:
            spec = _fetch_spec("PG")
        wb = openpyxl.load_workbook(_PG_TEMPLATE)
        ws = wb.active
        ws.title = (ds.tag or "Datasheet")[:31]
        _fill_pg(ws, ds, spec)
    else:
        wb = openpyxl.Workbook()
        _build_generic(wb, ds)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
