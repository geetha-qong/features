"""Backfill canonical.json for legacy jobs.

The canonical-entity emitter shipped on 2026-05-28 (commit 024cf4a, FEATURES #26).
Any job processed before that date has valve_list.csv / instrumentation_index.csv
on disk but no canonical.json next to them, so the editable-deliverables API
(GET /api/v1/jobs/{id}/entities) returns 404 and the DatasheetDrawer cannot load.

This script reads each legacy job's CSVs and re-emits canonical.json via
webapp.deliverables.pipeline_emitter.write_canonical_for_job — the same code the
pipeline now runs at job-completion time. Idempotent: skips jobs that already
have canonical.json.

Run inside the `web` container:

    docker compose exec web python -m webapp.scripts.backfill_canonical [--dry-run] [--job-id N] [--from-db]

Default mode walks the filesystem under /app/job_outputs (covers both flat
{job_id}/ and org-scoped {org_id}/{job_id}/ layouts). --from-db iterates
models.Job rows where output_csv_path is set — preferred when the DB is the
source of truth and you want to skip orphan dirs.
"""

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

from webapp import models
from webapp.database import SessionLocal
from webapp.deliverables.pipeline_emitter import write_canonical_for_job


def iter_jobs_from_db() -> Iterable[Tuple[int, Path]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(models.Job)
            .filter(models.Job.output_csv_path.isnot(None))
            .all()
        )
        for j in rows:
            if not j.output_csv_path:
                continue
            yield j.id, Path(j.output_csv_path).parent
    finally:
        db.close()


def iter_jobs_from_fs(root: Path) -> Iterable[Tuple[Optional[int], Path]]:
    if not root.exists():
        return
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name.isdigit():
            yield int(child.name), child
            continue
        for gc in sorted(child.iterdir(), key=lambda p: p.name):
            if gc.is_dir() and gc.name.isdigit():
                yield int(gc.name), gc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="/app/job_outputs",
                   help="job_outputs root (filesystem mode)")
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be written without writing")
    p.add_argument("--job-id", type=int, default=None,
                   help="restrict to a single job id")
    p.add_argument("--from-db", action="store_true",
                   help="iterate via models.Job rows instead of walking the FS")
    args = p.parse_args()

    pairs = (
        list(iter_jobs_from_db()) if args.from_db
        else list(iter_jobs_from_fs(Path(args.root)))
    )

    n_seen = n_existing = n_nocsv = n_written = n_errors = 0
    for job_id, job_dir in pairs:
        if args.job_id is not None and job_id != args.job_id:
            continue
        n_seen += 1
        canonical_path = job_dir / "canonical.json"
        if canonical_path.exists():
            n_existing += 1
            continue
        has_valve = (job_dir / "valve_list.csv").exists()
        has_inst = (job_dir / "instrumentation_index.csv").exists()
        if not (has_valve or has_inst):
            n_nocsv += 1
            print(f"  skip job {job_id}: no CSVs in {job_dir}")
            continue
        if args.dry_run:
            print(f"  DRY: job {job_id} → {canonical_path}")
            continue
        try:
            result = write_canonical_for_job(job_dir=job_dir, job_id=job_id or 0)
            print(f"  wrote job {job_id}: valves={result.valve_count} "
                  f"instruments={result.instrument_count} → {result.canonical_path}")
            n_written += 1
        except Exception as e:
            n_errors += 1
            print(f"  ERROR job {job_id}: {type(e).__name__}: {e}")

    print()
    print(f"Summary: seen={n_seen} written={n_written} "
          f"already_present={n_existing} no_csvs={n_nocsv} errors={n_errors}")
    return 0 if n_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
