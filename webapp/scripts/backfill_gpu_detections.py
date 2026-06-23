"""Backfill ``Job.gpu_detections`` for legacy jobs that predate in-process YOLO.

Jobs processed before ``webapp/inference.py`` existed (FEATURES #28) have
``gpu_detections`` NULL/empty, so the Studio canvas shows no detection overlay —
even though their extracted CSVs / canonical entities are intact. This re-runs
YOLO ONNX inference over each job's EXISTING tiles and populates
``gpu_detections`` via the SAME code path a fresh job uses
(``pipeline_runner._run_inplace_inference``), so the stored shape + coordinate
space match exactly (no #56-style scatter risk).

Purely additive: only writes ``gpu_detections``; never touches CSVs / canonical /
entity data. Idempotent — ``_run_inplace_inference`` skips any job that already
has detections, so re-running is safe.

Usage (inside the web/cpu-worker container, model baked into the image):
    python -m webapp.scripts.backfill_gpu_detections --dry-run
    python -m webapp.scripts.backfill_gpu_detections --job-id 5
    python -m webapp.scripts.backfill_gpu_detections [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from webapp import models
from webapp.database import SessionLocal


def _is_empty_detections(raw) -> bool:
    """True if a job's gpu_detections is NULL / empty / unparsable (needs backfill)."""
    if not raw:
        return True
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return True
    return not (isinstance(v, list) and len(v) > 0)


def jobs_needing_backfill(db, job_id: Optional[int] = None) -> List[models.Job]:
    """Done jobs with an output path but empty gpu_detections, ordered by id."""
    q = db.query(models.Job).filter(
        models.Job.status == "done",
        models.Job.output_csv_path.isnot(None),
    )
    if job_id is not None:
        q = q.filter(models.Job.id == job_id)
    return [
        j for j in q.order_by(models.Job.id).all()
        if _is_empty_detections(j.gpu_detections)
    ]


def run(*, job_id: Optional[int], limit: Optional[int], dry_run: bool) -> dict:
    """Backfill gpu_detections for legacy jobs. Returns a summary dict."""
    # Late import: pipeline_runner pulls heavy pipeline deps; only needed for a
    # real run and keeps the module importable for the dry-run / tests.
    db = SessionLocal()
    try:
        jobs = jobs_needing_backfill(db, job_id=job_id)
        if limit is not None:
            jobs = jobs[:limit]
        ids = [j.id for j in jobs]
        print(f"{len(ids)} job(s) need gpu_detections backfill: {ids}")

        if dry_run:
            print("DRY RUN: pass no --dry-run to populate.")
            return {"candidates": ids, "processed": 0, "dry_run": True}

        from webapp.pipeline_runner import _run_inplace_inference

        processed = 0
        for j in jobs:
            job_dir = Path(j.output_csv_path).parent
            print(f"--- job {j.id} ({j.pid_no}) — tiles in {job_dir / 'tmp'} ---")
            _run_inplace_inference(j.id, job_dir)
            processed += 1

        # Re-read committed counts (each _run_inplace_inference commits via its
        # own short session).
        db.expire_all()
        results = {}
        for jid in ids:
            jj = db.get(models.Job, jid)
            n = 0
            if jj and jj.gpu_detections:
                try:
                    n = len(json.loads(jj.gpu_detections))
                except (ValueError, TypeError):
                    n = -1
            results[jid] = n
        populated = sum(1 for v in results.values() if v > 0)
        print(f"\nBackfill complete: processed {processed} job(s); "
              f"{populated} now have detections.")
        print("detections per job:", results)
        return {"candidates": ids, "processed": processed,
                "detections": results, "dry_run": False}
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id", type=int, default=None,
                   help="backfill a single job id")
    p.add_argument("--limit", type=int, default=None,
                   help="cap how many jobs to process this run")
    p.add_argument("--dry-run", action="store_true",
                   help="list candidate jobs; write nothing")
    args = p.parse_args()
    run(job_id=args.job_id, limit=args.limit, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
