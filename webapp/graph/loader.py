"""I/O boundary — assemble a per-job graph-extraction input object.

This is the only module in the package that touches the filesystem. It reads:
  - the full-page image(s) (``page_{p}_full.png``),
  - tile-grid metadata (computed from full-page dimensions; 3×3 / 20% overlap),
  - canonical entities (``canonical.json``),
  - YOLO detections (passed in as a parameter — NOT read from the DB here, so the
    package stays importable without SQLAlchemy).

Tile geometry MUST stay in sync with ``pdf_to_tiles.py`` and
``webapp/frontend/src/studio/PidCanvas.tsx:computeTileOffsets`` (FEATURES #38).
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

import numpy as np

# ── Tile geometry — mirrors pdf_to_tiles.pdf_to_tiles defaults ────────────────
# 3×3 grid, 20% overlap. pdf_to_tiles uses int(tile_w * overlap_pct) (truncation
# toward zero == floor for positive values), matching PidCanvas Math.floor.
GRID_ROWS = 3
GRID_COLS = 3
OVERLAP_PCT = 0.20


class TileBox(NamedTuple):
    x0: int
    y0: int
    x1: int
    y1: int


def compute_tile_offsets(width: int, height: int, page_index: int = 0) -> Dict[str, TileBox]:
    """Per-tile (x0,y0,x1,y1) page-pixel offsets. Mirrors computeTileOffsets/pdf_to_tiles.

    Keyed by tile filename ``tile_p{page}_r{r}_c{c}.png``.
    """
    tile_w = math.ceil(width / GRID_COLS)
    tile_h = math.ceil(height / GRID_ROWS)
    overlap_x = int(tile_w * OVERLAP_PCT)
    overlap_y = int(tile_h * OVERLAP_PCT)
    out: Dict[str, TileBox] = {}
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            x0 = max(0, c * tile_w - overlap_x)
            y0 = max(0, r * tile_h - overlap_y)
            x1 = min(width, (c + 1) * tile_w + overlap_x)
            y1 = min(height, (r + 1) * tile_h + overlap_y)
            out[f"tile_p{page_index}_r{r}_c{c}.png"] = TileBox(x0, y0, x1, y1)
    return out


def to_page_pixel_detections(
    detections: Sequence[Dict[str, Any]], tile_offsets: Dict[str, TileBox]
) -> List[Dict[str, Any]]:
    """Translate tile-local detection bboxes → page-pixel using tile origins.

    ``Job.gpu_detections`` (webapp/inference.py) stores each bbox in *tile-local*
    pixel coords plus a ``tile`` filename. The graph data model is page-pixel, so
    the glue passes ``tile_local_detections=True`` and we offset each bbox by its
    tile's page-pixel origin (mirrors what PidCanvas does client-side).

    Adds page-pixel ``bbox`` and preserves the original tile-local box as
    ``bbox_tile``. Detections whose ``tile`` is unknown to ``tile_offsets`` (or
    that lack a 4-tuple bbox) pass through unchanged — already-page-pixel inputs
    (e.g. synthetic test fixtures with no matching tile) are therefore untouched.
    """
    out: List[Dict[str, Any]] = []
    for d in detections:
        tile = d.get("tile")
        bbox = d.get("bbox")
        box = tile_offsets.get(tile) if tile else None
        if box is None or not bbox or len(bbox) < 4:
            out.append(d)
            continue
        nd = dict(d)
        nd["bbox_tile"] = list(bbox)
        nd["bbox"] = [
            box.x0 + bbox[0], box.y0 + bbox[1],
            box.x0 + bbox[2], box.y0 + bbox[3],
        ]
        out.append(nd)
    return out


class JobInput(NamedTuple):
    job_dir: str
    page: int
    full_page_path: Optional[str]
    full_page_image: Optional[np.ndarray]   # grayscale page-pixel, may be None
    width: int
    height: int
    tile_offsets: Dict[str, TileBox]
    canonical_entities: List[Dict[str, Any]]
    detections: List[Dict[str, Any]]


def _find_full_page_path(job_dir: str, page: int) -> Optional[str]:
    """Locate the full-page PNG. Tries tmp/ and job_dir root, both naming forms."""
    candidates = [
        os.path.join(job_dir, "tmp", f"page_{page - 1}_full.png"),
        os.path.join(job_dir, f"page_{page - 1}_full.png"),
        os.path.join(job_dir, "tmp", f"page_{page}_full.png"),
        os.path.join(job_dir, f"page_{page}_full.png"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _load_canonical_entities(job_dir: str) -> List[Dict[str, Any]]:
    """Parse ``canonical.json`` → list of entity dicts. Missing/corrupt → []."""
    path = os.path.join(job_dir, "canonical.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        ents = data.get("entities", [])
    elif isinstance(data, list):
        ents = data
    else:
        ents = []
    return [e for e in ents if isinstance(e, dict)]


def _load_grayscale(path: Optional[str]) -> Optional[np.ndarray]:
    if not path:
        return None
    try:
        import cv2

        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        return img
    except Exception:
        return None


def load_job_input(
    job_dir: str,
    detections: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    page: int = 1,
    tile_local_detections: bool = False,
) -> JobInput:
    """Assemble the per-job input object.

    ``detections`` are supplied by the caller (the webapp glue passes
    ``Job.gpu_detections`` parsed to a list). Missing detections → []. Missing
    canonical.json → entities=[] (the pipeline layer enforces the 409 contract).
    The full-page image may be None if not on disk — the tracer degrades to no
    segments and the LLM fallback (if it has the path) can still run.

    ``tile_local_detections``: when True, the detection bboxes are tile-local
    (as ``Job.gpu_detections`` stores them) and are translated to page-pixel via
    the computed tile offsets. Requires the full-page image (for accurate page
    dimensions); without it the translation is skipped and a degraded result is
    returned. Synthetic/page-pixel inputs leave this False.
    """
    det_list: List[Dict[str, Any]] = list(detections) if detections else []

    canonical_entities = _load_canonical_entities(job_dir)
    full_page_path = _find_full_page_path(job_dir, page)
    full_page_image = _load_grayscale(full_page_path)

    if full_page_image is not None:
        height, width = full_page_image.shape[:2]
    elif tile_local_detections:
        # Can't reliably size the page from tile-local extents; skip sizing.
        width = height = 0
    else:
        # Fall back to inferring page size from detection bbox extents so tile
        # geometry + masks still work when the PNG isn't present.
        max_x = max((d.get("bbox", [0, 0, 0, 0])[2] for d in det_list if d.get("bbox")), default=0)
        max_y = max((d.get("bbox", [0, 0, 0, 0])[3] for d in det_list if d.get("bbox")), default=0)
        width = int(math.ceil(max_x)) or 0
        height = int(math.ceil(max_y)) or 0

    tile_offsets = compute_tile_offsets(width, height, page_index=page - 1) if width and height else {}

    if tile_local_detections and tile_offsets:
        det_list = to_page_pixel_detections(det_list, tile_offsets)

    return JobInput(
        job_dir=job_dir,
        page=page,
        full_page_path=full_page_path,
        full_page_image=full_page_image,
        width=width,
        height=height,
        tile_offsets=tile_offsets,
        canonical_entities=canonical_entities,
        detections=det_list,
    )


def build_bbox_mask(detections: Sequence[Dict[str, Any]], width: int, height: int) -> np.ndarray:
    """Boolean mask (H×W) True inside every detection bbox (page-pixel).

    Used by the tracer to blank out symbol interiors before skeletonisation.
    """
    mask = np.zeros((max(1, height), max(1, width)), dtype=bool)
    if not width or not height:
        return mask
    for d in detections:
        bbox = d.get("bbox") or d.get("bbox_tile")
        if not bbox or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
        x1, x2 = sorted((int(x1), int(x2)))
        y1, y2 = sorted((int(y1), int(y2)))
        x1 = max(0, min(x1, width))
        x2 = max(0, min(x2, width))
        y1 = max(0, min(y1, height))
        y2 = max(0, min(y2, height))
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = True
    return mask
