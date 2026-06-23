"""
Heartbeat watchdog: marks JobRun rows as 'killed' when their pipeline-runner
heartbeat thread has stopped writing. Phase 2 of the observability work.

Runs as a background asyncio task started on FastAPI startup. Independent of
the legacy `_reset_stale_jobs()` startup sweep, which only handles container
restarts — this sweep handles silent worker crashes during a run.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from webapp.database import SessionLocal
from webapp import models


# A JobRun is considered stale if no heartbeat for this long. Pipeline-runner
# beats every 30s, so 3 missed beats = 90s.
STALE_HEARTBEAT_SECONDS = 90

# How often the watchdog sweep runs.
WATCHDOG_INTERVAL_SECONDS = 5 * 60


def reap_stale_runs() -> int:
    """Mark running JobRuns with stale heartbeats as 'killed' and flip the
    parent Job to 'failed' if it's still 'processing'. Returns the count reaped.

    Idempotent: safe to call concurrently or repeatedly.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_HEARTBEAT_SECONDS)
    db = SessionLocal()
    reaped = 0
    try:
        stale_runs = (
            db.query(models.JobRun)
            .filter(
                models.JobRun.status == "running",
                models.JobRun.last_heartbeat_at < cutoff,
            )
            .all()
        )
        for run in stale_runs:
            run.status = "killed"
            run.killer = "heartbeat-watchdog"
            run.ended_at = datetime.utcnow()
            run.error_msg = (
                f"No heartbeat for >{STALE_HEARTBEAT_SECONDS}s — pipeline worker "
                "likely crashed or was killed."
            )
            # If the parent Job is still in 'processing' it has no other live
            # run (only one runs at a time per job) — flip it to failed.
            job = db.query(models.Job).filter(models.Job.id == run.job_id).first()
            if job and job.status == "processing":
                job.status = "failed"
                job.error_msg = run.error_msg
                job.completed_at = datetime.utcnow()
            reaped += 1
        if reaped:
            db.commit()
            print(f"[watchdog] Reaped {reaped} stale run(s): {[r.id for r in stale_runs]}")
    except Exception as e:
        print(f"[watchdog] Sweep error: {e}")
        db.rollback()
    finally:
        db.close()
    return reaped


async def _watchdog_loop() -> None:
    """Long-running asyncio task: sweeps every WATCHDOG_INTERVAL_SECONDS."""
    while True:
        try:
            await asyncio.to_thread(reap_stale_runs)
        except Exception as e:
            print(f"[watchdog] Loop error (continuing): {e}")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)


def start_watchdog(app) -> None:
    """Register the watchdog loop as a startup task on the given FastAPI app."""

    @app.on_event("startup")
    async def _kickoff_watchdog() -> None:  # noqa: D401  (startup hook)
        asyncio.create_task(_watchdog_loop())
        print(
            f"[watchdog] Started: heartbeat threshold {STALE_HEARTBEAT_SECONDS}s, "
            f"sweep every {WATCHDOG_INTERVAL_SECONDS}s"
        )
