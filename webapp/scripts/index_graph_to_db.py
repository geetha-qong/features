"""Index all on-disk `canonical_graph.json` files into `graph_nodes` /
`graph_edges` (graph-extraction, 2026-06-13 design).

One-shot CLI. Run inside the `web` container:

    docker compose exec web python -m webapp.scripts.index_graph_to_db [--dry-run] [--job-id N]

Per-job idempotent: reads `canonical_graph.json` next to the job's
`output_csv_path` and upserts every node + edge via `sync_graph_to_db`. Safe to
re-run. Back-population partner of the dual-write in `pipeline_runner.py`.
"""

import argparse
import json
import sys
from pathlib import Path

from webapp import models
from webapp.database import SessionLocal
from webapp.graph.graph_db_index import sync_graph_to_db


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

        n_seen = n_synced = n_no_graph = n_errors = 0
        total_nodes = total_edges = 0

        for j in jobs:
            if not j.output_csv_path:
                continue
            n_seen += 1
            graph_path = Path(j.output_csv_path).parent / "canonical_graph.json"
            if not graph_path.exists():
                n_no_graph += 1
                print(f"  skip job {j.id}: no canonical_graph.json at {graph_path.parent}")
                continue
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                graph.setdefault("job_id", j.id)
            except Exception as e:
                n_errors += 1
                print(f"  ERROR job {j.id}: read failed: {type(e).__name__}: {e}")
                continue

            if args.dry_run:
                print(f"  DRY: job {j.id}: {len(graph.get('nodes', []))} nodes, "
                      f"{len(graph.get('edges', []))} edges")
                continue

            try:
                n_nodes, n_edges = sync_graph_to_db(graph, db)
                total_nodes += n_nodes
                total_edges += n_edges
                n_synced += 1
                print(f"  synced job {j.id}: nodes={n_nodes} edges={n_edges}")
            except Exception as e:
                db.rollback()
                n_errors += 1
                print(f"  ERROR job {j.id}: sync failed: {type(e).__name__}: {e}")

        print()
        print(f"Summary: seen={n_seen} synced={n_synced} "
              f"no_graph={n_no_graph} errors={n_errors} | "
              f"rows nodes={total_nodes} edges={total_edges}")
        return 0 if n_errors == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
