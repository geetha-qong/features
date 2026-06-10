"""Index all on-disk canonical.json files into the `canonical_entities` table.

One-shot CLI. Run inside the `web` container:

    docker compose exec web python -m webapp.scripts.index_canonical_to_db [--dry-run] [--job-id N]

Per-job idempotent: reads `canonical.json` next to the job's `output_csv_path`
and upserts every entity row via `sync_canonical_to_db`. Safe to re-run.

This script is the back-population partner of the dual-write that lives in
`pipeline_runner.py` — together they keep the DB index in sync with the
filesystem source of truth (FEATURES #34).
"""

import argparse
import sys
from pathlib import Path

from webapp import models
from webapp.database import SessionLocal
from webapp.deliverables.canonical_db_index import sync_canonical_to_db
from webapp.deliverables.job_loader import JobCanonicalNotFound, load_canonical_for_job


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="show counts without writing")
    p.add_argument("--job-id", type=int, default=None,
                   help="restrict to a single job id")
    args = p.parse_args()

    db = SessionLocal()
    try:
        q = db.query(models.Job).filter(models.Job.output_csv_path.isnot(None))
        if args.job_id is not None:
            q = q.filter(models.Job.id == args.job_id)
        jobs = q.all()

        n_seen = n_synced = n_no_canonical = n_errors = 0
        total_inserted = total_updated = 0

        for j in jobs:
            if not j.output_csv_path:
                continue
            n_seen += 1
            canonical_dir = Path(j.output_csv_path).parent
            try:
                canonical = load_canonical_for_job(j.output_csv_path)
            except JobCanonicalNotFound:
                n_no_canonical += 1
                print(f"  skip job {j.id}: no canonical.json at {canonical_dir}")
                continue
            except Exception as e:
                n_errors += 1
                print(f"  ERROR job {j.id}: load failed: {type(e).__name__}: {e}")
                continue

            if args.dry_run:
                print(f"  DRY: job {j.id}: {len(canonical.entities)} entities")
                continue

            try:
                ins, upd = sync_canonical_to_db(canonical, db)
                total_inserted += ins
                total_updated += upd
                n_synced += 1
                print(f"  synced job {j.id}: inserted={ins} updated={upd}")
            except Exception as e:
                db.rollback()
                n_errors += 1
                print(f"  ERROR job {j.id}: sync failed: {type(e).__name__}: {e}")

        print()
        print(f"Summary: seen={n_seen} synced={n_synced} "
              f"no_canonical={n_no_canonical} errors={n_errors} | "
              f"rows inserted={total_inserted} updated={total_updated}")
        return 0 if n_errors == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
