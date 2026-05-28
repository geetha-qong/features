#!/usr/bin/env python3
"""Backfill canonical.json for existing jobs in job_outputs/.

Walks job_outputs/ and writes canonical.json next to each valve_list.csv
that doesn't already have one. Idempotent by default; pass --force to
overwrite existing canonical.json files.

Usage:
    python3 -m webapp.deliverables.backfill_canonical              # idempotent
    python3 -m webapp.deliverables.backfill_canonical --force      # overwrite
    python3 -m webapp.deliverables.backfill_canonical --root job_outputs/12  # subset
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from webapp.deliverables.pipeline_emitter import (
    EmitResult,
    write_canonical_for_job,
)


@dataclass
class DiscoveredJob:
    job_dir: Path
    job_id: int  # parsed from job_dir.name


@dataclass
class BackfillResult:
    job_id: int
    job_dir: Path
    canonical_path: Path
    skipped: bool
    error: Optional[str] = None


def discover_jobs(root: Path) -> Iterator[DiscoveredJob]:
    """Yield every job directory that has valve_list.csv.

    Supports both legacy flat (job_outputs/{job_id}/) and org-scoped
    (job_outputs/{org_id}/{job_id}/) layouts.
    """
    if not root.exists():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # Case A: child is a job dir (legacy)
        if (child / "valve_list.csv").exists():
            try:
                job_id = int(child.name)
            except ValueError:
                continue
            yield DiscoveredJob(job_dir=child, job_id=job_id)
            continue
        # Case B: child is an org dir containing job subdirs
        for grandchild in sorted(child.iterdir()):
            if not grandchild.is_dir():
                continue
            if (grandchild / "valve_list.csv").exists():
                try:
                    job_id = int(grandchild.name)
                except ValueError:
                    continue
                yield DiscoveredJob(job_dir=grandchild, job_id=job_id)


def backfill_all(root: Path, force: bool = False) -> List[BackfillResult]:
    results: List[BackfillResult] = []
    for job in discover_jobs(root):
        canonical_path = job.job_dir / "canonical.json"
        if canonical_path.exists() and not force:
            results.append(BackfillResult(
                job_id=job.job_id,
                job_dir=job.job_dir,
                canonical_path=canonical_path,
                skipped=True,
            ))
            continue
        try:
            emit: EmitResult = write_canonical_for_job(
                job_dir=job.job_dir, job_id=job.job_id
            )
            results.append(BackfillResult(
                job_id=job.job_id,
                job_dir=job.job_dir,
                canonical_path=emit.canonical_path,
                skipped=False,
            ))
        except Exception as e:
            results.append(BackfillResult(
                job_id=job.job_id,
                job_dir=job.job_dir,
                canonical_path=canonical_path,
                skipped=False,
                error=str(e),
            ))
    return results


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="job_outputs",
                   help="Job outputs root (default: job_outputs)")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing canonical.json")
    args = p.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"job_outputs root not found: {root}", file=sys.stderr)
        return 1

    results = backfill_all(root, force=args.force)
    written = sum(1 for r in results if not r.skipped and not r.error)
    skipped = sum(1 for r in results if r.skipped)
    errors = [r for r in results if r.error]

    print(f"Backfill complete: {written} written, {skipped} skipped (already had canonical.json), {len(errors)} errors")
    for r in errors:
        print(f"  ERROR job {r.job_id} ({r.job_dir}): {r.error}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
