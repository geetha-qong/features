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
import sys
from typing import Any, Dict, List, Tuple

from webapp import label_studio_client as ls


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


def run(project_ids: List[int], execute: bool, include_annotated: bool) -> int:
    total_deleted = total_failed = 0
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
        # SAFE by default: only unannotated duplicates. Annotated dupes carry
        # human labeling work — held back unless --include-annotated.
        delete = delete_safe + (delete_annotated if include_annotated else [])
        print(
            f"project {pid}: tasks={len(tasks)} distinct_images={distinct_imgs} keep={len(keep)} "
            f"| unannotated-dupes={len(delete_safe)} annotated-dupes={len(delete_annotated)}"
        )
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
    print(f"\nSummary: deleted={total_deleted} failed={total_failed} "
          f"mode={'EXECUTE' if execute else 'DRY-RUN'}")
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
    args = p.parse_args()
    return run(args.project, args.execute, args.include_annotated)


if __name__ == "__main__":
    sys.exit(main())
