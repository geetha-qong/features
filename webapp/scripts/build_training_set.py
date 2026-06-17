"""Versioned training-set builder — the AGGREGATE step of the self-learning loop.

Unifies the existing exporters (`export_annotations_for_yolo`,
`export_graph_for_training`) into one dated dataset directory plus a manifest,
and additionally collects a tag-corrections JSONL from `EntityOverride` rows.

Design: docs/superpowers/specs/2026-06-17-self-learning-loop-design.md

Layout produced under ``<out_root>/<YYYY-MM-DD>/``::

    detection/<job_id>/<tile>.txt   # YOLO labels (via the YOLO exporter)
    graph/edges.jsonl               # graph-correction edges (via the graph exporter)
    tags/tag_corrections.jsonl      # EntityOverride tag edits (this script)
    manifest.json                   # counts + provenance

The ``--since`` default is ``current_model_trained_at()`` — so an un-dated run
builds "everything corrected since the current production model", the natural
retrain corpus. Pass ``--since`` to override; ``since_source`` in the manifest
records which path was taken.

Usage:
    python -m webapp.scripts.build_training_set \
        [--since YYYY-MM-DD] [--out datasets/learning] \
        [--job-id N ...] [--dry-run]

Pure read against the DB + filesystem; safe to run repeatedly (the underlying
YOLO exporter is idempotent; graph/tags JSONL are overwritten each run).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from webapp import models
from webapp.database import SessionLocal
from webapp.datetime_utils import utc_iso
from webapp.model_version import current_model_trained_at, current_version

# Import the existing exporters by module. These pull heavy deps (PIL) at import
# time; guard so the dry-run path still works on a thin local checkout.
try:
    from webapp.scripts import export_annotations_for_yolo as _yolo_exporter
except Exception as _e:  # pragma: no cover - import-environment dependent
    _yolo_exporter = None
    _YOLO_IMPORT_ERR = _e
else:
    _YOLO_IMPORT_ERR = None

try:
    from webapp.scripts import export_graph_for_training as _graph_exporter
except Exception as _e:  # pragma: no cover - import-environment dependent
    _graph_exporter = None
    _GRAPH_IMPORT_ERR = _e
else:
    _GRAPH_IMPORT_ERR = None


DEFAULT_OUT_ROOT = "datasets/learning"


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    """YYYY-MM-DD -> aware UTC datetime (midnight). None passes through."""
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def _resolve_since(
    since_arg: Optional[str],
) -> "tuple[Optional[datetime], str]":
    """Resolve the effective since-filter + record its source.

    Returns ``(since_dt_or_None, source)`` where source is one of
    ``"arg"`` | ``"current_model_trained_at"`` | ``"none"``.
    """
    if since_arg:
        return _parse_since(since_arg), "arg"
    anchor = current_model_trained_at()
    if anchor is not None:
        return anchor, "current_model_trained_at"
    return None, "none"


def _tag_corrections(
    db,
    since: Optional[datetime],
    job_ids: Optional[List[int]],
) -> List[dict]:
    """EntityOverride rows where field_name == 'tag', as JSONL-ready dicts."""
    q = db.query(models.EntityOverride).filter(
        models.EntityOverride.field_name == "tag"
    )
    if job_ids:
        q = q.filter(models.EntityOverride.job_id.in_(job_ids))
    if since is not None:
        q = q.filter(models.EntityOverride.edited_at >= since)
    rows = q.order_by(
        models.EntityOverride.job_id, models.EntityOverride.id
    ).all()
    out: List[dict] = []
    for row in rows:
        out.append(
            {
                "job_id": row.job_id,
                "entity_id": row.entity_id,
                "new_tag": row.new_value,
                "prior_tag": row.prior_value,
                "edited_at": utc_iso(row.edited_at),
            }
        )
    return out


def _class_counts(
    db,
    since: Optional[datetime],
    job_ids: Optional[List[int]],
) -> Dict[str, int]:
    """Per-class label inventory from labeled UserAnnotation rows in scope.

    Grouped by ``f"{entity_class}/{sub_class or '_'}"``, counting rows whose
    status is in (user_added, user_confirmed).
    """
    q = db.query(models.UserAnnotation).filter(
        models.UserAnnotation.status.in_(("user_added", "user_confirmed"))
    )
    if job_ids:
        q = q.filter(models.UserAnnotation.job_id.in_(job_ids))
    if since is not None:
        q = q.filter(models.UserAnnotation.created_at >= since)
    counts: Dict[str, int] = defaultdict(int)
    for row in q.all():
        key = "{}/{}".format(row.entity_class, row.sub_class or "_")
        counts[key] += 1
    return dict(counts)


def run(
    *,
    since: Optional[str],
    out_root: str,
    job_ids: Optional[List[int]],
    dry_run: bool,
    date_str: str,
) -> dict:
    """Build (or, in dry-run, describe) a dated training set.

    ``date_str`` is supplied by the caller (``main()`` uses today's UTC date) so
    this function stays deterministic and testable — no ``datetime.now()`` here.

    Returns the manifest dict in both real and dry-run modes.
    """
    since_dt, since_source = _resolve_since(since)
    out_dir = Path(out_root) / date_str
    generated_at = utc_iso(datetime.now(timezone.utc))

    db = SessionLocal()
    try:
        tag_rows = _tag_corrections(db, since_dt, job_ids)
        class_counts = _class_counts(db, since_dt, job_ids)
    finally:
        db.close()

    # Exporter outputs. job_ids fan out to the single-job exporters (they accept
    # one --job-id each); None means "all jobs".
    job_id_list = list(job_ids) if job_ids else [None]

    detection_dir = out_dir / "detection"
    graph_path = out_dir / "graph" / "edges.jsonl"
    tags_path = out_dir / "tags" / "tag_corrections.jsonl"

    det_label_files = 0
    det_annotations = 0
    det_skipped = 0
    det_jobs: List[int] = []
    graph_edges = 0
    exporter_note: Optional[str] = None

    if dry_run:
        exporter_note = (
            "dry-run: exporters not invoked; detection/graph counts reported "
            "as 0 (run without --dry-run to materialize them)"
        )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Detection (YOLO) ────────────────────────────────────────────────
        if _yolo_exporter is None:
            exporter_note = (
                "YOLO exporter import failed ({}); detection skipped".format(
                    _YOLO_IMPORT_ERR
                )
            )
            print("WARN: " + exporter_note)
        else:
            detection_dir.mkdir(parents=True, exist_ok=True)
            seen_jobs: set = set()
            for jid in job_id_list:
                exported, skipped, _jobs_touched = _yolo_exporter.run(
                    job_id=jid,
                    since=since_dt,
                    out_dir=detection_dir,
                    dry_run=False,
                )
                det_annotations += exported
                det_skipped += skipped
            # Count produced label files + the jobs they belong to.
            for txt in detection_dir.rglob("*.txt"):
                det_label_files += 1
                seen_jobs.add(txt.parent.name)
            det_jobs = sorted(
                int(j) for j in seen_jobs if j.isdigit()
            )

        # ── Graph ───────────────────────────────────────────────────────────
        if _graph_exporter is None:
            note = "graph exporter import failed ({}); graph skipped".format(
                _GRAPH_IMPORT_ERR
            )
            exporter_note = (exporter_note + "; " + note) if exporter_note else note
            print("WARN: " + note)
        else:
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            if job_ids:
                # Concatenate per-job exports into the single edges.jsonl.
                import tempfile

                total = 0
                with graph_path.open("w", encoding="utf-8") as out_fh:
                    for jid in job_ids:
                        tmp = Path(
                            tempfile.mkstemp(suffix=".jsonl")[1]
                        )
                        try:
                            _graph_exporter.run(
                                job_id=jid, since=since_dt, out_path=tmp
                            )
                            if tmp.exists():
                                text = tmp.read_text(encoding="utf-8")
                                if text:
                                    out_fh.write(text)
                                    total += sum(
                                        1 for ln in text.splitlines() if ln.strip()
                                    )
                        finally:
                            tmp.unlink(missing_ok=True)
                graph_edges = total
            else:
                graph_edges = _graph_exporter.run(
                    job_id=None, since=since_dt, out_path=graph_path
                )

        # ── Tags ────────────────────────────────────────────────────────────
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        with tags_path.open("w", encoding="utf-8") as fh:
            for r in tag_rows:
                fh.write(json.dumps(r, ensure_ascii=False))
                fh.write("\n")

    manifest = {
        "generated_at": generated_at,
        "model_version": current_version(),
        "since": utc_iso(since_dt),
        "since_source": since_source,
        "job_ids": list(job_ids) if job_ids else None,
        "detection": {
            "label_files": det_label_files,
            "annotations": det_annotations,
            "skipped_unmappable": det_skipped,
            "jobs": det_jobs,
        },
        "graph": {"edges": graph_edges},
        "tags": {"corrections": len(tag_rows)},
        "class_counts": class_counts,
    }
    if exporter_note:
        manifest["note"] = exporter_note

    if dry_run:
        print("DRY RUN — manifest that would be written to {}:".format(
            out_dir / "manifest.json"
        ))
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return manifest

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print("Training set built: {}".format(out_dir))
    print(
        "  detection: {} label files, {} annotations, {} skipped, {} jobs".format(
            det_label_files, det_annotations, det_skipped, len(det_jobs)
        )
    )
    print("  graph:     {} edges".format(graph_edges))
    print("  tags:      {} corrections".format(len(tag_rows)))
    print(
        "  since:     {} ({})".format(
            manifest["since"] or "<none>", since_source
        )
    )
    print("  manifest:  {}".format(manifest_path))
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--since", type=str, default=None,
        help="only corrections on/after this YYYY-MM-DD "
             "(default: current model's trained-at date)",
    )
    p.add_argument(
        "--out", type=str, default=DEFAULT_OUT_ROOT,
        help="output root; the dated dir is <out>/<YYYY-MM-DD>/ "
             "(default {})".format(DEFAULT_OUT_ROOT),
    )
    p.add_argument(
        "--job-id", type=int, action="append", default=None, dest="job_ids",
        help="restrict to this job id (repeatable)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="compute + print the manifest; write nothing, invoke no exporters",
    )
    args = p.parse_args()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run(
        since=args.since,
        out_root=args.out,
        job_ids=args.job_ids,
        dry_run=args.dry_run,
        date_str=date_str,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
