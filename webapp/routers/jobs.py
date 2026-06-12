"""Job routes: upload, detail, status poll, download."""
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.config import JOB_OUTPUT_DIR, UPLOAD_DIR, get_job_dir, get_user_upload_dir
from webapp.database import SessionLocal, get_db
from webapp.queue import get_cpu_queue
from webapp.watchdog import STALE_HEARTBEAT_SECONDS

router = APIRouter()

# Legacy time-based stale hint (used only as a fallback when there's no
# JobRun row, e.g. for pre-observability jobs). The heartbeat watchdog handles
# new runs.
STALE_HINT_MINUTES = 60

# RQ job timeout — generous to fit a 12-page P&ID (~30 min) plus headroom.
RQ_JOB_TIMEOUT_SECONDS = 60 * 90


def _can_access_job(job, user) -> bool:
    """Owner always; super_admin and annotator can access any job."""
    return job.user_id == user.id or user.role in ("super_admin", "annotator")


def _enqueue_pipeline(job_id: int, pdf_path: str, pid_no_override: str,
                      include_control_valves: bool, original_filename: str) -> None:
    """Push pipeline work onto the cpu RQ queue. Runs on cpu-worker container."""
    get_cpu_queue().enqueue(
        "webapp.pipeline_runner.run_pipeline_for_job_rq",
        kwargs={
            "job_id": job_id,
            "pdf_path": pdf_path,
            "pid_no_override": pid_no_override,
            "include_control_valves": include_control_valves,
            "original_filename": original_filename,
        },
        job_timeout=RQ_JOB_TIMEOUT_SECONDS,
    )


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

        _enqueue_pipeline(
            job_id=job.id,
            pdf_path=job_pdf,
            pid_no_override=pid_no_override,
            include_control_valves=include_cv,
            original_filename=file.filename,
        )
        last_job_id = job.id

    # Single upload → go to job detail; multi → go to dashboard
    if last_job_id and len(files) == 1:
        return RedirectResponse(url=f"/jobs/{last_job_id}", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)


# Phase 4 cutover: the legacy Jinja GET /jobs/{job_id} HTML route has been
# removed. The React SPA's /jobs/:jobId (webapp/frontend/src/routes/JobDetail
# .tsx → Studio) takes over at the same URL via the catch-all SPA mount.
# The API endpoints below (/jobs/{id}/status, /pdf, /download, /tiles, etc.)
# are untouched and continue to serve all existing customers + the SPA.


@router.get("/jobs/{job_id}/status")
async def job_status(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")

    is_stale = False
    elapsed_minutes = None
    stale_seconds = None
    current_stage = None
    if job.status == "processing" and job.created_at:
        created = job.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - created
        elapsed_minutes = int(elapsed.total_seconds() // 60)

        # Prefer heartbeat-driven staleness when a JobRun row exists.
        latest_run = (
            db.query(models.JobRun)
            .filter(models.JobRun.job_id == job_id)
            .order_by(models.JobRun.attempt_num.desc())
            .first()
        )
        if latest_run and latest_run.last_heartbeat_at:
            current_stage = latest_run.current_stage
            hb = latest_run.last_heartbeat_at
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            stale_seconds = int((datetime.now(timezone.utc) - hb).total_seconds())
            is_stale = stale_seconds > STALE_HEARTBEAT_SECONDS
        else:
            # Pre-observability fallback: time-based.
            is_stale = elapsed_minutes >= STALE_HINT_MINUTES

    return JSONResponse({
        "status": job.status,
        "valve_count": job.valve_count,
        "error_msg": job.error_msg,
        "is_stale": is_stale,
        "elapsed_minutes": elapsed_minutes,
        "stale_seconds": stale_seconds,
        "current_stage": current_stage,
    })


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
    from starlette.responses import Response
    with open(str(pdf_path), "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{job.original_filename}"'},
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


@router.get("/jobs/{job_id}/annotated-pdf")
async def download_annotated_pdf(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.output_annotated_pdf_path:
        raise HTTPException(status_code=400, detail="Annotated PDF not available")
    pdf_path = Path(job.output_annotated_pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Annotated PDF file missing")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=f"annotated_{job.pid_no}.pdf",
    )


# CORS for the tile endpoint — Label Studio loads tiles cross-origin from
# ls-{env}.qongsystems.com → dev/qa.qongsystems.com and draws on them via
# canvas (bounding-box tools), which requires CORS-clean image sources.
# Tile content is non-sensitive (PID drawings), no auth state in headers,
# so `*` is the right allow-origin. NOTE: this router's tile endpoint is the
# one that actually fires (webapp.main also has a `serve_tile` but it's
# registered AFTER this router so it's shadowed — see FEATURES TBD).
_TILE_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Max-Age": "86400",
    # `Vary: Origin` tells caches (CF, browser) that the response varies by
    # the Origin request header — so subsequent requests with different
    # Origins get fetched separately rather than reusing a CORS-less cached
    # response. Critical: without this, the first non-CORS request locks in
    # a CORS-less response for all subsequent requesters until TTL expires.
    "Vary": "Origin",
    # Short cache TTL so a future no-CORS slip (e.g. another env hitting the
    # tile during bootstrap) doesn't lock CF for 4 hours.
    "Cache-Control": "public, max-age=300",
}


@router.options("/jobs/{job_id}/tiles/{filename}", include_in_schema=False)
async def serve_tile_preflight(job_id: int, filename: str):  # noqa: ARG001
    from fastapi.responses import JSONResponse
    return JSONResponse({}, headers=_TILE_CORS_HEADERS)


@router.get("/jobs/{job_id}/tiles/{filename}")
async def serve_tile(
    job_id: int,
    filename: str,
    db: Session = Depends(get_db),
):
    """Serve tile PNGs for Label Studio annotation — no auth (LS accesses directly).

    Returns CORS headers so LS at ls-dev.qongsystems.com can use the image
    in its canvas-based annotation tools (cross-origin, allow-origin *).
    """
    if not filename.endswith(".png"):
        raise HTTPException(status_code=400, detail="Only PNG tiles served here")
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    tile_path = get_job_dir(job) / "tmp" / filename
    if not tile_path.exists():
        raise HTTPException(status_code=404, detail="Tile not found")
    # Set headers post-construction — FileResponse's `headers=` kwarg
    # silently drops custom keys for image/* media types in our Starlette.
    resp = FileResponse(str(tile_path), media_type="image/png")
    for k, v in _TILE_CORS_HEADERS.items():
        resp.headers[k] = v
    return resp


@router.options("/jobs/{job_id}/page/{page_index}/full", include_in_schema=False)
async def serve_page_full_preflight(job_id: int, page_index: int):  # noqa: ARG001
    """CORS preflight for the full-page render endpoint.

    Mirrors `serve_tile_preflight` — the Qong Studio canvas may load this
    image cross-origin (same browser as the tile endpoint), so we ship the
    same CORS allowance.
    """
    return JSONResponse({}, headers=_TILE_CORS_HEADERS)


@router.get("/jobs/{job_id}/page/{page_index}/full")
async def serve_page_full(
    job_id: int,
    page_index: int,
    w: int | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve the full-page render `page_{page_index}_full.png`.

    Auth via `get_current_user`; foreign jobs return 404 (not 403) to avoid
    revealing job existence (same IDOR pattern as entities.py / the other
    job endpoints in this file). The PNG is written by `pdf_to_tiles.py`
    at `<job_dir>/tmp/page_{page_idx}_full.png` (see pdf_to_tiles.py:44).

    **High-DPI on demand (FEATURES #41):** the studio canvas measures the
    user's viewport at mount time and requests `?w=<target_px>`. When the
    cached 4x render is narrower than the request, we re-render the PDF
    page at exactly the requested width using PyMuPDF (no upscaling — true
    pixels straight from the vector source) and cache under
    `page_{idx}_full_w{w}.png`. Subsequent requests for the same width
    hit the cache. Bounded to 6000 px to cap render cost. Below or equal
    the 4x baseline → falls through to the original file unchanged so we
    don't waste cycles on small displays.

    CORS headers mirror `serve_tile` so Qong Studio's canvas can use the
    image cross-origin. Headers are set post-construction because
    Starlette's `FileResponse(headers=…)` silently drops custom keys for
    `image/*` media types.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    tmp_dir = get_job_dir(job) / "tmp"
    full_path = tmp_dir / f"page_{page_index}_full.png"
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="page render not found")

    target = full_path
    # Hi-DPI on-demand render. Cap at 6000 px (typical 5K display × 1.5
    # oversample). Only re-render when the request is *larger* than what we
    # have on disk — a tiny query value is just ignored.
    if w is not None and 100 < w <= 6000:
        hi_path = tmp_dir / f"page_{page_index}_full_w{w}.png"
        if not hi_path.exists():
            try:
                import fitz  # PyMuPDF — already a hard dep via pdf_to_tiles.py
                from PIL import Image
                # First measure what we already have so we don't waste work
                # when the cached 4x render is already wider than the ask.
                with Image.open(str(full_path)) as cached:
                    cached_w = cached.size[0]
                if cached_w < w:
                    pdf_path = get_job_dir(job) / "input.pdf"
                    if pdf_path.exists():
                        doc = fitz.open(str(pdf_path))
                        if 0 <= page_index < len(doc):
                            page = doc[page_index]
                            # Choose zoom that hits exactly the requested
                            # pixel width. PyMuPDF zoom is a scalar against
                            # the page's native point dimensions.
                            page_w_pt = page.rect.width or 1
                            zoom = w / page_w_pt
                            # Sanity cap — paranoia against a tiny page +
                            # huge w combining into a multi-GB pixmap.
                            zoom = min(zoom, 12.0)
                            mat = fitz.Matrix(zoom, zoom)
                            pix = page.get_pixmap(matrix=mat)
                            pix.save(str(hi_path))
                        doc.close()
            except Exception:
                # Any failure (missing input.pdf, OOM, etc.) → silently
                # fall back to the cached 4x render. Never break the page
                # over a clarity-bonus path.
                hi_path = full_path
        if hi_path.exists():
            target = hi_path

    resp = FileResponse(str(target), media_type="image/png")
    for k, v in _TILE_CORS_HEADERS.items():
        resp.headers[k] = v
    # 7-day immutable cache — different `w` values are different URLs so a
    # browser refresh after a resize naturally invalidates.
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    return resp


@router.get("/jobs/{job_id}/download-inst-datasheets")
async def download_inst_datasheets(
    job_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.output_inst_datasheet_path:
        raise HTTPException(status_code=400, detail="Instrument datasheets not available")
    zip_path = Path(job.output_inst_datasheet_path)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Datasheets file missing")
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"instrument_datasheets_{job.pid_no}.zip",
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
    job.output_inst_datasheet_path = None
    job.output_annotated_pdf_path = None
    job.processing_time = None
    job.processing_log = None
    job.completed_at = None
    job.include_control_valves = (include_control_valves == "on")
    db.commit()

    _enqueue_pipeline(
        job_id=job.id,
        pdf_path=job_pdf,
        pid_no_override=job.pid_no,
        include_control_valves=job.include_control_valves,
        original_filename=job.original_filename,
    )

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)
