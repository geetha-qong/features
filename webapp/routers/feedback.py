"""Feedback route: POST /jobs/{id}/feedback."""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db

router = APIRouter()


@router.post("/jobs/{job_id}/feedback")
async def submit_feedback(
    job_id: int,
    notes: str = Form(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    fb = models.Feedback(job_id=job_id, user_id=current_user.id, notes=notes.strip())
    db.add(fb)
    db.commit()
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)
