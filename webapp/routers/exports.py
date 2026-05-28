"""POST /api/v1/jobs/{job_id}/export/{deliverable_type}/{file_format}

Generates and returns one customer deliverable for one job.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from webapp.database import get_db
from webapp.deliverables.job_loader import (
    JobCanonicalNotFound,
    load_canonical_for_job,
)
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
        404: {"description": "Job or canonical.json not found"},
    },
)
def export_deliverable(
    job_id: int,
    deliverable_type: str,
    file_format: str,
    db: Session = Depends(get_db),
) -> Response:
    job: Optional[Job] = db.get(Job, job_id)
    if job is None or not job.output_csv_path:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")

    try:
        canonical = load_canonical_for_job(job.output_csv_path)
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
