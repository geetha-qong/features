"""CLI: freeze a job's hand-corrected MERGED graph as ground truth.

    python -m webapp.scripts.freeze_graph_gt --job-id 64 [--out PATH] [--status verified]

Workflow: a human corrects a job's graph in Studio (add missing symbols, remove
false positives, draw the real pipes — FEATURES #129). This snapshots the
resulting **merged** graph (auto extraction + user node/edge corrections) into
`tests/graph_ground_truth/job_N.json`, which `webapp.scripts.score_graph` reads.

Unlike `GET /jobs/{id}/graph` (which RETURNS rejected nodes flagged so the UI can
ghost + restore them), the frozen GT is the *clean truth*: rejected nodes and any
edge touching them are DROPPED; user-added nodes + user-drawn edges are included.
It reuses the exact merge helpers from `webapp.routers.graph` so the GT matches
what the user sees in Studio (guarded by `tests/unit/test_freeze_graph_gt.py`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from webapp.graph.orphan_dedup import superseded_auto_ids


def build_frozen_graph(job_id: int, db) -> Dict[str, Any]:
    """Return the clean merged ground-truth graph dict for a job.

    Reuses webapp.routers.graph helpers. Raises FileNotFoundError if the job has
    no `canonical_graph.json` (pipeline/graph step hasn't run).
    """
    from webapp import models
    from webapp.routers.graph import (
        _annotation_nodes,
        _job_dir,
        _rejected_entity_ids,
        _user_edge_to_dict,
    )

    job = db.get(models.Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    job_dir = _job_dir(job)
    graph_path = (job_dir / "canonical_graph.json") if job_dir else None
    if not graph_path or not graph_path.exists():
        raise FileNotFoundError(
            f"canonical_graph.json not found for job {job_id} "
            f"(looked at {graph_path}); run the pipeline/graph step first"
        )

    graph: Dict[str, Any] = json.loads(graph_path.read_text(encoding="utf-8"))
    graph.setdefault("job_id", job_id)

    rejected_ids = _rejected_entity_ids(job_id, db)
    annotation_nodes = _annotation_nodes(job_id, db, rejected_ids)

    # NODES — drop rejected (clean truth), tag source=auto, add non-rejected user
    # nodes (deduped against canonical entity_ids). Strip the UI-only `rejected`
    # flag (always false in the frozen set).
    auto_nodes: List[Dict[str, Any]] = []
    rejected_node_ids = set()
    for n in graph.get("nodes", []):
        eid = n.get("entity_id") or ""
        if eid in rejected_ids:
            if n.get("id"):
                rejected_node_ids.add(n["id"])
            continue
        n.setdefault("source", "auto")
        n.pop("rejected", None)
        auto_nodes.append(n)
    canonical_eids = {(n.get("entity_id") or "") for n in auto_nodes}
    user_nodes = [
        {k: v for k, v in a.items() if k != "rejected"}
        for a in annotation_nodes
        if not a.get("rejected") and a.get("entity_id") not in canonical_eids
    ]
    nodes = auto_nodes + user_nodes

    # Drop orphan auto nodes (no entity_id) superseded by an adopted user node.
    _superseded = superseded_auto_ids(auto_nodes, user_nodes)
    if _superseded:
        nodes = [n for n in nodes if n.get("id") not in _superseded]
        rejected_node_ids = rejected_node_ids | _superseded

    # EDGES — auto edges (minus user-rejected auto-edges) + user edges, dropping
    # any edge touching a rejected node (by entity_id OR node id — auto edges key
    # on node id). Mirrors webapp.routers.graph.get_job_graph edge omission.
    reject_keys = rejected_ids | rejected_node_ids
    corrections = (
        db.query(models.GraphCorrection)
        .filter(models.GraphCorrection.job_id == job_id)
        .all()
    )
    rejected_auto_ids = {
        r.source_entity_id for r in corrections if r.source == "auto_rejection"
    }
    auto_edges = [e for e in graph.get("edges", []) if e.get("id") not in rejected_auto_ids]
    for e in auto_edges:
        e.setdefault("directed", False)
    user_edges = [
        _user_edge_to_dict(r)
        for r in corrections
        if r.source == "user" and r.status != "user_rejected"
    ]

    def _touches(e: Dict[str, Any]) -> bool:
        return bool(
            {e.get("source_entity_id"), e.get("target_entity_id"),
             e.get("source"), e.get("target")} & reject_keys
        )

    edges = [e for e in (auto_edges + user_edges) if not _touches(e)]

    graph["nodes"] = nodes
    graph["edges"] = edges
    stats = dict(graph.get("stats", {}))
    stats["nodes"] = len(nodes)
    stats["edges"] = len(edges)
    graph["stats"] = stats
    return graph


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Freeze a job's hand-corrected merged graph as ground truth."
    )
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--out", default=None, help="output path (default tests/graph_ground_truth/job_N.json)")
    ap.add_argument(
        "--status", default="verified",
        help="meta.status to stamp (default 'verified' — only freeze after hand-correcting in Studio)",
    )
    args = ap.parse_args(argv)

    from webapp.database import SessionLocal

    db = SessionLocal()
    try:
        try:
            graph = build_frozen_graph(args.job_id, db)
        except (FileNotFoundError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    finally:
        db.close()

    graph["meta"] = {**(graph.get("meta") or {}), "status": args.status,
                     "frozen_from": "studio_merged_graph"}

    out_path = args.out or os.path.join("tests", "graph_ground_truth", f"job_{args.job_id}.json")
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(
        f"froze merged graph → {out_path} "
        f"({len(graph['nodes'])} nodes, {len(graph['edges'])} edges, status={args.status})"
    )
    print("Verify it reflects the true topology, then commit + "
          "`python -m webapp.scripts.score_graph --job-id %d`." % args.job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
