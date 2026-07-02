"""CLI: score a job's extracted graph against its frozen ground truth.

    python -m webapp.scripts.score_graph --job-id 43 [--graph PATH] [--gt PATH] [--json] [--seed]

Thin wrapper over webapp.graph.scoring. DB-free: the extracted graph is found
by globbing job_outputs (flat <=39 and org-scoped >=40 layouts), or passed
explicitly with --graph.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Optional, Sequence

from webapp.graph import scoring

DEFAULT_GT_DIR = os.path.join("tests", "graph_ground_truth")


def resolve_graph_path(job_id: int, explicit: Optional[str], root: str = "job_outputs") -> Optional[str]:
    if explicit:
        return explicit
    matches = sorted(glob.glob(os.path.join(root, "**", str(job_id), "canonical_graph.json"), recursive=True))
    flat = os.path.join(root, str(job_id), "canonical_graph.json")
    if flat in matches:
        return flat
    return matches[0] if matches else None


def resolve_gt_path(job_id: int, explicit: Optional[str]) -> str:
    return explicit or os.path.join(DEFAULT_GT_DIR, f"job_{job_id}.json")


def format_report(score: scoring.GraphScore, job_id: int) -> str:
    da = "n/a" if score.directed_agreement is None else f"{score.directed_agreement:.3f}"
    return "\n".join([
        f"Graph score — job {job_id}",
        f"  node precision={score.node_precision:.3f} recall={score.node_recall:.3f} f1={score.node_f1:.3f} "
        f"(tp={score.node_tp} fp={score.node_fp} fn={score.node_fn})",
        f"  edge f1={score.edge_f1:.3f} precision={score.edge_precision:.3f} recall={score.edge_recall:.3f} "
        f"(tp={score.edge_tp} fp={score.edge_fp} fn={score.edge_fn})",
        f"  directed_agreement: {da}",
        f"  is_isomorphic: {score.is_isomorphic}",
        f"  connectivity: extracted {score.extracted_components} comp / "
        f"largest {score.extracted_largest_frac:.2f}  |  gt {score.gt_components} comp / "
        f"largest {score.gt_largest_frac:.2f}",
        f"  missing_edges: {len(score.missing_edges)}   extra_edges: {len(score.extra_edges)}",
    ])


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Score a job graph against its ground truth.")
    ap.add_argument("--job-id", type=int, required=True)
    ap.add_argument("--graph", default=None, help="explicit path to extracted canonical_graph.json")
    ap.add_argument("--gt", default=None, help="explicit path to ground-truth json")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    ap.add_argument("--seed", action="store_true", help="copy the extracted graph to the GT path and exit")
    args = ap.parse_args(argv)

    graph_path = resolve_graph_path(args.job_id, args.graph)
    if not graph_path or not os.path.exists(graph_path):
        print(f"error: extracted graph not found for job {args.job_id} "
              f"(looked at {graph_path or 'job_outputs/**/'+str(args.job_id)})", file=sys.stderr)
        return 2
    with open(graph_path, "r", encoding="utf-8") as f:
        extracted = json.load(f)

    gt_path = resolve_gt_path(args.job_id, args.gt)

    if args.seed:
        parent = os.path.dirname(gt_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(extracted, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"seeded ground truth: {gt_path} (hand-correct it, then commit)")
        return 0

    if not os.path.exists(gt_path):
        print(f"error: ground truth not found: {gt_path} (run with --seed first)", file=sys.stderr)
        return 2
    with open(gt_path, "r", encoding="utf-8") as f:
        gt = json.load(f)

    score = scoring.score_graph(extracted, gt)
    if args.json:
        print(json.dumps(score.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(score, args.job_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
