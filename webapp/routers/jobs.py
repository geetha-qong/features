"""Job routes: upload, detail, status poll, download."""
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.config import JOB_OUTPUT_DIR, UPLOAD_DIR
from webapp.database import SessionLocal, get_db
from webapp.pipeline_runner import run_pipeline_for_job

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def _run_in_thread(job_id: int, pdf_path: str, pid_no_override: str, include_control_valves: bool = True):
    """Run pipeline in a separate thread with its own DB session."""
    db = SessionLocal()
    try:
        run_pipeline_for_job(job_id, pdf_path, pid_no_override, db, include_control_valves)
    finally:
        db.close()


@router.post("/upload")
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    pid_no: str = Form(""),
    include_control_valves: str = Form("off"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    stored_name = f"{uuid.uuid4()}.pdf"
    dest = UPLOAD_DIR / stored_name
    with dest.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    job = models.Job(
        user_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_name,
        pid_no=pid_no.strip() or "UNKNOWN",
        status="pending",
        include_control_valves=(include_control_valves == "on"),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Copy PDF to job output dir so pipeline can reference it
    job_dir = JOB_OUTPUT_DIR / str(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)
    job_pdf = str(job_dir / "input.pdf")
    shutil.copy2(str(dest), job_pdf)

    t = threading.Thread(
        target=_run_in_thread,
        args=(job.id, job_pdf, pid_no.strip(), job.include_control_valves),
        daemon=True,
    )
    t.start()

    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(
    job_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or job.user_id != current_user.id:
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
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({"status": job.status, "valve_count": job.valve_count, "error_msg": job.error_msg})


@router.get("/jobs/{job_id}/download")
async def download_csv(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or job.user_id != current_user.id:
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


@router.post("/jobs/{job_id}/rerun")
async def rerun_job(
    job_id: int,
    include_control_valves: str = Form("off"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Job is already running")

    job_pdf = str(JOB_OUTPUT_DIR / str(job_id) / "input.pdf")
    if not Path(job_pdf).exists():
        raise HTTPException(status_code=404, detail="Original PDF not found — cannot re-run")

    # Clear previous results
    db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).delete()
    job.status = "pending"
    job.valve_count = 0
    job.error_msg = None
    job.output_csv_path = None
    job.processing_time = None
    job.processing_log = None
    job.completed_at = None
    job.include_control_valves = (include_control_valves == "on")
    db.commit()

    t = threading.Thread(
        target=_run_in_thread,
        args=(job.id, job_pdf, job.pid_no, job.include_control_valves),
        daemon=True,
    )
    t.start()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)
