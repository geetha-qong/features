"""Job routes: upload, detail, status poll, download."""
import shutil
import threading
import uuid
from pathlib import Path

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.config import JOB_OUTPUT_DIR, UPLOAD_DIR, get_job_dir, get_user_upload_dir
from webapp.database import SessionLocal, get_db
from webapp.jinja import templates
from webapp.pipeline_runner import run_pipeline_for_job

router = APIRouter()


def _can_access_job(job, user) -> bool:
    """Owner always; super_admin can access any job."""
    return job.user_id == user.id or user.role == "super_admin"


def _run_in_thread(job_id: int, pdf_path: str, pid_no_override: str, include_control_valves: bool = True, original_filename: str = ""):
    """Run pipeline in a separate thread with its own DB session."""
    db = SessionLocal()
    try:
        run_pipeline_for_job(job_id, pdf_path, pid_no_override, db, include_control_valves, original_filename=original_filename)
    finally:
        db.close()


@router.post("/upload")
async def upload_pdf(
    request: Request,
    files: List[UploadFile] = File(...),
    pid_no: str = Form(""),
    include_control_valves: str = Form("off"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    include_cv = (include_control_valves == "on")
    # P&ID number override only makes sense for a single file
    pid_no_override = pid_no.strip() if len(files) == 1 else ""

    last_job_id = None
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{file.filename}: only PDF files are accepted")

        stored_name = f"{uuid.uuid4()}.pdf"
        user_upload_dir = get_user_upload_dir(current_user.id)
        dest = user_upload_dir / stored_name
        with dest.open("wb") as buf:
            shutil.copyfileobj(file.file, buf)

        job = models.Job(
            user_id=current_user.id,
            original_filename=file.filename,
            stored_filename=stored_name,
            pid_no=pid_no_override or "UNKNOWN",
            status="pending",
            include_control_valves=include_cv,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Per-user job folder: job_outputs/{user_id}/{job_id}/
        job_dir = JOB_OUTPUT_DIR / str(current_user.id) / str(job.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        job_pdf = str(job_dir / "input.pdf")
        shutil.copy2(str(dest), job_pdf)

        t = threading.Thread(
            target=_run_in_thread,
            args=(job.id, job_pdf, pid_no_override, include_cv),
            kwargs={"original_filename": file.filename},
            daemon=True,
        )
        t.start()
        last_job_id = job.id

    # Single upload → go to job detail; multi → go to dashboard
    if last_job_id and len(files) == 1:
        return RedirectResponse(url=f"/jobs/{last_job_id}", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    job_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")

    valve_rows = (
        db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).all()
        if job.status == "done"
        else []
    )
    feedbacks = (
        db.query(models.Feedback)
        .filter(models.Feedback.job_id == job_id)
        .order_by(models.Feedback.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "job_detail.html",
        {
            "request": request,
            "user": current_user,
            "job": job,
            "valve_rows": valve_rows,
            "feedbacks": feedbacks,
        },
    )


@router.get("/jobs/{job_id}/status")
async def job_status(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({"status": job.status, "valve_count": job.valve_count, "error_msg": job.error_msg})


@router.get("/jobs/{job_id}/pdf")
async def view_pdf(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    pdf_path = get_job_dir(job) / "input.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=job.original_filename,
    )


@router.get("/jobs/{job_id}/download")
async def download_csv(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.output_csv_path:
        raise HTTPException(status_code=400, detail="Output not ready")
    csv_path = Path(job.output_csv_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(
        str(csv_path),
        media_type="text/csv",
        filename=f"valve_list_{job.pid_no}.csv",
    )


@router.get("/jobs/{job_id}/download-inst-index")
async def download_inst_index(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.output_inst_index_path:
        raise HTTPException(status_code=400, detail="Instrument index not available")
    csv_path = Path(job.output_inst_index_path)
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Instrument index file missing")
    return FileResponse(
        str(csv_path),
        media_type="text/csv",
        filename=f"instrumentation_index_{job.pid_no}.csv",
    )


@router.post("/jobs/{job_id}/rerun")
async def rerun_job(
    job_id: int,
    include_control_valves: str = Form("off"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Job is already running")

    job_pdf = str(get_job_dir(job) / "input.pdf")
    if not Path(job_pdf).exists():
        raise HTTPException(status_code=404, detail="Original PDF not found — cannot re-run")

    # Clear previous results
    db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).delete()
    job.status = "pending"
    job.valve_count = 0
    job.error_msg = None
    job.output_csv_path = None
    job.output_inst_index_path = None
    job.processing_time = None
    job.processing_log = None
    job.completed_at = None
    job.include_control_valves = (include_control_valves == "on")
    db.commit()

    t = threading.Thread(
        target=_run_in_thread,
        args=(job.id, job_pdf, job.pid_no, job.include_control_valves),
        kwargs={"original_filename": job.original_filename},
        daemon=True,
    )
    t.start()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)
