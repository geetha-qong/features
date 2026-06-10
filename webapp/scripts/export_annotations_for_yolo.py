"""Export user_annotations rows as YOLO-format training labels.

For each `user_added` / `user_confirmed` row we:
  - map (entity_class, sub_class) -> the v1-10 YOLO class index
    (CLASS_NAMES in webapp.inference). Unmappable rows are SKIPPED.
  - translate the page-pixel bbox into the FIRST tile whose bounds
    contain the bbox center (the same 3×3 grid / 20% overlap math as
    `pdf_to_tiles.py`).
  - emit a YOLO line `<class_id> <cx> <cy> <w> <h>` (tile-local,
    normalized [0,1]) appended to
    `<out>/{job_id}/{tile_filename}.txt` (idempotent on the 5-tuple).

Usage:
    python -m webapp.scripts.export_annotations_for_yolo \
        [--job-id N] [--since YYYY-MM-DD] \
        [--out PATH] [--dry-run]

Pure read against the DB + filesystem; safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image

from webapp import models
from webapp.database import SessionLocal
from webapp.inference import CLASS_NAMES


# Default output directory mirrors the v1-10 dataset layout. Run from project
# root so the relative path resolves to `datasets/pid_valves/labels/`.
DEFAULT_OUT = Path("datasets/pid_valves/labels")

GRID_ROWS = 3
GRID_COLS = 3
OVERLAP_PCT = 0.20


# ── Class mapping ────────────────────────────────────────────────────────────


def _class_index() -> Dict[str, int]:
    """Reverse map: YOLO class name -> class index."""
    return {name: i for i, name in enumerate(CLASS_NAMES)}


def map_to_class_id(entity_class: str, sub_class: Optional[str]) -> Optional[int]:
    """Return the YOLO class index for an annotation, or None if unmappable.

    Rules:
      - For valves the canonical class name pattern is ``valve_<lower(sub)>``.
      - Instruments fold into ``inst_field`` unless a more specific match
        exists in CLASS_NAMES (e.g. ``inst_bpcs``, ``inst_sis``).
      - Equipment maps via a tiny dictionary to ``Motor`` / ``Pump/Dwg Pump``;
        anything else returns None.
    """
    idx = _class_index()
    if not entity_class:
        return None

    ec = entity_class.lower()
    sc = (sub_class or "").strip()

    if ec == "valve":
        if not sc:
            return None
        key = f"valve_{sc.lower()}"
        return idx.get(key)

    if ec == "instrument":
        # Try a specific match first (e.g. "bpcs" -> "inst_bpcs"), then fall
        # back to the generic field bubble. If nothing maps, skip.
        if sc:
            specific = f"inst_{sc.lower()}"
            if specific in idx:
                return idx[specific]
        return idx.get("inst_field")

    if ec == "equipment":
        equip_map = {
            "motor": "Motor",
            "pump": "Pump/Dwg Pump",
        }
        target = equip_map.get(sc.lower()) if sc else None
        return idx.get(target) if target else None

    return None


# ── Tile geometry — mirror of pdf_to_tiles.pdf_to_tiles() ─────────────────────


def compute_tile_bounds(
    page_w: int,
    page_h: int,
    grid_rows: int = GRID_ROWS,
    grid_cols: int = GRID_COLS,
    overlap_pct: float = OVERLAP_PCT,
) -> List[Dict[str, int]]:
    """Return the (x0,y0,x1,y1) tile bounds for the 3×3 / 20% overlap grid.

    Matches `pdf_to_tiles.pdf_to_tiles` exactly. The first tile that contains
    the bbox center wins (deterministic row-major iteration).
    """
    tile_w = math.ceil(page_w / grid_cols)
    tile_h = math.ceil(page_h / grid_rows)
    overlap_x = int(tile_w * overlap_pct)
    overlap_y = int(tile_h * overlap_pct)
    out: List[Dict[str, int]] = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            x0 = max(0, c * tile_w - overlap_x)
            y0 = max(0, r * tile_h - overlap_y)
            x1 = min(page_w, (c + 1) * tile_w + overlap_x)
            y1 = min(page_h, (r + 1) * tile_h + overlap_y)
            out.append({"row": r, "col": c, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return out


def find_owning_tile(
    bbox: List[float],
    tiles: List[Dict[str, int]],
) -> Optional[Dict[str, int]]:
    """Return the first tile whose bounds contain the bbox center."""
    if not bbox or len(bbox) < 4:
        return None
    cx_pg = (float(bbox[0]) + float(bbox[2])) / 2.0
    cy_pg = (float(bbox[1]) + float(bbox[3])) / 2.0
    for t in tiles:
        if t["x0"] <= cx_pg <= t["x1"] and t["y0"] <= cy_pg <= t["y1"]:
            return t
    return None


def bbox_to_yolo(
    bbox: List[float],
    tile: Dict[str, int],
) -> Tuple[float, float, float, float]:
    """Page-pixel bbox -> normalized YOLO (cx, cy, w, h) in tile-local coords."""
    tw = max(1, tile["x1"] - tile["x0"])
    th = max(1, tile["y1"] - tile["y0"])
    x0 = float(bbox[0]) - tile["x0"]
    y0 = float(bbox[1]) - tile["y0"]
    x1 = float(bbox[2]) - tile["x0"]
    y1 = float(bbox[3]) - tile["y0"]
    # Clamp to tile interior — annotations near the edge may extend into the
    # adjacent tile via the 20% overlap; we keep them assigned to the
    # center-owning tile and clamp the rect so YOLO targets stay in [0,1].
    x0 = max(0.0, min(float(tw), x0))
    y0 = max(0.0, min(float(tw), y0))
    x1 = max(0.0, min(float(tw), x1))
    y1 = max(0.0, min(float(th), y1))
    cx = ((x0 + x1) / 2.0) / tw
    cy = ((y0 + y1) / 2.0) / th
    w = abs(x1 - x0) / tw
    h = abs(y1 - y0) / th
    return cx, cy, w, h


# ── Page-image lookup ────────────────────────────────────────────────────────


def page_full_path_for_job(job: models.Job, sheet_number: int) -> Optional[Path]:
    """Return the page-full PNG for a sheet, if it exists on disk."""
    if not job.output_csv_path:
        return None
    job_dir = Path(job.output_csv_path).parent
    candidate = job_dir / "tmp" / f"page_{sheet_number - 1}_full.png"
    if candidate.exists():
        return candidate
    # Fallback: some legacy jobs used 1-indexed naming.
    legacy = job_dir / "tmp" / f"page_{sheet_number}_full.png"
    return legacy if legacy.exists() else None


def page_dimensions(page_path: Path) -> Tuple[int, int]:
    with Image.open(page_path) as im:
        return im.size  # (W, H)


def tile_filename(sheet_number: int, row: int, col: int) -> str:
    """Tile naming matches `pdf_to_tiles.pdf_to_tiles` (0-indexed page)."""
    return f"tile_p{sheet_number - 1}_r{row}_c{col}.png"


# ── DB iteration ─────────────────────────────────────────────────────────────


def _eligible_annotations(
    db,
    job_id: Optional[int],
    since: Optional[datetime],
):
    q = db.query(models.UserAnnotation).filter(
        models.UserAnnotation.status.in_(("user_added", "user_confirmed"))
    )
    if job_id is not None:
        q = q.filter(models.UserAnnotation.job_id == job_id)
    if since is not None:
        q = q.filter(models.UserAnnotation.created_at >= since)
    return q.order_by(models.UserAnnotation.job_id, models.UserAnnotation.id).all()


# ── Idempotent writer ────────────────────────────────────────────────────────


def _existing_lines(label_path: Path) -> set:
    if not label_path.exists():
        return set()
    out: set = set()
    for raw in label_path.read_text(encoding="utf-8").splitlines():
        parts = raw.strip().split()
        if len(parts) != 5:
            continue
        try:
            cls = int(parts[0])
            fl = tuple(round(float(p), 6) for p in parts[1:])
        except ValueError:
            continue
        out.add((cls, *fl))
    return out


def _format_line(class_id: int, cx: float, cy: float, w: float, h: float) -> str:
    return f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


# ── Main ─────────────────────────────────────────────────────────────────────


def run(
    *,
    job_id: Optional[int],
    since: Optional[datetime],
    out_dir: Path,
    dry_run: bool,
) -> Tuple[int, int, int]:
    """Returns (exported, skipped_unmappable, jobs_touched)."""
    db = SessionLocal()
    try:
        rows = _eligible_annotations(db, job_id=job_id, since=since)

        # Cache per-job tile geometry — page dims only need to be read once
        # per (job, sheet) pair.
        page_dims_cache: Dict[Tuple[int, int], Optional[Tuple[int, int]]] = {}
        tile_bounds_cache: Dict[Tuple[int, int], List[Dict[str, int]]] = {}
        job_cache: Dict[int, Optional[models.Job]] = {}

        exported = 0
        skipped_unmappable = 0
        jobs_touched: set = set()
        # accumulate writes so we hit disk once per label file
        pending: Dict[Path, List[Tuple[int, float, float, float, float]]] = (
            defaultdict(list)
        )

        for row in rows:
            class_id = map_to_class_id(row.entity_class, row.sub_class)
            if class_id is None:
                skipped_unmappable += 1
                print(
                    f"  skip annotation id={row.id} job={row.job_id} "
                    f"class={row.entity_class!r} sub={row.sub_class!r} (unmappable)"
                )
                continue

            job = job_cache.get(row.job_id)
            if job is None and row.job_id not in job_cache:
                job = (
                    db.query(models.Job)
                    .filter(models.Job.id == row.job_id)
                    .first()
                )
                job_cache[row.job_id] = job
            if job is None:
                skipped_unmappable += 1
                print(f"  skip annotation id={row.id}: job {row.job_id} not found")
                continue

            page_key = (row.job_id, row.sheet_number)
            if page_key not in page_dims_cache:
                page_path = page_full_path_for_job(job, row.sheet_number)
                if page_path is None:
                    page_dims_cache[page_key] = None
                else:
                    try:
                        page_dims_cache[page_key] = page_dimensions(page_path)
                    except Exception as e:
                        print(
                            f"  skip annotation id={row.id}: "
                            f"page-full read failed: {e}"
                        )
                        page_dims_cache[page_key] = None
            dims = page_dims_cache[page_key]
            if dims is None:
                skipped_unmappable += 1
                continue
            W, H = dims
            if page_key not in tile_bounds_cache:
                tile_bounds_cache[page_key] = compute_tile_bounds(W, H)
            tiles = tile_bounds_cache[page_key]

            tile = find_owning_tile(row.bbox, tiles)
            if tile is None:
                skipped_unmappable += 1
                continue
            cx, cy, w, h = bbox_to_yolo(row.bbox, tile)
            if w <= 0 or h <= 0:
                skipped_unmappable += 1
                continue

            label_path = (
                out_dir
                / str(row.job_id)
                / (tile_filename(row.sheet_number, tile["row"], tile["col"]) + ".txt")
            )
            pending[label_path].append((class_id, cx, cy, w, h))
            jobs_touched.add(row.job_id)
            exported += 1

        if dry_run:
            print()
            print(
                f"DRY RUN: would export {exported} annotations across "
                f"{len(jobs_touched)} jobs into {out_dir}"
            )
            print(f"DRY RUN: skipped {skipped_unmappable} unmappable rows")
            return exported, skipped_unmappable, len(jobs_touched)

        # Idempotent write — dedupe vs existing lines + dedupe within payload.
        actually_written = 0
        for label_path, lines in pending.items():
            label_path.parent.mkdir(parents=True, exist_ok=True)
            existing = _existing_lines(label_path)
            new_seen: set = set()
            to_append: List[str] = []
            for cls, cx, cy, w, h in lines:
                key = (cls, round(cx, 6), round(cy, 6), round(w, 6), round(h, 6))
                if key in existing or key in new_seen:
                    continue
                new_seen.add(key)
                to_append.append(_format_line(cls, cx, cy, w, h))
            if not to_append:
                continue
            with label_path.open("a", encoding="utf-8") as fh:
                if label_path.stat().st_size > 0:
                    fh.write("\n")
                fh.write("\n".join(to_append))
            actually_written += len(to_append)

        print()
        print(
            f"Exported: {actually_written} annotations across "
            f"{len(jobs_touched)} jobs into {out_dir}"
        )
        print(f"Skipped: {skipped_unmappable} (unmappable sub_class)")
        return actually_written, skipped_unmappable, len(jobs_touched)
    finally:
        db.close()


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--job-id", type=int, default=None,
                   help="restrict to a single job id")
    p.add_argument("--since", type=str, default=None,
                   help="only annotations created on/after this YYYY-MM-DD")
    p.add_argument("--out", type=str, default=str(DEFAULT_OUT),
                   help=f"output directory (default {DEFAULT_OUT})")
    p.add_argument("--dry-run", action="store_true",
                   help="report counts; write nothing")
    args = p.parse_args()

    out_dir = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    since = _parse_since(args.since)
    run(
        job_id=args.job_id,
        since=since,
        out_dir=out_dir,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
