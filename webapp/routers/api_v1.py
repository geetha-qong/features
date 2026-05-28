"""Programmatic REST API v1.

Auth: Bearer qk_... (API key) OR cookie JWT — both accepted on every endpoint.
"""
import json
import os
import shutil
import uuid
from datetime import datetime

_GPU_CALLBACK_SECRET = os.environ.get("GPU_CALLBACK_SECRET", "")

import fitz  # PyMuPDF — page count for credit pre-flight
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from webapp import credits as credits_module
from webapp import models
from webapp.auth import get_user_from_api_key, get_current_user
from webapp.config import JOB_OUTPUT_DIR, get_job_dir, get_user_upload_dir
from webapp.database import get_db
from webapp.queue import get_cpu_queue
from webapp.routers.jobs import RQ_JOB_TIMEOUT_SECONDS

router = APIRouter(prefix="/api/v1", tags=["api_v1"])


# ── Auth dependency ────────────────────────────────────────────────────────────

async def _get_api_user(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    """Accept Bearer API key or cookie JWT; raise 401 if neither works."""
    user = await get_user_from_api_key(request, db)
    if user:
        return user
    # Fall back to cookie JWT; convert browser redirect (303) to API-friendly 401
    try:
        return get_current_user(request, db)
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: provide a valid API key (Authorization: Bearer qk_...) or login cookie",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _credits_consumed(db: Session, job_id: int) -> int:
    """Sum of negative credit deltas recorded for this job."""
    rows = (
        db.query(models.CreditTransaction)
        .filter(
            models.CreditTransaction.job_id == job_id,
            models.CreditTransaction.delta < 0,
        )
        .all()
    )
    return sum(abs(r.delta) for r in rows)


# ── POST /api/v1/jobs ──────────────────────────────────────────────────────────

@router.post("/jobs", status_code=202)
async def api_create_job(
    request: Request,
    file: UploadFile = File(..., description="P&ID PDF file"),
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Upload a single P&ID PDF and queue it for processing.

    Returns 202 with job_id and a status_url to poll.
    Deducts credits equal to the page count; refunds on failure.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Store to uploads/{user_id}/{uuid}.pdf
    stored_name = f"{uuid.uuid4()}.pdf"
    user_upload_dir = get_user_upload_dir(current_user.id)
    dest = user_upload_dir / stored_name
    with dest.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # Pre-flight: count pages → required credits
    try:
        doc = fitz.open(str(dest))
        page_count = len(doc)
        doc.close()
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Could not parse PDF")

    if page_count == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="PDF has no pages")

    if not credits_module.check_balance(current_user, page_count):
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credits: need {page_count}, have {credits_module.get_balance(current_user)}. Visit /account/billing."
        )

    # Create job record
    job = models.Job(
        user_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_name,
        pid_no="UNKNOWN",
        status="pending",
        include_control_valves=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Deduct credits (refunded by pipeline_runner on failure)
    credits_module.deduct(
        current_user, page_count, reason="job_consumed", db=db, job_id=job.id
    )

    # Copy PDF to per-job directory and enqueue pipeline on cpu-worker
    job_dir = JOB_OUTPUT_DIR / str(current_user.id) / str(job.id)
    job_dir.mkdir(parents=True, exist_ok=True)
    job_pdf = str(job_dir / "input.pdf")
    shutil.copy2(str(dest), job_pdf)

    get_cpu_queue().enqueue(
        "webapp.pipeline_runner.run_pipeline_for_job_rq",
        kwargs={
            "job_id": job.id,
            "pdf_path": job_pdf,
            "pid_no_override": "",
            "include_control_valves": True,
            "original_filename": file.filename,
        },
        job_timeout=RQ_JOB_TIMEOUT_SECONDS,
    )

    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.id,
            "status": "pending",
            "status_url": f"{base}/api/v1/jobs/{job.id}",
            "credits_deducted": page_count,
        },
    )


# ── GET /api/v1/jobs ───────────────────────────────────────────────────────────

@router.get("/jobs")
async def api_list_jobs(
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    """List jobs owned by the current user (or all jobs for super_admin), newest first.

    Used by the QONG Studio Dashboard to render the projects tile grid.
    Shape is intentionally close to what the UI needs so the frontend only
    has to compute cosmetic fields (relative time, avatar colors).
    """
    q = (
        db.query(models.Job, models.User.username)
        .outerjoin(models.User, models.Job.user_id == models.User.id)
    )
    if current_user.role != "super_admin":
        q = q.filter(models.Job.user_id == current_user.id)
    rows = q.order_by(models.Job.created_at.desc()).limit(limit).all()

    return {
        "jobs": [
            {
                "id": j.id,
                "name": j.original_filename or f"Job {j.id}",
                "pid_no": j.pid_no or "UNKNOWN",
                "status": j.status,
                "valve_count": j.valve_count or 0,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "owner_username": owner_username,
            }
            for j, owner_username in rows
        ]
    }


# ── GET /api/v1/jobs/{id}/sheets ───────────────────────────────────────────────

@router.get("/jobs/{job_id}/sheets")
async def api_job_sheets(
    job_id: int,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """List tile filenames for the SPA studio sheet rail.

    Each entry maps directly to /jobs/{job_id}/tiles/{filename} which the
    Label Studio tile-serving endpoint already exposes. The SPA renders
    these as <img> in the sheet rail (replacing the prototype SheetGlyph).
    """
    from webapp.config import get_job_dir
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    job_dir = get_job_dir(job)
    tmp_dir = job_dir / "tmp"
    tiles = sorted(tmp_dir.glob("tile_p*_r*_c*.png")) if tmp_dir.exists() else []

    sheets = []
    for idx, t in enumerate(tiles):
        # Extract page/row/col from tile_p{page}_r{row}_c{col}.png
        stem = t.stem  # tile_p0_r1_c2
        sheets.append({
            "id": idx + 1,
            "filename": t.name,
            "url": f"/jobs/{job_id}/tiles/{t.name}",
            "label": stem.replace("tile_", "Sheet "),
        })

    return {
        "job_id": job_id,
        "pid_no": job.pid_no,
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


# ── GET /api/v1/jobs/{id}/detections ───────────────────────────────────────────

@router.get("/jobs/{job_id}/detections")
async def api_job_detections(
    job_id: int,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Return parsed GPU detections + ValveRow CSV data for canvas overlay.

    `detections` (may be null/empty if the GPU worker hasn't called back
    yet) contains the bounding-box positions to render on the PDF tile.
    `valves` is the structured CSV the customer downloads (no coords).

    The SPA studio canvas uses `detections` to draw overlay rectangles when
    available, and shows a fallback list from `valves` when not.
    """
    import json as _json
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    detections = []
    if job.gpu_detections:
        try:
            parsed = _json.loads(job.gpu_detections)
            if isinstance(parsed, list):
                detections = parsed
        except (ValueError, TypeError):
            detections = []

    valve_rows = db.query(models.ValveRow).filter(models.ValveRow.job_id == job_id).all()
    valves = [
        {
            "id": v.id,
            "pid_no": v.pid_no,
            "category": v.category,
            "size": v.size,
            "serial_no": v.serial_no,
            "fluid_code": v.fluid_code,
            "piping_class": v.piping_class,
            "qty": v.qty,
            "line": v.line,
            "motor_actuator": v.motor_actuator,
            "pneumatic_actuator": v.pneumatic_actuator,
            "solenoid": v.solenoid,
        }
        for v in valve_rows
    ]

    return {
        "job_id": job_id,
        "status": job.status,
        "valve_count": job.valve_count or 0,
        "detections": detections,
        "detection_count": len(detections),
        "valves": valves,
    }


# ── GET /api/v1/jobs/{id} ──────────────────────────────────────────────────────

@router.get("/jobs/{job_id}")
async def api_job_status(
    job_id: int,
    request: Request,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Poll job status. Returns status, valve count, credits consumed, and download URLs."""
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    base = str(request.base_url).rstrip("/")
    csv_url = f"{base}/jobs/{job.id}/download" if job.output_csv_path else None
    inst_url = f"{base}/jobs/{job.id}/download-inst-index" if job.output_inst_index_path else None

    return {
        "job_id": job.id,
        "status": job.status,
        "pid_no": job.pid_no,
        "original_filename": job.original_filename,
        "valve_count": job.valve_count or 0,
        "credits_consumed": _credits_consumed(db, job.id),
        "error_msg": job.error_msg,
        "csv_url": csv_url,
        "inst_index_url": inst_url,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


# ── GET /api/v1/account ────────────────────────────────────────────────────────

@router.get("/account")
async def api_account(
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Return current user's credits, tier, and role.

    `role` is consumed by the SPA to gate /admin/* routes — must be the
    authoritative server-side value, never derived from anything client-side.
    """
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "credits_remaining": credits_module.get_balance(current_user),
        "tier": current_user.tier or "trial",
        "role": current_user.role or "user",
    }


# ── POST /api/v1/jobs/{id}/gpu-result ─────────────────────────────────────────

@router.post("/jobs/{job_id}/gpu-result")
async def api_gpu_result(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive YOLO+OCR detection results from the Windows GPU worker.

    Auth: GPU_CALLBACK_SECRET (shared secret, set via .env) OR normal Bearer API key.
    Body: {"job_id": int, "detections": [...]}
    Stores detections on the job row; pushes predictions to Label Studio if configured.
    Returns: {"stored": N, "ls_predictions_posted": N}
    """
    # Accept GPU_CALLBACK_SECRET as a trusted alternative to per-user API keys.
    # (API keys are stored hashed — we can't reconstruct them for the worker payload.)
    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    trusted = bool(_GPU_CALLBACK_SECRET and bearer == _GPU_CALLBACK_SECRET)

    current_user = None
    if not trusted:
        current_user = await get_user_from_api_key(request, db)
        if not current_user:
            try:
                current_user = get_current_user(request, db)
            except HTTPException:
                raise HTTPException(
                    status_code=401,
                    detail="Provide GPU_CALLBACK_SECRET or a valid API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    body = await request.json()
    detections = body.get("detections", [])

    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user and job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    job.gpu_detections = json.dumps(detections)
    db.commit()

    ls_pushed = 0
    if job.ls_project_id:
        from webapp import label_studio_client as ls
        ls_pushed = ls.push_predictions(job.ls_project_id, detections, get_job_dir(job))

    return JSONResponse(
        status_code=200,
        content={"stored": len(detections), "ls_predictions_posted": ls_pushed},
    )
