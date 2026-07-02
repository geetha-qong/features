"""POST /api/v1/jobs/{job_id}/export/{deliverable_type}/{file_format}

Generates and returns one customer deliverable for one job.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.deliverables.job_loader import JobCanonicalNotFound
from webapp.deliverables.overrides import load_canonical_with_overrides
from webapp.deliverables.registry import REGISTRY, UnknownGenerator
from webapp.deliverables.storage import store_export
from webapp.deliverables.template_loader import TemplateLoader
from webapp.models import Job

router = APIRouter(prefix="/api/v1/jobs", tags=["exports"])

_loader = TemplateLoader()


CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.post(
    "/{job_id}/export/{deliverable_type}/{file_format}",
    responses={
        200: {"description": "Deliverable bytes"},
        400: {"description": "Unknown deliverable type or format"},
        404: {"description": "Job or canonical.json not found / not owned by caller"},
    },
)
def export_deliverable(
    job_id: int,
    deliverable_type: str,
    file_format: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> Response:
    job: Optional[Job] = db.get(Job, job_id)
    if job is None or not job.output_csv_path:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    # IDOR guard: jobs are scoped per-user; only the owner or a super_admin can export.
    # Return 404 (not 403) to avoid leaking the existence of jobs owned by others.
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")

    try:
        # Merged view: exports include user edits saved via the
        # /api/v1/jobs/{id}/entities PATCH endpoint. Pre-edit raw canonical
        # is still available via webapp.deliverables.job_loader.load_canonical_for_job
        # for tooling that intentionally wants the unedited pipeline output.
        canonical = load_canonical_with_overrides(job.output_csv_path, job.id, db)
    except JobCanonicalNotFound:
        raise HTTPException(
            status_code=404,
            detail=f"canonical.json missing for job {job_id}",
        )

    try:
        generator_cls = REGISTRY.resolve(deliverable_type, file_format)
    except UnknownGenerator:
        raise HTTPException(
            status_code=400,
            detail=f"unknown deliverable: {deliverable_type}/{file_format}",
        )

    # Line List represents engineering pipelines, not just valve entities:
    # fold in recovered pipelines (Pass 4 / 4.5 orientation OCR) that have no
    # backing entity. Scoped to this request's line_list export only — the
    # synthesized pseudo-entities must never reach other deliverables.
    if deliverable_type == "line_list":
        try:
            import json as _json
            from pathlib import Path as _Path
            from webapp.deliverables.line_list import synthesize_recovered_line_entities
            _ld_path = _Path(job.output_csv_path).parent / "line_list_data.json"
            if _ld_path.exists():
                with _ld_path.open(encoding="utf-8") as _fh:
                    _ld = _json.load(_fh) or {}
                _recovered = synthesize_recovered_line_entities(canonical.entities, _ld)
                if _recovered:
                    canonical = canonical.model_copy(
                        update={"entities": list(canonical.entities) + _recovered}
                    )
        except Exception:
            pass  # non-fatal — fall back to canonical-only line list

    template = _loader.load_with_fallback(canonical.customer_template_slug)
    content = generator_cls().generate(canonical, template)

    store_export(job.output_csv_path, deliverable_type, file_format, content)

    media_type = CONTENT_TYPES.get(file_format, "application/octet-stream")
    filename = f"{deliverable_type}.{file_format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
