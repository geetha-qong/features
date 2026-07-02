"""Annotator landing page — /annotate.

Annotator-role surface (NOT super_admin). Lists jobs synced to Label Studio
and links to their LS project. Stays as Jinja during Phase 4 cutover — the
React SPA covers only customer-facing + super_admin surfaces; annotators
continue to use the legacy template.

Extracted from webapp/routers/admin.py during Phase 4 so that deleting
admin.py's legacy super_admin routes does not take this annotator surface
down.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from webapp import label_studio_client as ls
from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.jinja import templates

router = APIRouter()


@router.get("/annotate", response_class=HTMLResponse)
async def annotate_page(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("annotator", "super_admin"):
        raise HTTPException(status_code=403, detail="Annotator access required")
    synced_jobs = (
        db.query(models.Job)
        .filter(models.Job.ls_synced == True)  # noqa: E712
        .order_by(models.Job.created_at.desc())
        .all()
    )
    job_stats = []
    for job in synced_jobs:
        stats = ls.get_project_stats(job.ls_project_id) if job.ls_project_id else {}
        job_stats.append({"job": job, "stats": stats})

    return templates.TemplateResponse(
        "annotate.html",
        {
            "request": request,
            "user": current_user,
            "job_stats": job_stats,
            "ls_url": ls.LS_EXTERNAL_URL,
            "ls_configured": ls.is_configured(),
        },
    )
