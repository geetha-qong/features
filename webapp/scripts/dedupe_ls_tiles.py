"""Dedupe duplicate tile tasks in Label Studio projects.

Re-importing the same PDF into an LS project created a fresh tile task for every
tile on each import, so projects accumulated duplicate tasks pointing at the SAME
`data.image` (LS projects 25/26 hit ~2x — June 2026). The root cause is fixed in
`webapp/auto_tile.py` (skip tiling if the project already has tiles); this script
cleans up the existing duplicates.

Rule: keep ONE task per distinct `data.image`. Prefer a task that has annotations
(never lose labeling work), else the lowest task id (the original). Delete the rest.

Usage (inside the web/cpu-worker container, LS env configured):
    python -m webapp.scripts.dedupe_ls_tiles --project 25 26            # dry-run (default)
    python -m webapp.scripts.dedupe_ls_tiles --project 25 26 --execute  # actually delete
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Tuple

from webapp import label_studio_client as ls


def normalize_result(result: Any) -> str:
    """Stable key for an annotation's `result` so identical labels on duplicate
    copies compare equal. Drops the per-region random `id` (differs between
    copies) and sorts by (from_name, type, value) so ordering doesn't matter."""
    if not isinstance(result, list):
        return json.dumps(result, sort_keys=True, default=str)
    norm = []
    for r in result:
        if not isinstance(r, dict):
            norm.append(r)
            continue
        d = {k: v for k, v in r.items() if k != "id"}
        norm.append(d)
    norm.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
    return json.dumps(norm, sort_keys=True, default=str)


def _ann_count(task: Dict[str, Any]) -> int:
    v = task.get("total_annotations")
    if isinstance(v, int):
        return v
    anns = task.get("annotations")
    return len(anns) if isinstance(anns, list) else 0


def plan_dedupe(tasks: List[Dict[str, Any]]) -> Tuple[List[int], List[int], List[int]]:
    """Decide which task ids to KEEP, which are SAFE to delete (unannotated
    duplicates), and which are ANNOTATED duplicates (held back by default —
    deleting them loses labeling work). Returns (keep, delete_safe, delete_annotated).

    Groups by `data.image`. For each group keeps the task with the most
    annotations (ties → lowest id), deletes the rest. Tasks with no/blank image
    are always kept (never touched). Returns (keep_ids, delete_ids,
    annotated_deletes) where annotated_deletes counts deletions that carry
    annotations (a warning signal — should normally be 0)."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    keep: List[int] = []
    for t in tasks:
        tid = t.get("id")
        if tid is None:
            continue
        img = ((t.get("data") or {}).get("image")) or ""
        if not str(img).strip():
            keep.append(tid)  # no image to dedupe on — leave alone
            continue
        groups.setdefault(str(img), []).append(t)

    delete_safe: List[int] = []
    delete_annotated: List[int] = []
    for _img, grp in groups.items():
        # Best copy kept first: most annotations, then lowest id.
        grp_sorted = sorted(grp, key=lambda t: (-_ann_count(t), t.get("id", 0)))
        keep.append(grp_sorted[0]["id"])
        for t in grp_sorted[1:]:
            if _ann_count(t) > 0:
                delete_annotated.append(t["id"])
            else:
                delete_safe.append(t["id"])
    return keep, delete_safe, delete_annotated


def build_groups(tasks: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Group tasks by `data.image`; return [(keeper, [duplicates]), ...] only for
    groups with >1 task. Keeper = most annotations, ties → lowest id."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        if t.get("id") is None:
            continue
        img = str(((t.get("data") or {}).get("image")) or "").strip()
        if not img:
            continue
        groups.setdefault(img, []).append(t)
    out = []
    for grp in groups.values():
        if len(grp) < 2:
            continue
        grp_sorted = sorted(grp, key=lambda t: (-_ann_count(t), t.get("id", 0)))
        out.append((grp_sorted[0], grp_sorted[1:]))
    return out


def _merge_group(keeper: Dict[str, Any], dups: List[Dict[str, Any]], execute: bool) -> int:
    """Copy any annotation on a duplicate that the keeper doesn't already have
    onto the keeper (dedup by normalized result). Returns count copied (or that
    WOULD be copied in dry-run)."""
    kdetail = ls.get_task(keeper["id"]) or {}
    seen = {normalize_result(a.get("result")) for a in (kdetail.get("annotations") or [])}
    copied = 0
    for d in dups:
        ddetail = ls.get_task(d["id"]) or {}
        for a in (ddetail.get("annotations") or []):
            key = normalize_result(a.get("result"))
            if key in seen:
                continue  # identical label already on keeper
            seen.add(key)
            copied += 1
            if execute:
                ls.create_annotation(
                    keeper["id"], a.get("result") or [],
                    was_cancelled=bool(a.get("was_cancelled")),
                    ground_truth=bool(a.get("ground_truth")),
                )
    return copied


def run(project_ids: List[int], execute: bool, include_annotated: bool, merge: bool) -> int:
    total_deleted = total_failed = total_merged = 0
    for pid in project_ids:
        tasks = ls.get_project_tasks(pid)
        if not tasks:
            print(f"project {pid}: no tasks (or LS unreachable) — skipping")
            continue
        keep, delete_safe, delete_annotated = plan_dedupe(tasks)
        distinct_imgs = len(set(
            str((t.get("data") or {}).get("image") or "") for t in tasks
            if str((t.get("data") or {}).get("image") or "").strip()
        ))
        print(
            f"project {pid}: tasks={len(tasks)} distinct_images={distinct_imgs} keep={len(keep)} "
            f"| unannotated-dupes={len(delete_safe)} annotated-dupes={len(delete_annotated)}"
        )

        if merge:
            # MERGE: preserve all labels — copy each duplicate's unique annotations
            # onto the keeper, THEN delete every duplicate (safe + annotated).
            groups = build_groups(tasks)
            copied = 0
            for keeper, dups in groups:
                copied += _merge_group(keeper, dups, execute)
            total_merged += copied
            delete = delete_safe + delete_annotated
            print(f"  MERGE: {'copied' if execute else 'would copy'} {copied} unique annotation(s) "
                  f"to keepers; then delete all {len(delete)} duplicates.")
        else:
            # SAFE: only unannotated duplicates; annotated held back unless opted in.
            delete = delete_safe + (delete_annotated if include_annotated else [])
            if delete_annotated:
                verb = "WILL DELETE (lose labels)" if include_annotated else "HELD BACK (kept safe)"
                print(f"  {len(delete_annotated)} annotated duplicate(s): {verb}.")
            print(f"  planned deletions this run: {len(delete)}")

        if not execute:
            print(f"  DRY-RUN: pass --execute to apply.")
            continue
        proj_deleted = proj_failed = 0
        for i, tid in enumerate(delete, 1):
            if ls.delete_task(tid):
                proj_deleted += 1
            else:
                proj_failed += 1
            if i % 50 == 0:
                print(f"  ...processed {i}/{len(delete)}")
        total_deleted += proj_deleted
        total_failed += proj_failed
        print(f"  done project {pid}: deleted={proj_deleted} failed={proj_failed}")
    print(f"\nSummary: merged_annotations={total_merged} deleted={total_deleted} "
          f"failed={total_failed} mode={'EXECUTE' if execute else 'DRY-RUN'}")
    return 0 if total_failed == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", type=int, nargs="+", required=True,
                   help="LS project id(s) to dedupe")
    p.add_argument("--execute", action="store_true",
                   help="actually delete (default is dry-run)")
    p.add_argument("--include-annotated", action="store_true",
                   help="ALSO delete annotated duplicates (loses labeling work on the "
                        "redundant copy). Default keeps every annotated task.")
    p.add_argument("--merge", action="store_true",
                   help="MERGE then delete: copy each duplicate's unique annotations onto "
                        "the keeper (no label loss), then delete ALL duplicates.")
    args = p.parse_args()
    return run(args.project, args.execute, args.include_annotated, args.merge)


if __name__ == "__main__":
    sys.exit(main())
