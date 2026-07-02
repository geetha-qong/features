"""
Tile Analysis API Router — line overlay endpoints.

Provides:
  GET  /api/v1/jobs/{job_id}/tiles/{tile_id}/summary     - topology lines for a tile
  GET  /api/v1/jobs/{job_id}/tiles/{tile_id}/annotations - saved manual annotations
  POST /api/v1/jobs/{job_id}/tiles/{tile_id}/annotations - save manual annotations

topology.json is written by webapp/line_detector.py after each pipeline run.
Schema: {"lines": [{"startX", "startY", "endX", "endY"}, ...], "drawing_width", "drawing_height"}
"""

import json
import logging
import math
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image as _PILImage
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.config import get_job_dir
from webapp.database import get_db

_PILImage.MAX_IMAGE_PIXELS = None  # P&IDs at 4× zoom exceed the 89 M-px default

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _can_access_job(job: models.Job, user: models.User) -> bool:
    return job.user_id == user.id or user.role in ("super_admin", "annotator")


def _compute_tile_bbox(
    job: models.Job,
    page: int,
    row: int,
    col: int,
    grid_rows: int = 3,
    grid_cols: int = 3,
    overlap_pct: float = 0.20,
) -> Optional[tuple]:
    """Return (x0, y0, x1, y1) in full-page pixel coords for a tile.

    Mirrors the formula in pdf_to_tiles.py exactly — reads the stored
    page_{page}_full.png to get actual dimensions rather than guessing.
    """
    job_dir = get_job_dir(job)
    page_img_path = job_dir / "tmp" / f"page_{page}_full.png"
    if not page_img_path.exists():
        return None
    try:
        with _PILImage.open(page_img_path) as img:
            W, H = img.size
        tile_w = math.ceil(W / grid_cols)
        tile_h = math.ceil(H / grid_rows)
        overlap_x = int(tile_w * overlap_pct)
        overlap_y = int(tile_h * overlap_pct)
        x0 = max(0, col * tile_w - overlap_x)
        y0 = max(0, row * tile_h - overlap_y)
        x1 = min(W, (col + 1) * tile_w + overlap_x)
        y1 = min(H, (row + 1) * tile_h + overlap_y)
        return (x0, y0, x1, y1)
    except Exception as exc:
        logger.error("_compute_tile_bbox failed page=%d r=%d c=%d: %s", page, row, col, exc)
        return None


def _liang_barsky_clip(
    px1: float, py1: float, px2: float, py2: float,
    bx1: float, by1: float, bx2: float, by2: float,
) -> Optional[tuple]:
    """Liang-Barsky segment-to-bbox clip.

    Returns (cx1, cy1, cx2, cy2) of the portion inside the bbox, or None if
    the segment misses it entirely.  Handles segments crossing the bbox with
    neither endpoint inside.
    """
    dx, dy = px2 - px1, py2 - py1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, px1 - bx1), (dx, bx2 - px1), (-dy, py1 - by1), (dy, by2 - py1)):
        if abs(p) < 1e-9:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    if t0 > t1:
        return None
    return (px1 + t0 * dx, py1 + t0 * dy, px1 + t1 * dx, py1 + t1 * dy)


def _topology_lines_for_tile(job: models.Job, bbox: tuple) -> list:
    """Extract line segments from topology.json that fall within tile bbox.

    Coordinates are returned in tile-local pixels (origin at bbox top-left).
    Uses Liang-Barsky clipping so segments crossing a tile boundary are still
    included (clipped to tile edge), eliminating visible gaps.
    """
    x1, y1, x2, y2 = bbox
    job_dir = get_job_dir(job)
    topo_path = job_dir / "graph_outputs" / "topology.json"
    if not topo_path.exists():
        return []
    try:
        with topo_path.open() as f:
            topology = json.load(f)
        lines_raw = topology.get("lines", [])
        lines = []
        seen: set = set()
        for seg_idx, seg in enumerate(lines_raw):
            px1 = float(seg["startX"])
            py1 = float(seg["startY"])
            px2 = float(seg["endX"])
            py2 = float(seg["endY"])
            # Deduplicate reversed edges (HoughLinesP can return A→B and B→A)
            key = (min(px1, px2), min(py1, py2), max(px1, px2), max(py1, py2))
            if key in seen:
                continue
            seen.add(key)
            clipped = _liang_barsky_clip(px1, py1, px2, py2, x1, y1, x2, y2)
            if clipped is None:
                continue
            cx1, cy1, cx2, cy2 = clipped
            lines.append({
                "start_x": cx1 - x1,
                "start_y": cy1 - y1,
                "end_x":   cx2 - x1,
                "end_y":   cy2 - y1,
                "tag": f"topo_e{seg_idx}",
                "service": "",
                "has_flow": False,
                "flow_direction": "",
            })
        return lines
    except Exception as exc:
        logger.error("Failed to extract tile lines from topology.json: %s", exc)
        return []


def _yolo_equipment_for_tile(
    job: models.Job, bbox: tuple, page: int = 0, row: int = 0, col: int = 0
) -> list:
    """Return YOLO detections for this tile in tile-local pixel coordinates.

    Matches by tile_page/tile_row/tile_col identity (new-format inference.py output).
    Falls back to centroid-in-page-bbox check for legacy detections.
    """
    if not job.gpu_detections:
        return []
    try:
        parsed = json.loads(job.gpu_detections)
        gpu_dets = parsed if isinstance(parsed, list) else parsed.get("detections", [])
        equipment = []
        seen: set = set()
        px1, py1, px2, py2 = bbox

        for det in gpu_dets:
            dbbox = det.get("bbox", det.get("bbox_tile", []))
            if len(dbbox) < 4:
                continue

            det_page = det.get("tile_page")
            det_row = det.get("tile_row")
            det_col = det.get("tile_col")
            has_tile_id = det_page is not None and det_row is not None and det_col is not None

            if has_tile_id:
                if int(det_page) != page or int(det_row) != row or int(det_col) != col:
                    continue
                bx1, by1, bx2, by2 = [float(v) for v in dbbox[:4]]
            else:
                # Legacy: bbox is in page coords — check centroid inside tile
                bx1, by1, bx2, by2 = [float(v) for v in dbbox[:4]]
                cx = (bx1 + bx2) / 2
                cy = (by1 + by2) / 2
                if not (px1 <= cx <= px2 and py1 <= cy <= py2):
                    continue
                bx1, by1, bx2, by2 = bx1 - px1, by1 - py1, bx2 - px1, by2 - py1

            key = (round(bx1), round(by1), round(bx2), round(by2))
            if key in seen:
                continue
            seen.add(key)

            label = det.get("label") or det.get("yolo_class") or ""
            equipment.append({
                "label": label,
                "bbox": [bx1, by1, bx2, by2],
                "confidence": float(det.get("confidence") or det.get("yolo_conf") or 0),
            })
        return equipment
    except Exception as exc:
        logger.error("_yolo_equipment_for_tile failed: %s", exc)
        return []


def _clip_lines_around_bboxes(lines: list, equipment: list, margin: int = 12) -> list:
    """Remove portions of line segments that pass through symbol bboxes.

    Stops lines just before symbol edges so the overlay looks cleaner.
    """
    raw_bboxes = [e["bbox"] for e in equipment if e.get("bbox") and len(e["bbox"]) == 4]
    if not raw_bboxes:
        return lines

    expanded = [
        (bx1 - margin, by1 - margin, bx2 + margin, by2 + margin)
        for bx1, by1, bx2, by2 in raw_bboxes
    ]

    result = []
    for line in lines:
        sx1 = line.get("start_x", 0)
        sy1 = line.get("start_y", 0)
        sx2 = line.get("end_x", 0)
        sy2 = line.get("end_y", 0)
        sub_segs = _clip_segment_against_bboxes(sx1, sy1, sx2, sy2, expanded)
        for i, (nx1, ny1, nx2, ny2) in enumerate(sub_segs):
            tag = line.get("tag", "seg")
            result.append({
                **line,
                "tag": f"{tag}_{i}" if i else tag,
                "start_x": nx1, "start_y": ny1,
                "end_x": nx2, "end_y": ny2,
            })
    return result


def _clip_segment_against_bboxes(
    sx1: float, sy1: float, sx2: float, sy2: float, bboxes: list
) -> list:
    """Parametric clip: return sub-segments of (sx1,sy1)-(sx2,sy2) outside all bboxes."""
    dx, dy = sx2 - sx1, sy2 - sy1
    seg_len = math.sqrt(dx * dx + dy * dy)
    if seg_len < 2:
        return [(sx1, sy1, sx2, sy2)]

    intervals = [(0.0, 1.0)]
    for bx1, by1, bx2, by2 in bboxes:
        if not intervals:
            break
        new_intervals = []
        for (a, b) in intervals:
            t_in, t_out = 0.0, 1.0
            if abs(dx) > 1e-9:
                tx_lo = (bx1 - sx1) / dx
                tx_hi = (bx2 - sx1) / dx
                if tx_lo > tx_hi:
                    tx_lo, tx_hi = tx_hi, tx_lo
                t_in = max(t_in, tx_lo)
                t_out = min(t_out, tx_hi)
            elif not (bx1 <= sx1 <= bx2):
                new_intervals.append((a, b))
                continue
            if abs(dy) > 1e-9:
                ty_lo = (by1 - sy1) / dy
                ty_hi = (by2 - sy1) / dy
                if ty_lo > ty_hi:
                    ty_lo, ty_hi = ty_hi, ty_lo
                t_in = max(t_in, ty_lo)
                t_out = min(t_out, ty_hi)
            elif not (by1 <= sy1 <= by2):
                new_intervals.append((a, b))
                continue
            if t_in >= t_out:
                new_intervals.append((a, b))
                continue
            if b <= t_in or a >= t_out:
                new_intervals.append((a, b))
            else:
                if a < t_in:
                    new_intervals.append((a, t_in))
                if b > t_out:
                    new_intervals.append((t_out, b))
        intervals = new_intervals

    MIN_FRAC = 0.04
    result = []
    for (a, b) in intervals:
        if b - a > MIN_FRAC:
            result.append((sx1 + a * dx, sy1 + a * dy, sx1 + b * dx, sy1 + b * dy))
    return result


def _load_saved_annotations(job: models.Job, tile_id: str) -> dict:
    """Load manually-drawn annotations from disk (written by POST /annotations).

    tile_id must already be validated by the caller via _parse_tile_id().
    Path confinement is re-checked here as a defence-in-depth measure.
    """
    job_dir = get_job_dir(job)
    ann_dir = job_dir / "graph_outputs" / "annotations"
    ann_path = (ann_dir / f"{tile_id}.json").resolve()
    try:
        ann_path.relative_to(ann_dir.resolve())
    except ValueError:
        logger.warning("Path traversal attempt blocked for tile_id=%s", tile_id)
        return {"lines": [], "equipment": [], "connections": []}
    if not ann_path.exists():
        return {"lines": [], "equipment": [], "connections": []}
    try:
        with ann_path.open() as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Failed to load annotations for tile %s: %s", tile_id, exc)
        return {"lines": [], "equipment": [], "connections": []}


def _parse_tile_id(tile_id: str) -> Optional[tuple]:
    """Parse 'page_tilenum' → (sheet_number, tile_number) as ints."""
    m = re.match(r"^(\d+)_(\d+)$", tile_id)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/jobs/{job_id}/tiles/{tile_id}/summary")
async def get_tile_summary(
    job_id: int,
    tile_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return topology lines for a single tile in tile-local pixel coords.

    tile_id format: "{page}_{tile_number}" where tile_number = row*3 + col.
    Returns {"entities": {"lines": [...], "equipment": [], "junctions": []}}
    """
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")

    parsed = _parse_tile_id(tile_id)
    if parsed is None:
        raise HTTPException(status_code=400, detail="Invalid tile_id format (expect page_tilenum)")

    sheet_number, tile_number = parsed
    page = sheet_number
    row = tile_number // 3
    col = tile_number % 3

    tile_bbox = _compute_tile_bbox(job, page, row, col)

    entities: dict = {"lines": [], "equipment": [], "junctions": []}

    if tile_bbox:
        raw_lines = _topology_lines_for_tile(job, tile_bbox)
        equipment = _yolo_equipment_for_tile(job, tile_bbox, page, row, col)
        entities["lines"] = _clip_lines_around_bboxes(raw_lines, equipment)
        entities["equipment"] = equipment

    saved = _load_saved_annotations(job, tile_id)

    return JSONResponse({
        "tile_id": tile_id,
        "entities": entities,
        "saved_annotations": saved,
    })


@router.get("/api/v1/jobs/{job_id}/tiles/{tile_id}/annotations")
async def get_tile_annotations(
    job_id: int,
    tile_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return saved manual annotations for a tile."""
    if _parse_tile_id(tile_id) is None:
        raise HTTPException(status_code=400, detail="Invalid tile_id format (expect page_tilenum)")

    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse(_load_saved_annotations(job, tile_id))


@router.post("/api/v1/jobs/{job_id}/tiles/{tile_id}/annotations")
async def save_tile_annotations(
    job_id: int,
    tile_id: str,
    body: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save manual annotations for a tile (lines, equipment, connections)."""
    if _parse_tile_id(tile_id) is None:
        raise HTTPException(status_code=400, detail="Invalid tile_id format (expect page_tilenum)")

    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job or not _can_access_job(job, current_user):
        raise HTTPException(status_code=404, detail="Job not found")

    job_dir = get_job_dir(job)
    ann_dir = job_dir / "graph_outputs" / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    ann_path = (ann_dir / f"{tile_id}.json").resolve()
    try:
        ann_path.relative_to(ann_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tile_id")

    payload = {
        "lines": body.get("lines", []),
        "equipment": body.get("equipment", []),
        "connections": body.get("connections", []),
    }
    try:
        with ann_path.open("w") as f:
            json.dump(payload, f)
    except Exception as exc:
        logger.error("Failed to save annotations for tile %s: %s", tile_id, exc)
        raise HTTPException(status_code=500, detail="Failed to save annotations")

    return JSONResponse({"status": "ok", "tile_id": tile_id})
