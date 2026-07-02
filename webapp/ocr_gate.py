"""OCR-completion gate — shared logic so a job's card never traps at "Preparing".

A job is held at "processing" (UI: "Preparing") while extraction is done but the
background OCR tag-resolution step is still pending. This module centralizes that
rule and its timeout so the read path (dashboard list, job status), the
pending-set sites, and the startup reconcile sweep all agree.

The read-path helpers (`is_ocr_overdue`, `effective_status`) are PURE — no DB, no
network — so they are safe to call inside the `async def` endpoints. CLAUDE.md:
never block an async event loop with a synchronous DB call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# A job whose OCR has been pending longer than this is auto-released to "done"
# (graceful degradation — detections simply lack OCR-resolved tag enrichment).
# Above a normal multi-minute run AND above a single 15-min RQ attempt, so a
# still-working job is never falsely released.
OCR_STALE_AFTER = timedelta(minutes=20)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a (possibly naive / non-UTC) datetime to aware-UTC. Naive is
    assumed UTC to match the codebase write convention."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_ocr_overdue(
    ocr_enqueued_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """True iff OCR was enqueued strictly more than OCR_STALE_AFTER ago.

    A NULL enqueue time is NOT overdue (legacy jobs, or pendings set before this
    change) — the startup sweep clears those, the read path does not.
    """
    enq = _as_utc(ocr_enqueued_at)
    if enq is None:
        return False
    return (_as_utc(now) or _utcnow()) - enq > OCR_STALE_AFTER


def effective_status(
    status: Optional[str],
    ocr_status: Optional[str],
    ocr_enqueued_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """Dashboard-facing status.

    Hold at "processing" only while extraction is done AND OCR is actively
    pending AND it has not been pending past the stale timeout. Otherwise return
    the raw status (a done job with done / NULL / overdue OCR reads "done").
    """
    if (
        status == "done"
        and ocr_status == "pending"
        and not is_ocr_overdue(ocr_enqueued_at, now)
    ):
        return "processing"
    return status


def mark_ocr_pending(job, now: Optional[datetime] = None) -> None:
    """Set a job's OCR stage to pending and stamp the enqueue time.

    Called at every site that enqueues background OCR so the stale timeout has a
    reference point. Mutates `job` in place; the caller commits.
    """
    job.ocr_status = "pending"
    job.ocr_enqueued_at = now or _utcnow()


def sweep_stale_ocr(db, now: Optional[datetime] = None) -> int:
    """Persist the released state for jobs stuck pending past the timeout.

    Flips ocr_status pending → done for every job whose extraction is done but
    whose OCR has been pending past OCR_STALE_AFTER (or has no enqueue timestamp —
    legacy / pre-change pendings). Runs OUTSIDE any request path (startup leader),
    so the DB write here is safe. Returns the number flipped.
    """
    from webapp import models  # local import — avoid an import cycle at load time

    cutoff = (_as_utc(now) or _utcnow()) - OCR_STALE_AFTER
    candidates = (
        db.query(models.Job)
        .filter(models.Job.status == "done", models.Job.ocr_status == "pending")
        .all()
    )
    swept = 0
    for job in candidates:
        enq = _as_utc(job.ocr_enqueued_at)
        if enq is None or enq < cutoff:
            job.ocr_status = "done"
            swept += 1
    if swept:
        db.commit()
    return swept
