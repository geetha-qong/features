"""Programmatic REST API v1.

Auth: Bearer qk_... (API key) OR cookie JWT — both accepted on every endpoint.
"""
import json
import os
import secrets as _secrets
import shutil
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from webapp.datetime_utils import utc_iso

_GPU_CALLBACK_SECRET = os.environ.get("GPU_CALLBACK_SECRET", "")

import fitz  # PyMuPDF — page count for credit pre-flight
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp import credits as credits_module
from webapp import models
from webapp.auth import get_current_user, get_user_from_api_key, pwd_context
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

    # Reject content that doesn't start with the PDF magic header — PyMuPDF
    # is lenient and would otherwise treat HTML / spoofed-extension files as
    # blank 1-page PDFs, producing useless empty tiles + a "done" job with
    # zero valves. Reading the first 5 bytes is O(1).
    try:
        with dest.open("rb") as fh:
            header = fh.read(5)
    except OSError:
        header = b""
    if not header.startswith(b"%PDF-"):
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail="File is not a valid PDF (missing %PDF- header).",
        )

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
                "created_at": utc_iso(j.created_at),
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


def _yolo_class_to_canonical(label: Optional[str]) -> tuple:
    """Map a YOLO class string to ``(entity_class, sub_class_or_None)``.

    Returns ``(None, None)`` for labels that don't correspond to a canonical
    entity (direction arrows, unknown classes). Detection of those labels
    will not be paired with any entity.
    """
    if not label:
        return None, None
    if label.startswith("valve_"):
        return "valve", label[len("valve_"):].upper()
    if label.startswith("inst_") or label in {"interlock", "SIS-R"}:
        return "instrument", None
    # v1-9 used "Pump_Dwg_Pump" (underscore); v1-10 uses "Pump/Dwg Pump" — handle both
    if label in {"Motor", "Pump/Dwg Pump", "Pump_Dwg_Pump"}:
        return "equipment", None
    if label.startswith("arrow_") or label.startswith("connector_"):
        return None, None  # direction labels are not editable entities
    return None, None


def _normalize_detection_shape(detections: list) -> None:
    """Smooth over the two stored shapes for `gpu_detections`:

      - Legacy Windows GPU worker rows: ``bbox_tile``, ``yolo_class``,
        ``yolo_conf``, ``tile_page/row/col`` (no ``tile`` filename).
      - In-process YOLO inference rows (FEATURES #28, #30): ``bbox``,
        ``label``, ``confidence``, ``tile`` filename + ``tile_page/row/col``.

    The frontend ``PidCanvas`` only reads the second shape (``bbox``,
    ``label``, ``tile``). Without normalisation, legacy jobs have detections
    in the DB but zero overlay rendered on the canvas, which silently
    breaks D2 even after D1.5 attaches entity_id correctly.

    Mutates each dict in-place; never overwrites a value that's already set.
    """
    for det in detections:
        if "bbox" not in det and "bbox_tile" in det:
            det["bbox"] = det["bbox_tile"]
        if "label" not in det and "yolo_class" in det:
            det["label"] = det["yolo_class"]
        if "confidence" not in det and "yolo_conf" in det:
            det["confidence"] = det["yolo_conf"]
        if "tile" not in det:
            page = det.get("tile_page")
            row = det.get("tile_row")
            col = det.get("tile_col")
            if all(v is not None for v in (page, row, col)):
                det["tile"] = f"tile_p{page}_r{row}_c{col}.png"


def _attach_entity_ids(detections: list, entities: list) -> None:
    """Mutate each detection dict in-place, adding ``entity_id`` and
    ``entity_class``. See the docstring on ``api_job_detections`` for the
    three-step matching strategy.

    Each canonical entity is consumed at most once across the whole
    detection list (FIFO over the detection iteration order), so two
    detections of class ``valve_BV`` will resolve to two distinct entities
    of that class.
    """
    tag_to_ids: dict = {}
    for e in entities:
        if e.tag:
            tag_to_ids.setdefault(e.tag, []).append(
                (str(e.entity_id), e.entity_class)
            )
    consumed: set = set()

    def _pop_from_bucket(bucket: list) -> tuple:
        while bucket:
            eid, ecls = bucket.pop(0)
            if eid not in consumed:
                consumed.add(eid)
                return eid, ecls
        return None, None

    for det in detections:
        entity_id = None
        entity_class = None

        # Step 1+2: tag-equality matches. Two possible carriers of a tag on
        # the detection — `valve_tag` (legacy GPU worker output) or `label`
        # (when the label string happens to be tag-shaped, e.g. fixtures).
        for candidate_tag in (det.get("valve_tag"), det.get("tag"), det.get("label")):
            if candidate_tag and candidate_tag in tag_to_ids:
                entity_id, entity_class = _pop_from_bucket(tag_to_ids[candidate_tag])
                if entity_id:
                    break

        # Step 3: class compatibility — read the YOLO class from either
        # shape (new in-process inference: `label`; legacy worker: `yolo_class`).
        if entity_id is None:
            yolo_label = det.get("label") or det.get("yolo_class")
            cls, sub = _yolo_class_to_canonical(yolo_label)
            if cls:
                # Prefer sub_class-exact match; fall back to class-only.
                for e in entities:
                    eid = str(e.entity_id)
                    if eid in consumed or e.entity_class != cls:
                        continue
                    if sub and (e.sub_class or "").upper() != sub:
                        continue
                    entity_id = eid
                    entity_class = e.entity_class
                    consumed.add(eid)
                    break
                if entity_id is None and sub:
                    # Sub_class didn't match anything; try class-only.
                    for e in entities:
                        eid = str(e.entity_id)
                        if eid in consumed or e.entity_class != cls:
                            continue
                        entity_id = eid
                        entity_class = e.entity_class
                        consumed.add(eid)
                        break

        det["entity_id"] = entity_id
        if entity_class:
            det.setdefault("entity_class", entity_class)


@router.get("/jobs/{job_id}/detections")
async def api_job_detections(
    job_id: int,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Return parsed GPU detections + ValveRow CSV data for canvas overlay.

    `detections` (may be null/empty if the GPU worker hasn't called back
    yet) contains the bounding-box positions to render on the PDF tile.
    Each detection is enriched with `entity_id` (UUID string) when it can
    be paired with a canonical entity — this makes the canvas click-to-edit
    flow work (Spec A / FEATURES #26-27 / D1.5).

    Matching strategy, tried in order until one succeeds (FEATURES #31):

      1. **Tag-equality.** If the detection carries an OCR'd tag string
         (`valve_tag` or `tag` field — populated by the legacy Windows GPU
         worker), match exactly against `canonical_entity.tag`.
      2. **Label-as-tag.** If the detection's `label` happens to be a
         tag-shaped string (legacy / unit-test fixtures), match against
         `tag` as well.
      3. **Class compatibility (FIFO).** Map the YOLO class string
         (`label` from `webapp.inference` *or* `yolo_class` from the
         legacy worker) → `(entity_class, sub_class)`, then assign the
         first un-consumed canonical entity of that class. This is the
         dominant path now that the in-process YOLO inference module
         (FEATURES #28, model v1-10 FEATURES #30) emits class names not
         tags. Without spatial info on canonical entities (their bboxes
         are placeholder zeros today) the pairing is order-based, not
         spatially correct — but it unblocks DatasheetDrawer editing for
         the matched class. Spatial IoU matching is the v2 of D1.5,
         deferred until `pipeline_emitter` populates real bboxes.

    Detections that fail all three steps get `entity_id: null` and stay
    informational-only (cannot be edited via the override API).

    `valves` is the structured CSV the customer downloads (no coords).
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

    # Normalize legacy GPU-worker shape (bbox_tile, yolo_class, ...) onto the
    # in-process inference shape the frontend expects (bbox, label, tile).
    if detections:
        _normalize_detection_shape(detections)

    if detections and job.output_csv_path:
        try:
            from webapp.deliverables.job_loader import (
                JobCanonicalNotFound,
                load_canonical_for_job,
            )
            canonical = load_canonical_for_job(job.output_csv_path)
            _attach_entity_ids(detections, canonical.entities)
        except JobCanonicalNotFound:
            # canonical.json hasn't been emitted yet — leave detections as-is.
            for det in detections:
                det.setdefault("entity_id", None)
        except Exception:
            # Any parse/schema error: skip enrichment but don't break the canvas.
            for det in detections:
                det.setdefault("entity_id", None)

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
        "created_at": utc_iso(job.created_at),
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
        "timezone": current_user.timezone,  # IANA name or null → frontend uses Intl auto-detect
    }


# ── PATCH /api/v1/account/timezone ────────────────────────────────────────────

class TimezonePatch(BaseModel):
    timezone: Optional[str] = None  # IANA name, or null to clear (back to auto-detect)


@router.patch("/account/timezone")
async def api_account_set_timezone(
    payload: TimezonePatch,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Set or clear the user's preferred display timezone.

    Body `{ "timezone": "Asia/Kolkata" }` to set, or `{ "timezone": null }` to
    clear (frontend then falls back to Intl.DateTimeFormat browser detection).
    IANA names only — validated via zoneinfo.ZoneInfo. Invalid → 422.
    """
    tz = payload.timezone
    if tz is not None:
        # Validate against the IANA database. zoneinfo is in stdlib (3.9+).
        # tzdata is included via requirements-webapp.txt so legacy aliases
        # (e.g. "Asia/Calcutta" sent by some browsers) resolve correctly.
        # If a string still doesn't match, accept it only when it looks like
        # a plausible IANA name (region/city or "UTC") — the frontend is
        # using Intl.DateTimeFormat which produces well-formed names, and
        # we don't want a stale tzdb on the server to reject a valid value.
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            if tz == "UTC" or ("/" in tz and len(tz) < 64 and tz.replace("/", "").replace("_", "").replace("-", "").replace("+", "").isalnum()):
                pass  # accept; logged for ops awareness
            else:
                raise HTTPException(status_code=422, detail=f"Unknown IANA timezone: {tz!r}")

    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.timezone = tz
    db.commit()
    return {"timezone": user.timezone}


# ── GET /api/v1/account/transactions ─────────────────────────────────────────

@router.get("/account/transactions")
async def api_account_transactions(
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
    limit: int = 20,
):
    """Return the current user's recent credit transactions (newest first)."""
    rows = (
        db.query(models.CreditTransaction)
        .filter(models.CreditTransaction.user_id == current_user.id)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )
    return {
        "transactions": [
            {
                "id": r.id,
                "delta": r.delta,
                "balance_after": r.balance_after,
                "reason": r.reason,
                "job_id": r.job_id,
                "created_at": utc_iso(r.created_at),
            }
            for r in rows
        ]
    }


# ── /api/v1/account/api-keys (list, create, revoke) ──────────────────────────

@router.get("/account/api-keys")
async def api_account_list_api_keys(
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """List the current user's non-revoked API keys."""
    keys = (
        db.query(models.ApiKey)
        .filter(
            models.ApiKey.user_id == current_user.id,
            models.ApiKey.revoked_at.is_(None),
        )
        .order_by(models.ApiKey.created_at.desc())
        .all()
    )
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "created_at": utc_iso(k.created_at),
                "last_used_at": utc_iso(k.last_used_at),
            }
            for k in keys
        ]
    }


class CreateApiKeyBody(BaseModel):
    name: str = "Default"


@router.post("/account/api-keys", status_code=201)
async def api_account_create_api_key(
    body: CreateApiKeyBody,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    # SECURITY: the plaintext `key` is returned ONCE in this response body.
    # DB stores only the bcrypt hash + the 8-char prefix. SPA must reveal-and-
    # discard; do NOT log this value anywhere.
    name = (body.name or "").strip() or "Default"
    name = name[:64]

    random_part = _secrets.token_hex(16)  # 32 hex chars
    full_key = f"qk_{random_part}"
    prefix = full_key[:8]
    key_hash = pwd_context.hash(full_key)

    api_key = models.ApiKey(
        user_id=current_user.id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "key": full_key,
        "created_at": utc_iso(api_key.created_at),
    }


@router.delete("/account/api-keys/{key_id}", status_code=204)
async def api_account_revoke_api_key(
    key_id: int,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    api_key = (
        db.query(models.ApiKey)
        .filter(
            models.ApiKey.id == key_id,
            models.ApiKey.user_id == current_user.id,
        )
        .first()
    )
    if not api_key:
        raise HTTPException(status_code=404, detail="Key not found")
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    return None


# ── GET /api/v1/account/billing ──────────────────────────────────────────────

@router.get("/account/billing")
async def api_account_billing(
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    plans = (
        db.query(models.BillingPlan)
        .filter(models.BillingPlan.is_active == True)  # noqa: E712 — SQLAlchemy filter
        .order_by(models.BillingPlan.price_usd_cents)
        .all()
    )
    return {
        "balance": credits_module.get_balance(current_user),
        "tier": current_user.tier or "trial",
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "credits": p.credits,
                "price_usd_cents": p.price_usd_cents,
                "stripe_price_id": p.stripe_price_id,
            }
            for p in plans
        ],
    }


# ── POST /api/v1/feedback (anonymous allowed) ────────────────────────────────

class FeedbackBody(BaseModel):
    category: str
    subject: str
    message: str
    page_url: Optional[str] = None


@router.post("/feedback", status_code=201)
async def api_feedback_submit(
    body: FeedbackBody,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit user feedback. Anonymous submissions allowed (user_id NULL)."""
    # Try cookie → API key → anonymous, in that order.
    user_id: Optional[int] = None
    user = await get_user_from_api_key(request, db)
    if user is None:
        try:
            user = get_current_user(request, db)
        except HTTPException:
            user = None
    if user is not None:
        user_id = user.id

    category = body.category if body.category in ("bug", "feature", "pricing", "other") else "other"
    subject = (body.subject or "").strip()
    message = (body.message or "").strip()
    if not subject or not message:
        raise HTTPException(status_code=400, detail="Subject and message are required")

    # SECURITY: page_url is rendered as href in /admin/feedback. We allow-list
    # http(s) URLs only — javascript:, data:, vbscript: are silently dropped so
    # the rendered href can never execute in the admin's origin. Mirror the
    # pre-existing Jinja /feedback POST sanitisation (was webapp/routers/account.py).
    cleaned_url: Optional[str] = None
    raw_url = (body.page_url or "").strip()[:500]
    if raw_url:
        try:
            parsed = urlparse(raw_url)
        except ValueError:
            parsed = None
        if parsed and parsed.scheme.lower() in ("http", "https") and parsed.netloc:
            cleaned_url = raw_url

    item = models.UserFeedback(
        user_id=user_id,
        category=category,
        subject=subject[:255],
        message=message,
        page_url=cleaned_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "id": item.id,
        "category": item.category,
        "subject": item.subject,
        "created_at": utc_iso(item.created_at),
    }


# ── POST /api/v1/jobs/{id}/corrections ────────────────────────────────────────

_ALLOWED_CORRECTION_ACTIONS = {"delete", "reclassify", "add"}


class _CorrectionItem(BaseModel):
    detection_index: int
    action: str
    new_label: Optional[str] = None
    new_bbox: Optional[List[float]] = None    # [x1, y1, x2, y2]
    note: Optional[str] = None


class _CorrectionsPayload(BaseModel):
    corrections: List[_CorrectionItem]


@router.post("/jobs/{job_id}/corrections", status_code=201)
async def api_job_corrections(
    job_id: int,
    payload: _CorrectionsPayload,
    current_user: models.User = Depends(_get_api_user),
    db: Session = Depends(get_db),
):
    """Record user corrections against YOLO detections on a job.

    FEATURES #28 — active-learning plumbing. Each correction in the body
    becomes one row in ``model_corrections``. The bulk-insert is atomic
    against the request: either all rows persist or none do (single commit).

    Action contract::

        delete       → false-positive at detection_index.
        reclassify   → wrong class; new_label REQUIRED.
        add          → false-negative; new_bbox REQUIRED (new_label optional).

    The endpoint validates the action vocabulary and that the required
    companion fields are present. It does NOT attempt to apply the
    correction back into ``Job.gpu_detections`` — that's a UI concern; this
    endpoint is a write-only audit log that the (future) export script
    consumes to build training data.
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Access denied")

    if not payload.corrections:
        raise HTTPException(status_code=400, detail="corrections array is empty")

    # Validate all entries before inserting any — fail fast and atomically.
    for i, c in enumerate(payload.corrections):
        if c.action not in _ALLOWED_CORRECTION_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"corrections[{i}].action must be one of "
                       f"{sorted(_ALLOWED_CORRECTION_ACTIONS)}; got {c.action!r}",
            )
        if c.action == "reclassify" and not c.new_label:
            raise HTTPException(
                status_code=400,
                detail=f"corrections[{i}]: reclassify requires new_label",
            )
        if c.action == "add" and not c.new_bbox:
            raise HTTPException(
                status_code=400,
                detail=f"corrections[{i}]: add requires new_bbox",
            )
        if c.new_bbox is not None:
            if not (isinstance(c.new_bbox, list) and len(c.new_bbox) == 4):
                raise HTTPException(
                    status_code=400,
                    detail=f"corrections[{i}].new_bbox must be [x1, y1, x2, y2]",
                )

    rows = [
        models.ModelCorrection(
            job_id=job_id,
            user_id=current_user.id,
            detection_index=c.detection_index,
            action=c.action,
            new_label=c.new_label,
            new_bbox=c.new_bbox,
            note=c.note,
        )
        for c in payload.corrections
    ]
    db.add_all(rows)
    db.commit()

    return {"stored": len(rows), "job_id": job_id}


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
