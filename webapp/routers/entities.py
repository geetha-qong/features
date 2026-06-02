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

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.deliverables.canonical import CanonicalEntity
from webapp.deliverables.field_resolver import resolve_field
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
