"""Sheet "Apply" state API (Studio finishing, design 2026-06-13 §1b).

Persists the reviewer's per-sheet "Apply · N" intent so it survives a reload.
Previously `appliedBySheet` in `Studio.tsx` was UI-only session state; these
endpoints back it with a `sheet_apply_state` DB row per (job, sheet).

Endpoints (mounted under prefix "/api/v1/jobs"):
  GET    /{job_id}/sheets/applied        map {sheet_number: applied_at_iso} for the job
  POST   /{job_id}/sheets/{n}/apply      upsert apply row (applied_at=now, applied_by=user)
  DELETE /{job_id}/sheets/{n}/apply      clear it (re-arm). 204.

Auth: same IDOR pattern as `edges.py` / `entities.py` — 404 (not 403) for
foreign jobs to avoid leaking other users' job IDs. Super_admin can read/write
any job.
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.datetime_utils import utc_iso

router = APIRouter(prefix="/api/v1/jobs", tags=["sheets"])


# --- pydantic models ---


class SheetApplyRow(BaseModel):
    job_id: int
    sheet_number: int
    applied_at: Optional[str] = None  # Z-suffixed ISO via utc_iso
    applied_by: int


class AppliedMapResponse(BaseModel):
    # {sheet_number: applied_at_iso}. Keys are ints in the model; JSON object
    # keys serialize as strings — the frontend reads them back as numbers.
    applied: Dict[int, str]


# --- helpers ---


def _load_job_or_404(
    job_id: int, db: Session, current_user: models.User
) -> models.Job:
    """Mirror of edges.py auth pattern. 404 (not 403) for foreign jobs.

    No `output_csv_path` requirement: a reviewer applies sheets during marking,
    before any deliverable CSV exists.
    """
    job: Optional[models.Job] = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


# --- endpoints ---


@router.get(
    "/{job_id}/sheets/applied",
    response_model=AppliedMapResponse,
    responses={
        200: {"description": "Map of sheet_number -> applied_at ISO for the job"},
        404: {"description": "Job not found / not owned by caller"},
    },
)
def get_applied(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> AppliedMapResponse:
    _load_job_or_404(job_id, db, current_user)
    rows = (
        db.query(models.SheetApplyState)
        .filter(models.SheetApplyState.job_id == job_id)
        .all()
    )
    applied = {r.sheet_number: utc_iso(r.applied_at) for r in rows}
    return AppliedMapResponse(applied=applied)


@router.post(
    "/{job_id}/sheets/{n}/apply",
    response_model=SheetApplyRow,
    responses={
        200: {"description": "Apply state upserted"},
        404: {"description": "Job not found / not owned by caller"},
    },
)
def apply_sheet(
    job_id: int,
    n: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> SheetApplyRow:
    _load_job_or_404(job_id, db, current_user)

    row: Optional[models.SheetApplyState] = (
        db.query(models.SheetApplyState)
        .filter(
            models.SheetApplyState.job_id == job_id,
            models.SheetApplyState.sheet_number == n,
        )
        .first()
    )
    now = models._utcnow()
    if row is None:
        row = models.SheetApplyState(
            job_id=job_id,
            sheet_number=n,
            applied_at=now,
            applied_by=current_user.id,
        )
        db.add(row)
    else:
        # Re-apply: refresh who/when.
        row.applied_at = now
        row.applied_by = current_user.id
    db.commit()
    db.refresh(row)
    return SheetApplyRow(
        job_id=row.job_id,
        sheet_number=row.sheet_number,
        applied_at=utc_iso(row.applied_at),
        applied_by=row.applied_by,
    )


@router.delete(
    "/{job_id}/sheets/{n}/apply",
    status_code=204,
    # No `responses={204: ...}` — newer FastAPI asserts no body is allowed for
    # 204 at route-registration time when a response is declared.
    responses={
        404: {"description": "Job not found / not owned by caller"},
    },
)
def clear_sheet(
    job_id: int,
    n: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Response:
    _load_job_or_404(job_id, db, current_user)

    row: Optional[models.SheetApplyState] = (
        db.query(models.SheetApplyState)
        .filter(
            models.SheetApplyState.job_id == job_id,
            models.SheetApplyState.sheet_number == n,
        )
        .first()
    )
    # Idempotent re-arm: clearing an un-applied sheet is a no-op 204, not a 404.
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204)
