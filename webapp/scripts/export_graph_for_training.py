"""Dump graph_corrections rows to a JSONL file for graph-extraction training.

Each `user_added` / `user_confirmed` edge becomes one JSON object per line:
    {"job_id": N, "edge_id": "...", "line_type": "...", "relation_type": "...",
     "source_entity_id": "...", "target_entity_id": "...",
     "polyline": [[x,y],...], "group_id": "...", "metadata": {...}}

Usage:
    python -m webapp.scripts.export_graph_for_training \
        [--job-id N] [--since YYYY-MM-DD] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from webapp import models
from webapp.database import SessionLocal


DEFAULT_OUT = Path("datasets/graph_corrections.jsonl")


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def _row_to_dict(row: models.GraphCorrection) -> dict:
    return {
        "job_id": row.job_id,
        "edge_id": row.edge_id,
        "line_type": row.line_type,
        "relation_type": row.relation_type,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "polyline": row.polyline or [],
        "group_id": row.group_id,
        "metadata": row.metadata_json or {},
    }


def run(
    *,
    job_id: Optional[int],
    since: Optional[datetime],
    out_path: Path,
) -> int:
    db = SessionLocal()
    try:
        q = db.query(models.GraphCorrection).filter(
            models.GraphCorrection.status.in_(("user_added", "user_confirmed"))
        )
        if job_id is not None:
            q = q.filter(models.GraphCorrection.job_id == job_id)
        if since is not None:
            q = q.filter(models.GraphCorrection.created_at >= since)
        rows = q.order_by(
            models.GraphCorrection.job_id, models.GraphCorrection.id
        ).all()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(_row_to_dict(row), ensure_ascii=False))
                fh.write("\n")
        print(f"Exported {len(rows)} edges to {out_path}")
        return len(rows)
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id", type=int, default=None)
    p.add_argument("--since", type=str, default=None)
    p.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    args = p.parse_args()
    run(
        job_id=args.job_id,
        since=_parse_since(args.since),
        out_path=Path(args.out),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
