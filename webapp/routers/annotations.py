"""User-annotation API for the Studio marking workflow.

Three endpoints serve the Studio canvas + drawer interactions for marking
symbols (valves, instruments, equipment) on a P&ID:

  GET    /api/v1/jobs/{job_id}/annotations
         All rows in `user_annotations` for the job, any status. The frontend
         filters client-side by status / sheet_number — server returns the
         whole set so a single fetch hydrates the canvas + counter overlays.

  POST   /api/v1/jobs/{job_id}/annotations
         Create a new annotation. Two flows:
           - linked_detection_index >= 0 → user clicked an existing YOLO
             detection. Look up Job.gpu_detections[i], compare its label-mapped
             (entity_class, sub_class) to the request body. Equal → status
             'user_confirmed' (no training-signal correction emitted). Differ
             → 'user_added' on user_annotations PLUS model_corrections('delete')
             flagging the original detection as false-positive.
           - linked_detection_index null / -1 → fresh mark. Insert both the
             user_annotation (status 'user_added', source 'user') and a
             matching model_corrections('add') row. The two are linked via
             user_annotations.linked_correction_id.
         See spec §3.4: collision rule on POST.

  PATCH  /api/v1/jobs/{job_id}/annotations/{entity_id}
         Partial update — status / tag / fields_json / sub_class. No
         auto-derived state changes; the client is in charge of the lifecycle.

  DELETE /api/v1/jobs/{job_id}/annotations/{entity_id}
         Hard-delete the row. Soft-rejection is PATCH with status='user_rejected'
         — this DELETE is for "user undoes the mark entirely" only.

Auth: same IDOR pattern as entities.py — owner or super_admin, returns 404
(not 403) for foreign jobs so we never leak job-ID existence.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.models import Job, ModelCorrection, UserAnnotation

router = APIRouter(prefix="/api/v1/jobs", tags=["annotations"])


# --- request / response models ---


BboxList = List[float]


class AnnotationCreate(BaseModel):
    entity_class: str
    sub_class: Optional[str] = None
    bbox: BboxList
    sheet_number: int = 1
    linked_detection_index: Optional[int] = None

    @field_validator("bbox")
    @classmethod
    def _bbox_len(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError("bbox must have exactly 4 elements [x1, y1, x2, y2]")
        return v

    @field_validator("entity_class")
    @classmethod
    def _entity_class_valid(cls, v: str) -> str:
        if v not in {"valve", "instrument", "equipment"}:
            raise ValueError(
                "entity_class must be one of 'valve', 'instrument', 'equipment'"
            )
        return v


class AnnotationPatch(BaseModel):
    status: Optional[str] = None
    tag: Optional[str] = None
    fields_json: Optional[Dict[str, Any]] = None
    sub_class: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"user_added", "user_confirmed", "user_rejected", "model_found"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v


class AnnotationRow(BaseModel):
    id: int
    job_id: int
    entity_id: str
    user_id: int
    source: str
    status: str
    entity_class: str
    sub_class: Optional[str]
    bbox: List[float]
    sheet_number: int
    placeholder_tag: Optional[str]
    tag: Optional[str]
    fields_json: Optional[Dict[str, Any]]
    linked_detection_index: Optional[int]
    linked_correction_id: Optional[int]
    created_at: Optional[str]
    updated_at: Optional[str]


class AnnotationsResponse(BaseModel):
    annotations: List[AnnotationRow]


class AnnotationCreateResponse(AnnotationRow):
    pass


# --- helpers ---


def _load_job_or_404(job_id: int, db: Session, current_user: models.User) -> Job:
    """Mirror of entities.py/exports.py auth pattern. 404 (not 403) for foreign
    jobs so we never leak whether a given job_id exists for another user."""
    job: Optional[Job] = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


def _row_to_response(row: UserAnnotation) -> AnnotationRow:
    """Serialize a UserAnnotation ORM row → AnnotationRow with ISO datetimes."""
    return AnnotationRow(
        id=row.id,
        job_id=row.job_id,
        entity_id=row.entity_id,
        user_id=row.user_id,
        source=row.source,
        status=row.status,
        entity_class=row.entity_class,
        sub_class=row.sub_class,
        bbox=list(row.bbox) if row.bbox is not None else [],
        sheet_number=row.sheet_number,
        placeholder_tag=row.placeholder_tag,
        tag=row.tag,
        fields_json=row.fields_json,
        linked_detection_index=row.linked_detection_index,
        linked_correction_id=row.linked_correction_id,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _detection_label_to_class(
    label: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """Map YOLO detection label → (entity_class, sub_class).

    Examples:
        "valve_bv"      → ("valve",      "BV")
        "valve_gt"      → ("valve",      "GT")
        "instrument_ft" → ("instrument", "FT")
        "equipment_p"   → ("equipment",  "P")
        "arrow_up"      → (None, None)   # direction labels are non-editable
        "connector_in"  → (None, None)
    """
    if not label or not isinstance(label, str):
        return None, None
    if label.startswith("valve_"):
        return "valve", label[len("valve_"):].upper() or None
    if label.startswith("instrument_"):
        return "instrument", label[len("instrument_"):].upper() or None
    if label.startswith("equipment_"):
        return "equipment", label[len("equipment_"):].upper() or None
    return None, None


def _load_detection(
    job: Job, idx: int
) -> Tuple[Optional[str], Optional[str]]:
    """Read Job.gpu_detections[idx] and return its (entity_class, sub_class).

    Both the v1-10 in-process inference shape (``label``) and the legacy
    Windows-worker shape (``yolo_class``) are accepted. Returns (None, None)
    when the index is out of bounds, the JSON is malformed, or the label
    doesn't map to a known editable class (direction / connector classes).
    """
    raw = job.gpu_detections
    if not raw:
        return None, None
    try:
        detections = json.loads(raw)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(detections, list) or idx < 0 or idx >= len(detections):
        return None, None
    det = detections[idx]
    if not isinstance(det, dict):
        return None, None
    label = det.get("label") or det.get("yolo_class")
    return _detection_label_to_class(label)


def _next_placeholder_tag(job_id: int, sub_class: Optional[str], db: Session) -> str:
    """Per-job sequence: USER-<SUB>-NNNN where NNNN is zero-padded existing count + 1.

    Counts existing user_annotations rows for the job at call time. Races are
    fine in practice — the UNIQUE constraint is on (job_id, entity_id), not on
    the placeholder tag, so two concurrent POSTs may both land "USER-BV-0001"
    but distinct entity_ids. Tag visibility is informational, not a key.
    """
    existing = db.query(UserAnnotation).filter(UserAnnotation.job_id == job_id).count()
    sub = (sub_class or "X").upper()
    return f"USER-{sub}-{existing + 1:04d}"


# --- endpoints ---


@router.get(
    "/{job_id}/annotations",
    response_model=AnnotationsResponse,
    responses={
        200: {"description": "All user_annotations rows for the job"},
        404: {"description": "Job not found / not owned by caller"},
    },
)
def list_annotations(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> AnnotationsResponse:
    job = _load_job_or_404(job_id, db, current_user)
    rows = (
        db.query(UserAnnotation)
        .filter(UserAnnotation.job_id == job.id)
        .order_by(UserAnnotation.id.asc())
        .all()
    )
    return AnnotationsResponse(annotations=[_row_to_response(r) for r in rows])


@router.post(
    "/{job_id}/annotations",
    response_model=AnnotationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Annotation created"},
        400: {"description": "Bad payload"},
        404: {"description": "Job not found / not owned by caller"},
        409: {"description": "Duplicate entity_id for this job"},
    },
)
def create_annotation(
    job_id: int,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> AnnotationRow:
    job = _load_job_or_404(job_id, db, current_user)

    entity_id = uuid.uuid4().hex
    bbox = list(payload.bbox)
    placeholder = _next_placeholder_tag(job.id, payload.sub_class, db)

    correction_id: Optional[int] = None
    source = "user"

    fresh_mark = (
        payload.linked_detection_index is None
        or payload.linked_detection_index < 0
    )

    if fresh_mark:
        # No existing detection → user drew a new bbox the model missed.
        # Emit both an annotation row and a model_corrections('add') so the
        # YOLO export script picks this up as false-negative training data.
        new_label_suffix = (payload.sub_class or "x").lower()
        new_label = f"{payload.entity_class}_{new_label_suffix}"
        correction = ModelCorrection(
            job_id=job.id,
            user_id=current_user.id,
            detection_index=-1,
            action="add",
            new_label=new_label,
            new_bbox=bbox,
        )
        db.add(correction)
        db.flush()  # populate correction.id without committing the whole txn
        correction_id = correction.id
        ann_status = "user_added"
        source = "user"
    else:
        # Linked to an existing model detection. Compare classes.
        det_class, det_sub = _load_detection(job, payload.linked_detection_index)
        same_class = (
            det_class == payload.entity_class
            and (det_sub or None) == (payload.sub_class or None)
        )
        if same_class:
            ann_status = "user_confirmed"
            source = "model"
        else:
            # Model said one thing, user said another → mark the model
            # detection as false-positive, and record the user's correct
            # interpretation as a fresh user_added annotation.
            ann_status = "user_added"
            source = "user"
            correction = ModelCorrection(
                job_id=job.id,
                user_id=current_user.id,
                detection_index=payload.linked_detection_index,
                action="delete",
            )
            db.add(correction)
            db.flush()
            correction_id = correction.id

    row = UserAnnotation(
        job_id=job.id,
        entity_id=entity_id,
        user_id=current_user.id,
        source=source,
        status=ann_status,
        entity_class=payload.entity_class,
        sub_class=payload.sub_class,
        bbox=bbox,
        sheet_number=payload.sheet_number,
        placeholder_tag=placeholder,
        tag=None,
        fields_json=None,
        linked_detection_index=payload.linked_detection_index,
        linked_correction_id=correction_id,
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:  # IntegrityError on (job_id, entity_id) UNIQUE
        db.rollback()
        # uuid4 collisions are astronomically unlikely; treat as 409 so callers
        # can retry rather than silently masking duplicate-write logic bugs.
        raise HTTPException(
            status_code=409,
            detail=f"annotation already exists for entity_id={entity_id}",
        ) from exc
    db.refresh(row)
    return _row_to_response(row)


@router.patch(
    "/{job_id}/annotations/{entity_id}",
    response_model=AnnotationRow,
    responses={
        200: {"description": "Updated annotation row"},
        400: {"description": "Bad payload"},
        404: {"description": "Job or annotation not found / not owned by caller"},
    },
)
def patch_annotation(
    job_id: int,
    entity_id: str,
    payload: AnnotationPatch,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> AnnotationRow:
    job = _load_job_or_404(job_id, db, current_user)

    row = (
        db.query(UserAnnotation)
        .filter(
            UserAnnotation.job_id == job.id,
            UserAnnotation.entity_id == entity_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"annotation {entity_id} not found in job {job_id}",
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        # No-op PATCH — return current state. Mirrors entities.py behavior.
        return _row_to_response(row)

    for key, value in updates.items():
        setattr(row, key, value)
    # Force updated_at to refresh — SQLAlchemy onupdate is a column default
    # that fires on UPDATE; we rely on it but bump explicitly so SQLite (which
    # ignores `timezone=True`) still gets a fresh stamp.
    row.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(row)
    return _row_to_response(row)


@router.delete(
    "/{job_id}/annotations/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # NOTE: don't add a `responses={204: …}` entry — newer FastAPI asserts
    # `is_body_allowed_for_status_code(204) == False` at route registration
    # time when a declared response exists for a body-forbidden status.
    # The 204 status is documented by `status_code=` alone.
    responses={
        404: {"description": "Job or annotation not found / not owned by caller"},
    },
)
def delete_annotation(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> None:
    job = _load_job_or_404(job_id, db, current_user)
    row = (
        db.query(UserAnnotation)
        .filter(
            UserAnnotation.job_id == job.id,
            UserAnnotation.entity_id == entity_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"annotation {entity_id} not found in job {job_id}",
        )
    db.delete(row)
    db.commit()
    return None
