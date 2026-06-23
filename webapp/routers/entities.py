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
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.deliverables.canonical import CanonicalEntity
from webapp.deliverables.field_resolver import resolve_field
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
}


# --- response models ---


class ColumnSchema(BaseModel):
    field: str           # dot-notation path matching CanonicalEntity
    header: str          # human-readable column header from the template
    order: int           # column order in the deliverable
    editable: bool       # whether PATCH accepts this field


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
    rows: List[EntityRow] = []
    for entity in canonical.entities:
        if entity.entity_class != target_class:
            continue
        values: Dict[str, FieldValue] = {}
        for col in columns_src:
            is_ov = (str(entity.entity_id), col.field) in overridden_ids
            values[col.field] = _build_field_value(entity, col.field, is_ov)
        rows.append(EntityRow(
            entity_id=str(entity.entity_id),
            entity_class=entity.entity_class,
            sub_class=entity.sub_class,
            tag=entity.tag,
            pid_number=entity.pid_number,
            sheet_number=entity.sheet_number,
            values=values,
        ))

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


@router.get(
    "/{job_id}/entities/{entity_id}/datasheet/export",
    responses={
        200: {
            "description": "Formatted Excel instrument datasheet",
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            },
        },
        404: {"description": "Job, entity, or canonical not found"},
    },
)
def export_entity_datasheet(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Response:
    """Return a formatted Excel instrument data sheet for a single entity."""
    from webapp.deliverables.datasheet_export import generate_datasheet_excel

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
            )
            for f in section.fields
        ]
        sections_out.append(DatasheetSectionOut(name=section.name, fields=fields_out))

    type_key = normalize_subclass(entity.sub_class)
    type_label = TYPE_LABELS.get(type_key, entity.sub_class or "Generic")

    ds = EntityDatasheetResponse(
        entity_id=str(entity.entity_id),
        sub_class=entity.sub_class,
        type_label=type_label,
        type_supported=type_key is not None,
        tag=entity.tag,
        pid_number=entity.pid_number,
        sheet_number=entity.sheet_number,
        sections=sections_out,
    )

    xlsx_bytes = generate_datasheet_excel(ds)
    tag_slug = (entity.tag or "datasheet").replace("/", "_").replace(" ", "_")
    filename = f"{tag_slug}_datasheet.xlsx"

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Instrument spec proxy ─────────────────────────────────────────────────────
# The spec API lives on an external ngrok URL which browsers can't call
# directly (CORS). This endpoint proxies the request server-side.

_SPEC_API_URL = "https://dill-payday-chirping.ngrok-free.dev/api/instrument-datasheet"
_SPEC_API_KEY = "qong-local-dev-key-0000000000000000"


class _SpecRequest(BaseModel):
    instType: str


@router.post(
    "/instrument-spec",
    responses={200: {"description": "Instrument spec data from upstream API"}},
)
def proxy_instrument_spec(
    payload: _SpecRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Proxy POST to the external instrument-spec API to avoid browser CORS."""
    import requests as _requests

    try:
        resp = _requests.post(
            _SPEC_API_URL,
            json={"instType": payload.instType},
            headers={"Content-Type": "application/json", "X-API-KEY": _SPEC_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
