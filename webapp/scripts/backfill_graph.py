"""Graph-only backfill (FEATURES #123).

Rebuilds a job's process graph (`canonical_graph.json` + `graph_nodes` /
`graph_edges`) through the CURRENT #66 pipeline (entity node-dedup + chunked
structured-output LLM edge fallback) WITHOUT re-running the paid deliverables
pipeline (`extractor.py` passes 3-5 / enrichment) and WITHOUT re-inferring YOLO
detections. The process graph is YOLO-derived and orthogonal to the
valve-list / instrument-index deliverables (CLAUDE.md "Third path"), so a graph
rebuild leaves every CSV / canonical.json deliverable untouched.

Use when a job's stored `gpu_detections` are already current but its graph
predates a graph-pipeline fix — e.g. job 38 sat at 202 nodes / 11 edges, the
classic pre-#66 sparse-edge symptom, vs the healed job 43 at 128 / 155.

It REFUSES to run on stale or missing detections (you must run
`backfill_gpu_detections` first), so it can never silently trigger
re-inference — honouring the "never auto-rerun jobs" policy.

  python -m webapp.scripts.backfill_graph --job-id 38               # rebuild one
  python -m webapp.scripts.backfill_graph --job-id 38 --dry-run     # report only
  python -m webapp.scripts.backfill_graph --job-id 38 --job-id 39   # several

Long graph builds (LLM fallback per 3x3 tile) can take minutes — run detached
over SSM and poll the log (CLAUDE.md).
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple


def _detections(job) -> list:
    raw = getattr(job, "gpu_detections", None)
    if not raw:
        return []
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        return []


def _backfill_decision(job, dets: list, stale) -> Tuple[bool, str]:
    """Pure guard: decide whether a job is safe to graph-backfill.

    Refuses anything that would need re-inference or has no output dir, so the
    caller never silently re-runs YOLO or a deliverables pipeline.
    """
    if job is None:
        return False, "MISSING"
    if not dets:
        return False, "no gpu_detections — run backfill_gpu_detections first"
    if stale:
        return False, "gpu_detections are STALE — run backfill_gpu_detections first"
    if not getattr(job, "output_csv_path", None):
        return False, "no output_csv_path"
    return True, "ok"


def _counts(db, job_id: int) -> Tuple[int, int]:
    from webapp import models
    n = db.query(models.GraphNodeRow).filter(models.GraphNodeRow.job_id == job_id).count()
    e = db.query(models.GraphEdgeRow).filter(models.GraphEdgeRow.job_id == job_id).count()
    return n, e


def backfill_one(db, job_id: int, dry_run: bool) -> bool:
    from webapp import models
    # pipeline_runner is host-importable (no module-level cv2); the heavy graph
    # modules are imported lazily below so the guard/dry-run paths stay light.
    from webapp.pipeline_runner import _detections_are_stale

    job = db.get(models.Job, job_id)
    dets = _detections(job)
    stale = bool(dets) and _detections_are_stale(dets)
    ok, reason = _backfill_decision(job, dets, stale)
    if not ok:
        print(f"job {job_id}: {reason} — skipped")
        return False

    before_n, before_e = _counts(db, job_id)
    job_dir = Path(job.output_csv_path).parent
    print(f"job {job_id}: before nodes={before_n} edges={before_e} dets={len(dets)} dir={job_dir}")
    if dry_run:
        print(f"job {job_id}: --dry-run, not rebuilding")
        return True

    from webapp.pipeline_runner import _run_line_detection
    from webapp.graph.pipeline import extract_graph
    from webapp.graph.graph_db_index import sync_graph_to_db
    from webapp.datetime_utils import utc_iso, utcnow

    # OpenCV line tracing → topology.json (current tracer w/ #65 downscale guard).
    try:
        _run_line_detection(job_id, job_dir)
    except Exception as e:
        print(f"job {job_id}: line-detect failed ({e}) — continuing with existing topology", file=sys.stderr)

    graph = extract_graph(
        str(job_dir),
        dets,
        generated_at=utc_iso(utcnow()),
        job_id=job_id,
        tile_local_detections=True,
    )
    n_nodes, n_edges = sync_graph_to_db(graph, db)
    db.commit()
    print(f"job {job_id}: after  nodes={n_nodes} edges={n_edges} stats={graph.get('stats', {})}")
    return True


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description="Graph-only backfill (no deliverable re-run, no re-inference).")
    ap.add_argument("--job-id", type=int, action="append", required=True, help="job id (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="report before-counts only; do not rebuild")
    args = ap.parse_args(argv)

    from webapp.database import SessionLocal
    db = SessionLocal()
    try:
        ok = sum(1 for jid in args.job_id if backfill_one(db, jid, args.dry_run))
        print(f"done: {ok}/{len(args.job_id)} job(s) rebuilt" + (" (dry-run)" if args.dry_run else ""))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
