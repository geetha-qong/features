"""Dashboard route: /dashboard — job list for current user."""
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
    jobs = (
        db.query(models.Job)
        .filter(models.Job.user_id == current_user.id)
        .order_by(models.Job.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": current_user, "jobs": jobs},
    )
