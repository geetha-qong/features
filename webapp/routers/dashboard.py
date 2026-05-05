"""Dashboard route: /dashboard — job list for current user (all jobs for super_admin/annotator)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.jinja import templates

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role in ("super_admin", "annotator"):
        jobs_q = (
            db.query(models.Job, models.User.username)
            .join(models.User, models.Job.user_id == models.User.id)
            .order_by(models.Job.created_at.desc())
            .all()
        )
        # Attach username onto each job object for template use
        jobs = []
        for job, username in jobs_q:
            job.owner_username = username
            jobs.append(job)
    else:
        jobs = (
            db.query(models.Job)
            .filter(models.Job.user_id == current_user.id)
            .order_by(models.Job.created_at.desc())
            .all()
        )
        for job in jobs:
            job.owner_username = current_user.username

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": current_user, "jobs": jobs},
    )
