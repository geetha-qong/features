"""Versioned training-set builder — the AGGREGATE step of the self-learning loop.

Unifies the existing exporters (`export_annotations_for_yolo`,
`export_graph_for_training`) into one dated dataset directory plus a manifest,
and additionally collects a tag-corrections JSONL from `EntityOverride` rows.

Design: docs/superpowers/specs/2026-06-17-self-learning-loop-design.md

Layout produced under ``<out_root>/<YYYY-MM-DD>/``::

    detection/                      # a self-contained, directly-trainable YOLO dataset
        images/train/<job_id>__<tile>.png
        images/val/<job_id>__<tile>.png
        labels/train/<job_id>__<tile>.txt
        labels/val/<job_id>__<tile>.txt
        data.yaml                   # path / train / val / nc / names
    graph/edges.jsonl               # graph-correction edges (via the graph exporter)
    tags/tag_corrections.jsonl      # EntityOverride tag edits (this script)
    manifest.json                   # counts + provenance

The YOLO exporter writes labels into a throw-away ``_staging`` dir; this script
then crops each tile image out of the job's page-full PNG, copies the matching
label, and splits train/val by a deterministic per-job hash (all tiles of one
drawing land on the same side — no train/val leakage). The ``_staging`` dir is
removed at the end, so ``detection/`` contains only ``images/``, ``labels/``,
and ``data.yaml``.

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
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from webapp import models
from webapp.database import SessionLocal
from webapp.datetime_utils import utc_iso
from webapp.model_version import current_model_trained_at, current_version
from webapp.taxonomy import class_names

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


# ── YOLO dataset assembly ─────────────────────────────────────────────────────

# tile_p{page_index}_r{row}_c{col}.png  (page_index = sheet_number - 1)
_TILE_RE = re.compile(r"^tile_p(\d+)_r(\d+)_c(\d+)\.png$")


def _split_for_job(job_id: int) -> str:
    """Deterministic per-job train/val assignment.

    All tiles of one drawing stay together (no leakage). ~10% of jobs land in
    val via a stable sha1(job_id) % 10 == 0 bucket.
    """
    h = int(hashlib.sha1(str(job_id).encode()).hexdigest(), 16)
    return "val" if h % 10 == 0 else "train"


def _parse_tile_name(tile_filename: str) -> Optional[Tuple[int, int, int]]:
    """``tile_p{N}_r{row}_c{col}.png`` -> (sheet_number, row, col), else None.

    sheet_number = N + 1 (the tile name carries the 0-indexed page).
    """
    m = _TILE_RE.match(tile_filename)
    if not m:
        return None
    page_index, row, col = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return page_index + 1, row, col


def _write_data_yaml(data_yaml_path: Path, detection_dir: Path) -> int:
    """Write detection/data.yaml. Returns nc (== len(class_names()))."""
    names = class_names()
    nc = len(names)
    lines: List[str] = []
    lines.append("path: {}".format(detection_dir.resolve()))
    lines.append("train: images/train")
    lines.append("val: images/val")
    lines.append("nc: {}".format(nc))
    lines.append("names:")
    for i, name in enumerate(names):
        lines.append("  {}: {}".format(i, name))
    data_yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return nc


def _build_yolo_dataset(
    *,
    staging_dir: Path,
    detection_dir: Path,
) -> dict:
    """Turn staged ``_staging/{job_id}/{tile}.txt`` labels into a trainable tree.

    For each staged label: crop the tile PNG out of the job's page-full image,
    save it under ``images/<split>/``, copy the label under ``labels/<split>/``.
    Missing/unreadable page images are logged + counted, never fatal.

    Returns counts dict consumed by the manifest builder.
    """
    # Lazy import — PIL + the exporter helpers are heavy; only needed for a
    # real build, and only when staging actually produced something.
    from PIL import Image

    # P&ID page-full PNGs are large (>140M px); trusted internal renders, so lift
    # PIL's decompression-bomb guard (hard-errors >178M px, losing a page's tiles).
    Image.MAX_IMAGE_PIXELS = None

    from webapp.scripts.export_annotations_for_yolo import (
        compute_tile_bounds,
        find_owning_tile,
        page_full_path_for_job,
        tile_filename as _tile_filename,
    )

    images_root = detection_dir / "images"
    labels_root = detection_dir / "labels"
    for split in ("train", "val"):
        (images_root / split).mkdir(parents=True, exist_ok=True)
        (labels_root / split).mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        job_cache: Dict[int, Optional[models.Job]] = {}
        # (job_id, sheet_number) -> (page_path or None, (W,H) or None, tiles)
        page_cache: Dict[Tuple[int, int], Tuple[Optional[Path],
                                                 Optional[Tuple[int, int]],
                                                 Optional[list]]] = {}

        images = 0
        skipped = 0
        train_tiles = 0
        val_tiles = 0
        train_jobs: set = set()
        val_jobs: set = set()

        # _staging/{job_id}/{tile}.txt
        for label_file in sorted(staging_dir.rglob("*.txt")):
            job_part = label_file.parent.name
            if not job_part.isdigit():
                continue
            job_id = int(job_part)
            tile_png = label_file.name[:-len(".txt")]  # strip trailing ".txt"
            parsed = _parse_tile_name(tile_png)
            if parsed is None:
                skipped += 1
                print("  skip {}: unparseable tile name".format(label_file))
                continue
            sheet_number, row, col = parsed

            job = job_cache.get(job_id)
            if job is None and job_id not in job_cache:
                job = (
                    db.query(models.Job)
                    .filter(models.Job.id == job_id)
                    .first()
                )
                job_cache[job_id] = job
            if job is None:
                skipped += 1
                print("  skip {}: job {} not found".format(label_file, job_id))
                continue

            page_key = (job_id, sheet_number)
            if page_key not in page_cache:
                page_path = page_full_path_for_job(job, sheet_number)
                if page_path is None:
                    page_cache[page_key] = (None, None, None)
                else:
                    try:
                        with Image.open(page_path) as im:
                            dims = im.size  # (W, H)
                        tiles = compute_tile_bounds(dims[0], dims[1])
                        page_cache[page_key] = (page_path, dims, tiles)
                    except Exception as e:  # pragma: no cover - IO dependent
                        print(
                            "  skip {}: page-full read failed: {}".format(
                                label_file, e
                            )
                        )
                        page_cache[page_key] = (None, None, None)
            page_path, dims, tiles = page_cache[page_key]
            if page_path is None or dims is None or tiles is None:
                skipped += 1
                print(
                    "  skip {}: page-full image missing for job {} sheet {}".format(
                        label_file, job_id, sheet_number
                    )
                )
                continue

            # Match by (row, col); guards against any geometry drift.
            tile = None
            for t in tiles:
                if t["row"] == row and t["col"] == col:
                    tile = t
                    break
            if tile is None:
                skipped += 1
                print(
                    "  skip {}: no tile r{} c{} in grid".format(
                        label_file, row, col
                    )
                )
                continue

            # Sanity: the expected tile name for this sheet/row/col.
            expected = _tile_filename(sheet_number, row, col)
            stem = "{}__{}".format(job_id, expected[:-len(".png")])

            split = _split_for_job(job_id)
            try:
                with Image.open(page_path) as im:
                    crop = im.crop(
                        (tile["x0"], tile["y0"], tile["x1"], tile["y1"])
                    )
                    crop.save(images_root / split / (stem + ".png"))
            except Exception as e:  # pragma: no cover - IO dependent
                skipped += 1
                print("  skip {}: crop failed: {}".format(label_file, e))
                continue

            shutil.copyfile(
                label_file, labels_root / split / (stem + ".txt")
            )
            images += 1
            if split == "val":
                val_tiles += 1
                val_jobs.add(job_id)
            else:
                train_tiles += 1
                train_jobs.add(job_id)

        return {
            "images": images,
            "skipped": skipped,
            "train_tiles": train_tiles,
            "val_tiles": val_tiles,
            "train_jobs": sorted(train_jobs),
            "val_jobs": sorted(val_jobs),
        }
    finally:
        db.close()


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
    det_images = 0
    det_train_tiles = 0
    det_val_tiles = 0
    det_train_jobs: List[int] = []
    det_val_jobs: List[int] = []
    det_classes = len(class_names())
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
            # Stage labels in a throw-away dir, then assemble the trainable tree.
            staging_dir = detection_dir / "_staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            seen_jobs: set = set()
            for jid in job_id_list:
                exported, skipped, _jobs_touched = _yolo_exporter.run(
                    job_id=jid,
                    since=since_dt,
                    out_dir=staging_dir,
                    dry_run=False,
                )
                det_annotations += exported
                det_skipped += skipped
            # Count staged label files + the jobs they belong to.
            for txt in staging_dir.rglob("*.txt"):
                det_label_files += 1
                seen_jobs.add(txt.parent.name)
            det_jobs = sorted(
                int(j) for j in seen_jobs if j.isdigit()
            )

            # Build images/<split> + labels/<split> by cropping page-full PNGs.
            ds = _build_yolo_dataset(
                staging_dir=staging_dir, detection_dir=detection_dir
            )
            det_images = ds["images"]
            det_skipped += ds["skipped"]
            det_train_tiles = ds["train_tiles"]
            det_val_tiles = ds["val_tiles"]
            det_train_jobs = ds["train_jobs"]
            det_val_jobs = ds["val_jobs"]

            # data.yaml + cleanup so detection/ holds only images/, labels/, yaml.
            det_classes = _write_data_yaml(
                detection_dir / "data.yaml", detection_dir
            )
            shutil.rmtree(staging_dir, ignore_errors=True)

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
            "images": det_images,
            "train_tiles": det_train_tiles,
            "val_tiles": det_val_tiles,
            "train_jobs": det_train_jobs,
            "val_jobs": det_val_jobs,
            "classes": det_classes,
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
    print(
        "  dataset:   {} tile images ({} train / {} val), "
        "{} train jobs / {} val jobs, {} classes".format(
            det_images, det_train_tiles, det_val_tiles,
            len(det_train_jobs), len(det_val_jobs), det_classes
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
