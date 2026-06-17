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
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response, status
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


class OcrBboxRequest(BaseModel):
    """Re-OCR a single element's bbox to recover its true tag.

    bbox is NORMALIZED (fractions 0..1 of page width/height) so it's independent
    of whatever zoom/render resolution the canvas is at — the server maps it onto
    the source page image's pixel dims. pad_frac expands the crop slightly so a
    tag sitting just outside the symbol bbox is still captured."""
    bbox: List[float]
    # P&ID tags sit OUTSIDE the symbol bbox (above/beside it), so the crop must
    # expand well past the symbol to capture the tag text. ~1x each side works.
    pad_frac: float = 1.0

    @field_validator("bbox")
    @classmethod
    def _bbox_norm(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError("bbox must have 4 elements [x0,y0,x1,y1] (normalized 0..1)")
        for c in v:
            if c < -0.05 or c > 1.05:
                raise ValueError("bbox coords must be normalized fractions in [0,1]")
        return v


class OcrBboxResponse(BaseModel):
    text: str          # best single tag-shaped candidate (or raw text if none matched)
    found: bool        # a tag-shaped candidate was found
    candidates: List[str] = []  # all tag-shaped tokens, ranked (user disambiguates)
    raw: str = ""      # full OCR output (debug / fallback)


# Generic P&ID tag shape: "62-BV-151109", "62-FE-151010", "P-101", with optional
# trailing instance letter. Tolerant of OCR spacing around the dashes.
_TAG_TOKEN_RE = re.compile(r"\b\d{1,4}\s*-\s*[A-Z]{1,5}\s*-?\s*\d{2,7}[A-Z]?\b")


def _tag_candidates(ocr_text: str) -> List[str]:
    """Pull tag-shaped tokens from noisy OCR text, de-spaced + de-duped, ranked
    by length (longer = more complete tag). Dense crops capture neighbouring
    tags too, so we return all and let the user pick."""
    if not ocr_text:
        return []
    norm = ocr_text.upper().replace("\n", " ")
    seen, out = set(), []
    for m in _TAG_TOKEN_RE.finditer(norm):
        tok = re.sub(r"\s+", "", m.group(0))
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    out.sort(key=len, reverse=True)
    return out


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


# ── Annotation → canonical (deliverable) sync ────────────────────────────────
#
# Mark-Symbol annotations live in `user_annotations` (training signal). Exports,
# the DatasheetDrawer, and Bulk Review all read canonical.json + entity_overrides.
# To make a user-added symbol appear in those (and a deleted/rejected one
# disappear), we mirror a TAGGED annotation into canonical.json. Product rule
# (chosen 2026-06-17): a mark only reaches deliverables ONCE IT HAS A TAG; an
# untagged or user_rejected mark is removed from canonical.
#
# canonical.json (file) is the source of truth the deliverable path reads; the
# canonical_entities DB index is refreshed best-effort (admin cross-job queries).
# Annotation entity_ids are uuid4 and pipeline canonical ids are uuid5 — the id
# spaces don't collide, so upsert/remove by entity_id can't touch a pipeline row.

_EXPORTABLE_STATUSES = {"user_added", "user_confirmed"}


def _canonical_path(job: Job) -> Optional[Path]:
    if not job.output_csv_path:
        return None
    return Path(job.output_csv_path).parent / "canonical.json"


def _entity_dict_from_annotation(row: UserAnnotation) -> Dict[str, Any]:
    """Build a canonical entity dict matching entities.create_entity's shape."""
    fields: Dict[str, Any] = dict(row.fields_json or {})
    pid_number = str(fields.pop("pid_number", "") or "")
    return {
        "entity_id": row.entity_id,
        "entity_class": row.entity_class,
        "sub_class": row.sub_class or "",
        "tag": row.tag,
        "pid_number": pid_number,
        "sheet_number": row.sheet_number or 1,
        "bbox": list(row.bbox) if row.bbox else [0.0, 0.0, 0.0, 0.0],
        "fields": fields,
        "vendor_match": None,
    }


def _refresh_canonical_db_index(job: Job, db: Session) -> None:
    """Best-effort refresh of the canonical_entities read-index (admin queries).
    Non-fatal: the deliverable path reads the file, not this index."""
    try:
        from webapp.deliverables.job_loader import load_canonical_for_job
        from webapp.deliverables.canonical_db_index import sync_canonical_to_db

        canonical = load_canonical_for_job(job.output_csv_path)
        sync_canonical_to_db(canonical, db)
        db.commit()
    except Exception:
        db.rollback()


def _sync_annotation_to_canonical(job: Job, row: UserAnnotation, db: Session) -> None:
    """Upsert (tagged + exportable) or remove (untagged / rejected) the
    annotation's entity in canonical.json so deliverables/drawer/bulk-review
    reflect it. Idempotent; safe no-op when canonical.json is absent."""
    path = _canonical_path(job)
    if path is None or not path.exists():
        return
    raw = json.loads(path.read_text())
    ents = [e for e in raw.get("entities", []) if e.get("entity_id") != row.entity_id]
    should_export = bool(row.tag and row.tag.strip()) and row.status in _EXPORTABLE_STATUSES
    if should_export:
        ents.append(_entity_dict_from_annotation(row))
    raw["entities"] = ents
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    _refresh_canonical_db_index(job, db)


def _remove_annotation_from_canonical(job: Job, entity_id: str, db: Session) -> None:
    """Drop the annotation's entity from canonical.json (delete flow)."""
    path = _canonical_path(job)
    if path is None or not path.exists():
        return
    raw = json.loads(path.read_text())
    ents = raw.get("entities", [])
    kept = [e for e in ents if e.get("entity_id") != entity_id]
    if len(kept) != len(ents):
        raw["entities"] = kept
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        _refresh_canonical_db_index(job, db)


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
    # Mirror into canonical.json so a now-tagged mark appears in exports/drawer/
    # bulk-review (or is removed if it was untagged / rejected).
    _sync_annotation_to_canonical(job, row, db)
    return _row_to_response(row)


@router.delete(
    "/{job_id}/annotations/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # CRITICAL FastAPI quirk for 204:
    # - DO NOT set a `-> None` return annotation. FastAPI derives a
    #   response_field from it and trips
    #   `assert is_body_allowed_for_status_code(204)` at registration time.
    # - DO NOT add `responses={204: ...}` for the same reason.
    # - Return a `Response(status_code=204)` from the function body explicitly.
    # Set `response_class=Response` so FastAPI sticks with a no-body response.
    response_class=Response,
    responses={
        404: {"description": "Job or annotation not found / not owned by caller"},
    },
)
def delete_annotation(
    job_id: int,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
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
    # Remove from canonical.json so a deleted mark disappears from exports/
    # drawer/bulk-review (training corrections were already recorded).
    _remove_annotation_from_canonical(job, entity_id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _source_page_path(job: Job) -> Optional[Path]:
    """Locate the hi-res source page image the bboxes/tiles came from."""
    dirs = []
    if job.output_csv_path:
        dirs.append(Path(job.output_csv_path).parent)
    for d in dirs:
        for cand in (d / "tmp" / "page_0_full.png", d / "page_0_full.png"):
            if cand.exists():
                return cand
    return None


_VISION_TAG_PROMPT = (
    "This image is a small crop from a P&ID engineering drawing, centered on ONE "
    "component (a valve, instrument, or equipment item). Read its TAG — the "
    "alphanumeric identifier printed next to the symbol, e.g. '62-BV-151109', "
    "'62-FE-151010', 'P-101'. Return ONLY the single tag string for the component "
    "nearest the centre of the image, with no other words. If you cannot read a "
    "tag, return exactly: NONE"
)


def _vision_read_tag(crop_png_b64: str) -> str:
    """Ask the OpenRouter vision model to read the tag from a tight crop. A
    focused crop is far more accurate than the whole-tile pass (and than local
    OCR, which can't read the small/rotated tag text). Returns the raw model
    string ('' on NONE / empty)."""
    from extractor import get_client, DEFAULT_MODEL

    client = get_client()
    resp = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_TAG_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{crop_png_b64}"}},
                ],
            }
        ],
        max_tokens=30,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.upper() == "NONE":
        return ""
    return text


@router.post(
    "/{job_id}/ocr-bbox",
    response_model=OcrBboxResponse,
    responses={
        200: {"description": "Best tag candidate read from the crop (may be empty)"},
        404: {"description": "Job / page image not found, or not owned by caller"},
        503: {"description": "Vision engine unavailable"},
    },
)
def ocr_bbox(
    job_id: int,
    payload: OcrBboxRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> OcrBboxResponse:
    """Re-read the tag for a single element by sending a tight crop of the source
    page to the vision model. The whole-tile extraction pass misreads dense tags;
    a focused crop recovers the true text. Returns the best-guess string for the
    user to accept (they then save it via the normal tag-edit path)."""
    job = _load_job_or_404(job_id, db, current_user)

    page_path = _source_page_path(job)
    if page_path is None:
        raise HTTPException(status_code=404, detail="source page image not found for this job")

    try:
        import base64 as _b64
        import io as _io
        from PIL import Image
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"imaging stack unavailable: {type(e).__name__}")

    try:
        im = Image.open(str(page_path)).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"page image unreadable: {e}")

    w, h = im.size
    x0, y0, x1, y1 = payload.bbox
    # normalized → source pixels; pad so the tag (which sits OUTSIDE the symbol
    # bbox on a P&ID) is inside the crop.
    px0, py0, px1, py1 = x0 * w, y0 * h, x1 * w, y1 * h
    bw, bh = (px1 - px0), (py1 - py0)
    pad_x, pad_y = bw * payload.pad_frac, bh * payload.pad_frac
    cx0 = max(0, int(px0 - pad_x)); cy0 = max(0, int(py0 - pad_y))
    cx1 = min(w, int(px1 + pad_x)); cy1 = min(h, int(py1 + pad_y))
    if cx1 <= cx0 or cy1 <= cy0:
        raise HTTPException(status_code=400, detail="degenerate bbox after padding")

    buf = _io.BytesIO()
    im.crop((cx0, cy0, cx1, cy1)).save(buf, format="PNG")
    crop_b64 = _b64.standard_b64encode(buf.getvalue()).decode("utf-8")

    try:
        text = _vision_read_tag(crop_b64)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"vision read failed: {type(e).__name__}: {e}")

    cands = _tag_candidates(text or "")
    best = cands[0] if cands else (text or "")
    return OcrBboxResponse(
        text=best,
        found=bool(best),
        candidates=cands,
        raw=text or "",
    )
