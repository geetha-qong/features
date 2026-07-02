"""Editable-deliverables API.

Two endpoints serve the Studio drawer + Bulk Review workbench:

  GET  /api/v1/jobs/{job_id}/entities?deliverable_type={t}
       Returns all rows of `t` for the job, with per-field metadata (value,
       source, is_override, confidence) + the column schema (from the
       customer template). The frontend uses this to render both the
       drawer's editable form and the workbench's table.

  PATCH /api/v1/jobs/{job_id}/entities/{entity_id}
       Persists a partial update. `prior_value` is captured from the
       on-disk canonical (not from a previous override) so audit trail
       always references the pipeline-produced source-of-truth.

Auth: same IDOR pattern as exports.py — owner or super_admin, returns 404
(not 403) to avoid leaking other users' job IDs.
"""

import json
import re
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.deliverables.canonical import CanonicalEntity
from webapp.deliverables.field_resolver import resolve_field
from webapp.deliverables.line_fluids import propagate_line_fluids
from webapp.deliverables.sort_utils import instrument_sort_key
from webapp.deliverables.ids_schema import (
    TYPE_LABELS,
    get_ids_sections_for_type,
    normalize_subclass,
)
from webapp.deliverables.job_loader import JobCanonicalNotFound, load_canonical_for_job
from webapp.deliverables.overrides import (
    capture_prior_value,
    is_field_editable,
    load_canonical_with_overrides,
    resolve_field_raw,
)
from webapp.deliverables.template_loader import TemplateLoader
from webapp.models import EntityOverride, Job

router = APIRouter(prefix="/api/v1/jobs", tags=["entities"])

_loader = TemplateLoader()


# Maps deliverable_type → which CanonicalEntity.entity_class it presents.
# datasheet and instrument_index both render instruments (same class, different
# column projections from the template). valve_list = valves, equipment_list
# = equipment. The 6 design-only deliverables (control_narrative, etc.) are
# absent here — they have no generator yet, so they don't appear in the API.
DELIVERABLE_ENTITY_CLASS = {
    "valve_list": "valve",
    "instrument_index": "instrument",
    "datasheet": "instrument",
    "equipment_list": "equipment",
    "line_list": "valve",
    "io_list": "instrument",
}


# --- response models ---


class ColumnSchema(BaseModel):
    field: str                    # dot-notation path matching CanonicalEntity
    header: str                   # human-readable column header from the template
    order: int                    # column order in the deliverable
    editable: bool                # whether PATCH accepts this field
    group: Optional[str] = None   # optional group header (e.g. "AT WORKING CONDITIONS")


class FieldValue(BaseModel):
    """One cell in the entities response.

    `is_override`: True iff a row in entity_overrides exists for this
        (entity, field). The frontend renders an "edited" badge.
    `source`: "pid" if the underlying canonical has a non-null value,
        "manual" if the canonical value is null/empty (user-supplied
        field). Stays "pid" after an override of a pid-sourced field —
        the badge comes from is_override.
    """
    value: Any
    source: str = "pid"   # "pid" | "manual"
    is_override: bool = False


class EntityRow(BaseModel):
    entity_id: str
    entity_class: str
    sub_class: str
    tag: Optional[str]
    pid_number: str
    sheet_number: int
    values: Dict[str, FieldValue]   # keyed by ColumnSchema.field


class EntitiesResponse(BaseModel):
    deliverable_type: str
    customer_template_slug: str
    schema_: List[ColumnSchema] = Field(alias="schema")  # 'schema' shadows Pydantic
    entities: List[EntityRow]

    class Config:
        populate_by_name = True


class PatchRequest(BaseModel):
    fields: Dict[str, Any]
    """Map of field-path → new value. e.g. {"tag": "FT-202", "fields.size": "3\""}.

    Empty `fields` is a no-op (returns the current state, doesn't 400).
    """


class CreateEntityBody(BaseModel):
    """Payload for POST /jobs/{job_id}/entities — manually add a new entity."""
    entity_class: str               # "valve" | "instrument" | "equipment"
    sub_class: Optional[str] = ""
    fields: Dict[str, Any] = Field(default_factory=dict)
    """Flat field values using the same dot-notation as PATCH:
       "tag" → entity.tag, "fields.instrument_type" → entity.fields["instrument_type"], etc.
    """


class DatasheetFieldOut(BaseModel):
    field: str
    header: str
    source: str
    editable: bool
    value: Any
    is_override: bool = False
    options: Optional[List[str]] = None
    group: Optional[str] = None


class DatasheetSectionOut(BaseModel):
    name: str
    fields: List[DatasheetFieldOut]


class EntityDatasheetResponse(BaseModel):
    entity_id: str
    sub_class: str
    type_label: str
    type_supported: bool
    tag: Optional[str]
    pid_number: str
    sheet_number: int
    sections: List[DatasheetSectionOut]


# --- helpers ---


def _load_job_or_404(job_id: int, db: Session, current_user: models.User) -> Job:
    """Mirror of exports.py auth pattern. 404 (not 403) for foreign jobs."""
    job: Optional[Job] = db.get(Job, job_id)
    if job is None or not job.output_csv_path:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


def _build_field_value(
    entity: CanonicalEntity,
    field_path: str,
    is_override: bool,
) -> FieldValue:
    raw = resolve_field_raw(entity, field_path)
    # source = "pid" if the *original* canonical had a value here, "manual"
    # otherwise. We approximate "manual" as: the raw value is None or "" AND
    # there's no override (overrides always present user-supplied content;
    # "pid"-sourced overrides also count as user-edited but the field
    # originated from the P&ID). The frontend uses this only to decide
    # whether to render a "manual" hint label or the cyan "P&ID" badge.
    source = "pid"
    if (raw is None or raw == "") and not is_override:
        source = "manual"
    return FieldValue(value=raw, source=source, is_override=is_override)


# --- endpoints ---


@router.get(
    "/{job_id}/entities",
    response_model=EntitiesResponse,
    responses={
        200: {"description": "Entities + schema for the given deliverable_type"},
        400: {"description": "Unknown deliverable_type"},
        404: {"description": "Job or canonical not found / not owned by caller"},
    },
)
def get_entities(
    job_id: int,
    deliverable_type: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> EntitiesResponse:
    if deliverable_type not in DELIVERABLE_ENTITY_CLASS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown deliverable_type '{deliverable_type}'. "
                   f"Known: {sorted(DELIVERABLE_ENTITY_CLASS.keys())}",
        )

    job = _load_job_or_404(job_id, db, current_user)

    try:
        # Use the merged view: API returns the user-edited state, not the
        # raw pipeline output. The drawer + workbench display "what the user
        # would get if they exported right now".
        canonical = load_canonical_with_overrides(job.output_csv_path, job.id, db)
    except JobCanonicalNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"canonical.json missing for job {job_id}",
        )

    template = _loader.load_with_fallback(canonical.customer_template_slug)
    deliverable_cfg = template.deliverables.get(deliverable_type)
    if deliverable_cfg is None:
        # Template doesn't define this deliverable — fall back to the default
        # template so we never 500 just because a customer template omitted
        # a section. Frontend gets the default columns; admin can override.
        default = _loader.load_with_fallback("default")
        deliverable_cfg = default.deliverables.get(deliverable_type)
        if deliverable_cfg is None:
            # Shouldn't happen for any of the 4 generators we ship, but be
            # defensive — return an empty schema rather than crashing.
            deliverable_cfg = None  # type: ignore[assignment]

    columns_src = deliverable_cfg.columns if deliverable_cfg else []
    columns_src = sorted(columns_src, key=lambda c: c.order)
    schema = [
        ColumnSchema(
            field=c.field,
            header=c.header,
            order=c.order,
            editable=is_field_editable(c.field),
            group=getattr(c, "group", None),
        )
        for c in columns_src
    ]

    # Which entities did this caller override at all?
    overridden_ids: set[tuple[str, str]] = {
        (ov.entity_id, ov.field_name)
        for ov in db.query(EntityOverride.entity_id, EntityOverride.field_name)
        .filter(EntityOverride.job_id == job_id)
        .all()
    }

    target_class = DELIVERABLE_ENTITY_CLASS[deliverable_type]

    # Line list: fill blank Fluid/Phase via drawing-scoped evidence (a fluid-code
    # letter whose fluid was observed from a banner on this P&ID is applied to
    # other lines sharing that letter). Read-time only — canonical is untouched.
    if deliverable_type == "line_list":
        propagate_line_fluids(canonical.entities)

    # IO list: import _classify_system once outside the loop (used per-row below).
    if deliverable_type == "io_list":
        from webapp.deliverables.pipeline_emitter import _classify_system as _io_classify_system
    else:
        _io_classify_system = None  # type: ignore[assignment]

    # Load Pass 4 OCR data (line_list_data.json) for read-time injection into
    # engineering columns. Graceful no-op when file is absent.
    _line_ocr_data: dict = {}
    if deliverable_type == "line_list" and job.output_csv_path:
        _ocr_path = Path(job.output_csv_path).parent / "line_list_data.json"
        if _ocr_path.exists():
            try:
                with _ocr_path.open(encoding="utf-8") as _f:
                    _line_ocr_data = json.load(_f) or {}
            except Exception:
                _line_ocr_data = {}

    # Maps OCR JSON keys → template column field paths for line_list injection.
    _OCR_FIELD_MAP = {
        "fluid":           "fields.fluid_type",
        "phase":           "fields.phase",
        "op_pressure":     "fields.working_pressure",
        "op_temp":         "fields.working_temp",
        "design_pressure": "fields.design_press",
        "design_temp":     "fields.design_temp",
        "pipe_size":       "fields.size",
        "piping_class":    "fields.piping_class",
        "insulation":      "fields.insulation_type",
        "material":        "fields.material",
    }

    # Load Pass 5 equipment specs (equipment_specs.json) for read-time injection.
    _equip_specs_data: dict = {}
    if deliverable_type == "equipment_list" and job.output_csv_path:
        _equip_specs_path = Path(job.output_csv_path).parent / "equipment_specs.json"
        if _equip_specs_path.exists():
            try:
                with _equip_specs_path.open(encoding="utf-8") as _f:
                    _equip_specs_data = json.load(_f) or {}
            except Exception:
                _equip_specs_data = {}

    # Maps equipment_specs.json keys → template column field paths for equipment_list.
    _EQUIP_SPEC_FIELD_MAP = {
        "type":                  "fields.equip_spec_type",
        "rated_capacity":        "fields.rated_capacity",
        "differential_pressure": "fields.differential_pressure",
        "design_temperature":    "fields.design_temp",
        "motor_rating":          "fields.motor_rating",
        "material":              "fields.material",
        "quantity":              "fields.quantity",
    }

    rows: List[EntityRow] = []
    for entity in canonical.entities:
        if entity.entity_class != target_class:
            continue

        values: Dict[str, FieldValue] = {}
        for col in columns_src:
            is_ov = (str(entity.entity_id), col.field) in overridden_ids
            fv = _build_field_value(entity, col.field, is_ov)
            # Remarks is a manual-entry column for line_list — always blank.
            if deliverable_type == "line_list" and col.field == "fields.service_description":
                fv = FieldValue(value="", is_override=fv.is_override)
            values[col.field] = fv

        # line_list: derive Fluid, Pipe Size, Phase, and Piping Class from the line
        # number + fluid_code stored in canonical. These are never written to
        # fields.fluid_type / fields.phase / etc. by the emitter (it uses different
        # field names), so resolve_field_raw returns empty for them. Fill here from
        # what IS in canonical — same logic as generate_line_list() in line_list.py.
        if deliverable_type == "line_list":
            _line_tag = (entity.fields or {}).get("line", "") or ""
            _fluid_code_raw = (entity.fields or {}).get("fluid_code", "") or ""

            # parse size / fluid_code / piping_class out of the line number string
            # e.g. '20"-W-62151023-BGA' → size='20"', fluid='W', piping='BGA'
            _ll_parts = _line_tag.split("-")
            _ll_parsed_size    = _ll_parts[0] if _ll_parts else ""
            _ll_parsed_fluid   = _ll_parts[1] if len(_ll_parts) > 1 else ""
            if len(_ll_parts) >= 4 and _ll_parts[-2].isalpha() and len(_ll_parts[-2]) >= 2:
                _ll_parsed_piping = f"{_ll_parts[-2]}-{_ll_parts[-1]}"
            else:
                _ll_parsed_piping = _ll_parts[-1] if len(_ll_parts) >= 3 else ""

            _ll_fluid_code = (_fluid_code_raw.strip() or _ll_parsed_fluid).upper()

            # Fluid (fields.fluid_type): use fluid_code letter if no OCR banner name
            if "fields.fluid_type" in values and not values["fields.fluid_type"].value:
                if _ll_fluid_code:
                    values["fields.fluid_type"] = FieldValue(value=_ll_fluid_code, source="pid")

            # Nominal Pipe Size (fields.size): parse from line tag if blank or "NOT DEFINED"
            if "fields.size" in values:
                _sz = (values["fields.size"].value or "").strip()
                if not _sz or _sz.upper() == "NOT DEFINED":
                    if _ll_parsed_size:
                        values["fields.size"] = FieldValue(value=_ll_parsed_size, source="pid")

            # Piping Class (fields.piping_class): parse from line tag if blank
            if "fields.piping_class" in values and not values["fields.piping_class"].value:
                if _ll_parsed_piping:
                    values["fields.piping_class"] = FieldValue(value=_ll_parsed_piping, source="pid")

            # Phase (fields.phase): infer from fluid code if blank
            if "fields.phase" in values and not values["fields.phase"].value:
                _LIQUID_FC = {"W", "WAP", "FW", "CW", "SW", "O", "LO", "HO", "P", "GO"}
                _GAS_FC    = {"G", "GAS", "NG", "FG"}
                if _ll_fluid_code in _LIQUID_FC:
                    values["fields.phase"] = FieldValue(value="Liquid", source="pid")
                elif _ll_fluid_code in _GAS_FC:
                    values["fields.phase"] = FieldValue(value="Gas", source="pid")

            # Insulation Type (fields.insulation_type): extract trailing alpha suffix
            # from the piping class after derivation above.
            # BGA-H → H, BGA-HD → HD, BGA-ET → ET, BGA → (no suffix, skip)
            if "fields.insulation_type" in values and not values["fields.insulation_type"].value:
                _pc_resolved = (values.get("fields.piping_class", FieldValue(value="")).value or "").strip()
                if not _pc_resolved:
                    _pc_resolved = _ll_parsed_piping
                if "-" in _pc_resolved:
                    _insul_suffix = _pc_resolved.rsplit("-", 1)[-1]
                    if _insul_suffix.isalpha() and 1 <= len(_insul_suffix) <= 4:
                        values["fields.insulation_type"] = FieldValue(value=_insul_suffix, source="pid")

        # IO list: blank out fields.line_no if it's not a real pipe line number.
        # The LLM mis-classifies two types of values as line_no:
        #   1. P&ID drawing numbers: "MUK-62-1-0010-003-24C7" (starts with letters)
        #   2. Engineering/valve tags: "62-DB-151028" (matches \d+-[A-Z]+-\d+ pattern)
        # A real line number contains a pipe-spec marker — e.g. '3"-W-62151007-BGA'
        # or '250-WAP-XXXX-AS1LC' — it always contains at least one '"' or is never
        # purely <digits>-<UPPERCASE>-<digits>.
        if deliverable_type == "io_list":
            from webapp.deliverables.field_resolver import sanitize_line_no
            _lno_fv = values.get("fields.line_no")
            if _lno_fv and _lno_fv.value:
                _sanitized = sanitize_line_no(str(_lno_fv.value))
                if _sanitized != str(_lno_fv.value).strip():
                    values["fields.line_no"] = FieldValue(value=_sanitized, source="pid")

        # IO list: re-classify any legacy "FIELD" system value as BPCS or SIS.
        # "FIELD" means the emitter didn't know — reclassify at read time using
        # tag_type_code + instrument_type so canonical.json is not modified.
        if deliverable_type == "io_list" and _io_classify_system:
            _sys_fv = values.get("fields.system")
            if _sys_fv and (not _sys_fv.value or _sys_fv.value.upper() == "FIELD"):
                _type_code = (entity.fields or {}).get("tag_type_code", "") or ""
                _inst_type = (entity.fields or {}).get("instrument_type", "") or (entity.sub_class or "")
                _reclassified = _io_classify_system(_type_code, _inst_type)
                values["fields.system"] = FieldValue(value=_reclassified, source="pid")

        # Inject Pass 4 OCR engineering data BEFORE building EntityRow — Pydantic
        # copies the values dict on construction, so injection must happen first.
        if deliverable_type == "line_list" and _line_ocr_data:
            _line_key = (values.get("fields.line", FieldValue(value="")).value or "").strip()
            _ocr = _line_ocr_data.get(_line_key) or {}
            for _ocr_key, _col_field in _OCR_FIELD_MAP.items():
                if _col_field not in values:
                    continue
                if values[_col_field].value:
                    continue  # canonical already has a value — don't overwrite
                _ocr_val = (_ocr.get(_ocr_key) or "")
                if isinstance(_ocr_val, str):
                    _ocr_val = _ocr_val.strip()
                if _ocr_val and str(_ocr_val).lower() not in ("null", "none"):
                    values[_col_field] = FieldValue(value=_ocr_val, source="pid")

        # Inject Pass 5 equipment spec data BEFORE building EntityRow (same Pydantic rule).
        if deliverable_type == "equipment_list" and _equip_specs_data:
            _etag = (entity.tag or "").strip()
            _spec = _equip_specs_data.get(_etag) or {}
            for _spec_key, _col_field in _EQUIP_SPEC_FIELD_MAP.items():
                if _col_field not in values:
                    continue
                if values[_col_field].value:
                    continue  # canonical value takes priority
                _spec_val = (_spec.get(_spec_key) or "")
                if isinstance(_spec_val, str):
                    _spec_val = _spec_val.strip()
                if _spec_val and str(_spec_val).lower() not in ("null", "none"):
                    values[_col_field] = FieldValue(value=_spec_val, source="pid")

        rows.append(EntityRow(
            entity_id=str(entity.entity_id),
            entity_class=entity.entity_class,
            sub_class=entity.sub_class,
            tag=entity.tag,
            pid_number=entity.pid_number,
            sheet_number=entity.sheet_number,
            values=values,
        ))

    # Deduplicate line_list by fields.line — one row per unique line number.
    # Multiple valves on the same pipe run share the same line string; keep
    # the first occurrence (highest-confidence, earliest in pipeline output).
    # Also filter out invalid line designations (bare sizes like '2"' or '2"NC')
    # that the pipeline emits when only the diameter annotation was captured.
    # A valid line number must match: <digits> then optional " then - then a letter.
    # Supports both inch-symbol format (3"-P-62151007-BGA) and mm/numeric format
    # (50-ABL-XXXX-AS2LC). The " is made optional to cover both conventions.
    _VALID_LINE_RE = re.compile(r'^\d+(/\d+)?"?-[A-Z]', re.IGNORECASE)
    if deliverable_type == "line_list":
        seen_lines: set = set()
        deduped: List[EntityRow] = []
        for row in rows:
            line_val = row.values.get("fields.line")
            line_key = (line_val.value or "").strip() if line_val else ""
            if not line_key or not _VALID_LINE_RE.match(line_key):
                continue
            if line_key in seen_lines:
                continue
            seen_lines.add(line_key)
            deduped.append(row)
        rows = deduped

    # Sort rows in ascending natural order so the table always reads top-to-bottom
    # by tag/line number, regardless of the order entities were extracted.
    def _natural_key(s: Optional[str]) -> list:
        if not s:
            return ["\xff"]  # blanks sort to the end
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]

    if deliverable_type == "line_list":
        rows.sort(key=lambda r: _natural_key(
            (r.values["fields.line"].value if "fields.line" in r.values else None)
        ))
    else:
        rows.sort(key=lambda r: instrument_sort_key(r.tag or ""))

    return EntitiesResponse(
        deliverable_type=deliverable_type,
        customer_template_slug=canonical.customer_template_slug,
        schema=schema,
        entities=rows,
    )


@router.patch(
    "/{job_id}/entities/{entity_id}",
    responses={
        200: {"description": "Updated entity (full row)"},
        400: {"description": "Read-only field in payload, or unknown field path"},
        404: {"description": "Job, entity, or canonical not found"},
    },
)
def patch_entity(
    job_id: int,
    entity_id: str,
    payload: PatchRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    job = _load_job_or_404(job_id, db, current_user)

    # Validate the entity exists in canonical before touching the DB.
    try:
        canonical = load_canonical_for_job(job.output_csv_path)
    except JobCanonicalNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"canonical.json missing for job {job_id}",
        )
    target_entity = next(
        (e for e in canonical.entities if str(e.entity_id) == entity_id),
        None,
    )
    if target_entity is None:
        raise HTTPException(status_code=404, detail=f"entity {entity_id} not in job {job_id}")

    if not payload.fields:
        # No-op PATCH — return current merged state without touching the DB.
        return {"entity_id": entity_id, "applied": 0}

    # Validate every field is editable BEFORE writing any row. Atomic from the
    # client's point of view: either all updates land or none do.
    for fname in payload.fields:
        if not is_field_editable(fname):
            raise HTTPException(
                status_code=400,
                detail=f"field '{fname}' is read-only",
            )

    applied = 0
    for fname, new_value in payload.fields.items():
        prior = capture_prior_value(job.output_csv_path, entity_id, fname)

        # Skip if value identical to prior — keeps the audit trail tight
        # (re-saving the drawer shouldn't churn rows) and avoids the unique
        # constraint dance when the only change is a confidence pill blink.
        existing = (
            db.query(EntityOverride)
            .filter(
                EntityOverride.job_id == job_id,
                EntityOverride.entity_id == entity_id,
                EntityOverride.field_name == fname,
            )
            .first()
        )

        # The "current" value the user is overriding may be a prior override.
        # Capture prior_value from the on-disk canonical so audit always
        # points at the pipeline-produced source of truth.
        if existing is not None:
            if existing.new_value == new_value:
                continue
            existing.new_value = new_value
            existing.prior_value = prior   # refresh — earliest pipeline value
            existing.edited_by = current_user.id
            existing.edited_at = datetime.utcnow()
            applied += 1
        else:
            row = EntityOverride(
                job_id=job_id,
                entity_id=entity_id,
                field_name=fname,
                new_value=new_value,
                prior_value=prior,
                edited_by=current_user.id,
            )
            db.add(row)
            applied += 1

    db.commit()
    return {"entity_id": entity_id, "applied": applied}


@router.post(
    "/{job_id}/entities",
    status_code=201,
    responses={
        201: {"description": "New entity created in canonical.json"},
        400: {"description": "Invalid entity_class"},
        404: {"description": "Job or canonical.json not found"},
    },
)
def create_entity(
    job_id: int,
    payload: CreateEntityBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Manually create a new canonical entity for a job.

    Inserts a new entry directly into canonical.json (not via entity_overrides)
    and persists user-supplied field values as EntityOverride rows so they
    survive future pipeline re-runs that would overwrite canonical.json.

    Field path format (same as PATCH):
      "tag"                  → entity.tag (top-level)
      "fields.some_key"      → entity.fields["some_key"]
    Other paths are stored as-is inside entity.fields.
    """
    from webapp.deliverables.canonical import CANONICAL_SCHEMA_VERSION

    valid_classes = {"valve", "instrument", "equipment"}
    if payload.entity_class not in valid_classes:
        raise HTTPException(status_code=400, detail=f"entity_class must be one of {valid_classes}")

    job = _load_job_or_404(job_id, db, current_user)

    try:
        canonical = load_canonical_for_job(job.output_csv_path)
    except JobCanonicalNotFound:
        raise HTTPException(status_code=404, detail=f"canonical.json missing for job {job_id}")

    new_id = str(_uuid.uuid4())

    # Parse dot-notation field paths into top-level and nested values.
    tag: Optional[str] = None
    pid_number: str = ""
    nested_fields: Dict[str, Any] = {}

    for path, value in payload.fields.items():
        if not value and value != 0:
            continue
        str_value = str(value).strip() if value is not None else ""
        if not str_value:
            continue
        if path == "tag":
            tag = str_value
        elif path == "pid_number":
            pid_number = str_value
        elif path.startswith("fields."):
            nested_fields[path[len("fields."):]] = str_value
        else:
            nested_fields[path] = str_value

    # Build the raw dict and append to canonical.json directly (bypassing
    # Pydantic so we don't need to satisfy every required field for classes
    # we don't have data for — bbox stays at placeholder zeros).
    new_entity_raw = {
        "entity_id": new_id,
        "entity_class": payload.entity_class,
        "sub_class": payload.sub_class or "",
        "tag": tag,
        "pid_number": pid_number,
        "sheet_number": 1,
        "bbox": [0.0, 0.0, 0.0, 0.0],
        "fields": nested_fields,
        "vendor_match": None,
    }

    canonical_path = Path(job.output_csv_path).parent / "canonical.json"
    raw = json.loads(canonical_path.read_text())
    raw.setdefault("entities", []).append(new_entity_raw)
    canonical_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2))

    # Persist all non-empty field values as EntityOverride rows so they survive
    # a future canonical.json re-emit (which would wipe the appended entity).
    for fname, new_value in payload.fields.items():
        if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
            continue
        row = EntityOverride(
            job_id=job_id,
            entity_id=new_id,
            field_name=fname,
            new_value=new_value,
            prior_value=None,
            edited_by=current_user.id,
        )
        db.add(row)
    db.commit()

    return {"entity_id": new_id, "applied": len(payload.fields)}


@router.get(
    "/{job_id}/entities/{entity_id}/datasheet",
    response_model=EntityDatasheetResponse,
    responses={
        200: {"description": "Per-type datasheet (sectioned field metadata) for one entity"},
        404: {"description": "Job, entity, or canonical not found / not owned by caller"},
    },
)
def get_entity_datasheet(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> EntityDatasheetResponse:
    """Return the IDS (instrument datasheet) view for a single entity.

    Sections come from the entity's sub_class via the IDS schema: a Common
    section plus any type-specific section (CV / PT / PSV). Unknown sub_classes
    get the Common section only and `type_supported=False`. Each field carries
    its merged value (canonical + overrides) and whether the user has edited it.
    """
    job = _load_job_or_404(job_id, db, current_user)

    try:
        canonical = load_canonical_with_overrides(job.output_csv_path, job.id, db)
    except JobCanonicalNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"canonical.json missing for job {job_id}",
        )

    entity = next(
        (e for e in canonical.entities if str(e.entity_id) == entity_id),
        None,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail=f"entity {entity_id} not in job {job_id}")

    # Auto-fetch vendor datasheet (40+ fields) for instruments on every panel open.
    # Takes the prefix before the first hyphen: "PT-3069A" → "PT", "PIT-3087" → "PIT".
    # Normalises 3-letter codes to vendor API format: PIT→PT, FIT→FT, TIT→TT.
    # ids_* fields: only fills EMPTY slots so user overrides always win.
    # vendor_match identity: only built when not already set (preserves user vendor selection).
    if entity.entity_class in ("instrument", "valve"):
        from webapp.deliverables.vendor_match_client import fetch_vendor_datasheet
        tag = entity.tag or ""
        inst_code = tag.split("-")[0].upper()
        if len(inst_code) > 2 and inst_code.endswith("T"):
            inst_code = inst_code[0] + "T"
        elif len(inst_code) > 2 and inst_code.endswith("E"):
            inst_code = inst_code[0] + "E"
        if inst_code and len(inst_code) <= 4:
            vendor_data = fetch_vendor_datasheet(inst_code)
            if vendor_data:
                # Fill empty ids_* fields — user overrides always win.
                for k, v in vendor_data.items():
                    if k.startswith("ids_") and v and not entity.fields.get(k):
                        entity.fields[k] = v

                # Only build vendor_match if not already set (don't overwrite user's
                # manually-selected vendor from the Select Vendor dropdown).
                if not entity.vendor_match and (
                    vendor_data.get("_vendor_name") or vendor_data.get("_model_number")
                ):
                    from webapp.deliverables.canonical import VendorMatch
                    import uuid
                    catalog = {
                        k: v for k, v in vendor_data.items()
                        if not k.startswith("_") and not k.startswith("ids_") and v
                    }
                    entity.vendor_match = VendorMatch(
                        vendor_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, str(entity.entity_id))),
                        vendor_name=vendor_data.get("_vendor_name", ""),
                        product_name=vendor_data.get("_model_number", ""),
                        part_number=vendor_data.get("_product_id", ""),
                        catalog_fields=catalog,
                    )

    # Which field paths has this caller overridden for this entity?
    overridden = {
        ov.field_name
        for ov in db.query(EntityOverride.field_name)
        .filter(
            EntityOverride.job_id == job_id,
            EntityOverride.entity_id == entity_id,
        )
        .all()
    }

    sections_out: List[DatasheetSectionOut] = []
    for section in get_ids_sections_for_type(entity.sub_class):
        fields_out = [
            DatasheetFieldOut(
                field=f.path,
                header=f.header,
                source=f.source,
                editable=f.editable,
                value=resolve_field_raw(entity, f.path),
                is_override=f.path in overridden,
                options=f.options,
                group=f.group,
            )
            for f in section.fields
        ]
        sections_out.append(DatasheetSectionOut(name=section.name, fields=fields_out))

    type_key = normalize_subclass(entity.sub_class)
    type_label = TYPE_LABELS.get(type_key, entity.sub_class or "Generic")

    return EntityDatasheetResponse(
        entity_id=str(entity.entity_id),
        sub_class=entity.sub_class,
        type_label=type_label,
        type_supported=type_key is not None,
        tag=entity.tag,
        pid_number=entity.pid_number,
        sheet_number=entity.sheet_number,
        sections=sections_out,
    )
