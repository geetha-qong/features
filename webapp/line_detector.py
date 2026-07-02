"""
Pipe/line segment detection for P&ID tiles.

Called from pipeline_runner.py after YOLO inference completes.
Produces a clean topology.json containing only detected line segment coordinates,
replacing the bloated graph_detection pipeline output (which stored raw skeleton
pixel arrays and could exceed 1 GB).

Pipeline per tile (all in tile-local pixel coordinates until Phase 7):
  Phase 1 — Suppress text strokes via proportional morphological kernels
  Phase 2 — Mask YOLO symbol bboxes so valve/instrument outlines are ignored
  Phase 3 — Drop noise blobs via connected-component size filtering
  Phase 4 — Skeletonize surviving strokes to single-pixel centerlines
  Phase 5 — HoughLinesP on skeleton
  Phase 6 — Filter tile-edge artifacts
  Phase 7 — Offset segments to full-drawing coordinates
  Phase 8 — Write clean topology.json (lines + drawing dimensions, no pixel data)

Output schema (topology.json):
  {
    "lines": [{"startX": int, "startY": int, "endX": int, "endY": int}, ...],
    "drawing_width": int,
    "drawing_height": int
  }
"""

import json
import logging
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ── HoughLinesP tuning ────────────────────────────────────────────────────────
# rho / theta: sub-pixel rho and fine angle resolution for clean skeleton lines.
# threshold: low because the skeleton is 1px wide (few voting points per segment).
# minLineLength / maxLineGap: start at 15 / 5 px — these are conservative values
# appropriate for the tile pixel resolution produced by pdf_to_tiles at zoom=4.
# At zoom=4, a single page of A1 paper renders to ~19000×13500 px; divided by 3
# with 20% overlap each tile is roughly 7500×5500 px.  15px minLength keeps short
# branch stubs; adjust upward (e.g. 40-60 px) if output is noisy with fragments.
_HOUGH_RHO = 0.2
_HOUGH_THETA_DIVS = 1080          # theta step = π / 1080 ≈ 0.17°
_HOUGH_THRESHOLD = 5
_HOUGH_MIN_LINE_LENGTH = 15       # px; scale proportionally for smaller tiles
_HOUGH_MAX_LINE_GAP = 5           # px

# Tile-edge artifact filter: drop segments whose BOTH endpoints are within this
# many pixels of a tile boundary edge (these are cut-artefacts, not real pipes).
_EDGE_MARGIN = 5


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_tile_bbox(
    page_img_path: Path,
    row: int,
    col: int,
    grid_rows: int = 3,
    grid_cols: int = 3,
    overlap_pct: float = 0.20,
) -> Optional[Tuple[int, int, int, int]]:
    """Return (x0, y0, x1, y1) of a tile in full-page pixel coordinates.

    Mirrors the exact formula in pdf_to_tiles.py so offsets are always consistent
    with the original tile crop.  Reads the stored full-page image to get actual
    page dimensions rather than guessing from tile index arithmetic.
    """
    try:
        with Image.open(page_img_path) as img:
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
        logger.error("_compute_tile_bbox failed for r%d_c%d: %s", row, col, exc)
        return None


def _binarize(gray: np.ndarray) -> Tuple[np.ndarray, int]:
    """OTSU binarization. Returns (binary, bg_val) where binary foreground = 255.

    Detects background colour from the histogram peak:
      light background (P&ID drawings are typically white) → THRESH_BINARY_INV
      dark background                                      → THRESH_BINARY
    """
    import cv2

    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    bg_peak = int(np.argmax(hist))
    is_light_bg = bg_peak > 127

    if is_light_bg:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        bg_val = 255
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bg_val = 0

    return binary, bg_val


def _suppress_text_strokes(
    binary: np.ndarray,
    gray: np.ndarray,
    bg_val: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Phase 1: erase compact character blobs, leaving continuous pipe strokes.

    Strategy:
      1. Extract horizontal continuous structures (pipe-length horizontal runs)
         using an opening kernel of width proportional to the tile.
      2. Extract vertical continuous structures similarly.
      3. Anything in the binary image NOT covered by either line mask is a
         character blob — paint it with the background colour in the grayscale.
      4. Re-binarize the cleaned grayscale.

    Kernel sizes are proportional to tile dimensions so that:
      - On a 7500 px wide tile (4× zoom), h_len ≈ 300 px — comfortably longer
        than any text character while shorter than most pipe runs.
      - On a smaller 1000 px tile, h_len ≈ 40 px (floor), still removes chars.
    Capped at 300 px so long kernels don't destroy short pipe stubs near bends.
    """
    import cv2

    H, W = binary.shape
    h_len = max(20, min(W // 25, 300))
    v_len = max(20, min(H // 25, 300))

    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))

    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    line_mask = cv2.bitwise_or(h_lines, v_lines)
    char_mask = cv2.bitwise_and(binary, cv2.bitwise_not(line_mask))

    clean_gray = gray.copy()
    clean_gray[char_mask > 0] = bg_val

    clean_binary, _ = _binarize(clean_gray)
    return clean_binary, clean_gray


def _mask_yolo_symbols(
    gray: np.ndarray,
    binary: np.ndarray,
    yolo_bboxes: List[List[float]],
    bg_val: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Phase 2: paint YOLO detection regions with background colour.

    Prevents valve/instrument symbol outlines from being detected as pipe
    segments.  Uses tile-local bbox coordinates (as stored by inference.py).
    """
    if not yolo_bboxes:
        return gray, binary

    import cv2

    masked_gray = gray.copy()
    tile_h, tile_w = gray.shape

    for bx1, by1, bx2, by2 in yolo_bboxes:
        x1i = max(0, int(bx1))
        y1i = max(0, int(by1))
        x2i = min(tile_w, int(bx2))
        y2i = min(tile_h, int(by2))
        masked_gray[y1i:y2i, x1i:x2i] = bg_val

    masked_binary, _ = _binarize(masked_gray)
    return masked_gray, masked_binary


def _drop_noise_blobs(binary: np.ndarray) -> np.ndarray:
    """Phase 3: remove small isolated components (character fragments, YOLO-mask
    edge artifacts, scan dust).

    A component is kept if: width ≥ min_dim OR height ≥ min_dim OR area ≥ min_area.
    Thresholds scale with tile size so a component that is "small" on a high-res
    tile is still filtered:
      reference size: 1000 px (medium tile)
      base thresholds: 40 px / 150 px² (task specification)
      at 5000 px tile: min_dim ≈ 200 px, min_area ≈ 3750 px²
    """
    import cv2

    H, W = binary.shape
    scale = min(W, H) / 1000.0

    min_dim = max(40, int(40 * scale))
    min_area = max(150, int(150 * scale * scale))

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)

    mask = np.zeros_like(binary)
    for i in range(1, num_labels):   # label 0 = background
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if w >= min_dim or h >= min_dim or area >= min_area:
            mask[labels == i] = 255

    return mask


def _skeletonize(binary: np.ndarray) -> np.ndarray:
    """Phase 4: iterative morphological thinning to single-pixel centerlines.

    Algorithm (Zhang-Suen style morphological skeleton):
      eroded  = erode(img, cross_kernel)
      temp    = img − dilate(eroded, cross_kernel)   # the boundary ring
      skeleton |= temp
      img = eroded
      repeat until img is empty

    Converges in O(stroke_thickness) iterations — for typical P&ID linework
    at 4× zoom (3–8 px strokes) this is fast.  A guard limit of 200 iterations
    prevents runaway loops on pathological input.
    """
    import cv2

    img = binary.copy()
    skeleton = np.zeros_like(img)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    max_iters = 200

    for _ in range(max_iters):
        eroded = cv2.erode(img, kernel)
        temp = cv2.subtract(img, cv2.dilate(eroded, kernel))
        skeleton = cv2.bitwise_or(skeleton, temp)
        img = eroded
        if cv2.countNonZero(img) == 0:
            break

    return skeleton


def _classify_dashed(
    lines: List[Tuple[int, int, int, int]],
    skeleton: np.ndarray,
) -> List[bool]:
    """Classify each segment as dashed (True) or solid (False).

    Dashed instrument/signal lines in P&IDs appear as many SHORT segments with
    regular gaps. Two signals:
      1. Length < SHORT_THRESH  → candidate dash stroke
      2. Skeleton density in the extended region < DENSITY_THRESH confirms it —
         a solid pipe skeleton stays dense past each endpoint; a dashed line has
         gaps (no skeleton pixels) between the dashes.
    """
    SHORT_THRESH = 50      # px; individual dashes at tile resolution
    DENSITY_THRESH = 0.40  # < 40% dark in extended scan → dashed
    EXTEND = 0.9           # sample 90% of segment length beyond each endpoint

    h, w = skeleton.shape
    result: List[bool] = []
    for x1, y1, x2, y2 in lines:
        length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if length < 1 or length >= SHORT_THRESH:
            result.append(False)
            continue
        dx = (x2 - x1) / length
        dy = (y2 - y1) / length
        ext_px = max(1, int(length * EXTEND))
        dark = total = 0
        for sign in (-1, 1):
            for k in range(1, ext_px + 1):
                px = int(round(x2 + sign * dx * k))
                py = int(round(y2 + sign * dy * k))
                if 0 <= px < w and 0 <= py < h:
                    total += 1
                    if skeleton[py, px] > 0:
                        dark += 1
        density = dark / total if total > 0 else 1.0
        result.append(density < DENSITY_THRESH)
    return result


def _detect_hough_lines(
    skeleton: np.ndarray,
) -> List[Tuple[int, int, int, int]]:
    """Phase 5: detect line segments on the skeleton via HoughLinesP.

    Returns list of (x1, y1, x2, y2) in tile-local pixels.
    """
    import cv2

    raw = cv2.HoughLinesP(
        skeleton,
        rho=_HOUGH_RHO,
        theta=np.pi / _HOUGH_THETA_DIVS,
        threshold=_HOUGH_THRESHOLD,
        minLineLength=_HOUGH_MIN_LINE_LENGTH,
        maxLineGap=_HOUGH_MAX_LINE_GAP,
    )
    if raw is None:
        return []
    return [(int(r[0][0]), int(r[0][1]), int(r[0][2]), int(r[0][3])) for r in raw]


def _filter_edge_artifacts(
    lines: List[Tuple[int, int, int, int]],
    tile_w: int,
    tile_h: int,
) -> List[Tuple[int, int, int, int]]:
    """Phase 6: remove segments whose both endpoints hug a tile boundary.

    A segment is considered a tile-edge artifact when BOTH its endpoints are
    within _EDGE_MARGIN pixels of the same tile boundary edge (left / right /
    top / bottom).  A genuine pipe that happens to run close to one edge will
    have at least one endpoint further in, so it is preserved.
    """
    m = _EDGE_MARGIN
    result = []
    for x1, y1, x2, y2 in lines:
        near_left   = x1 < m and x2 < m
        near_right  = x1 > tile_w - m and x2 > tile_w - m
        near_top    = y1 < m and y2 < m
        near_bottom = y1 > tile_h - m and y2 > tile_h - m
        if near_left or near_right or near_top or near_bottom:
            continue
        result.append((x1, y1, x2, y2))
    return result


_MERGE_ANGLE_TOL_DEG = 2.0   # degrees — segments within this angle are "same direction"
_MERGE_PERP_TOL     = 4      # px  — max perpendicular distance for collinear grouping
_MERGE_GAP_THRESH   = 60     # px  — max gap between endpoints to bridge and merge


def _merge_collinear_segments(
    lines: List[Tuple[int, int, int, int]],
) -> List[Tuple[int, int, int, int]]:
    """Merge overlapping / close collinear Hough segments into single runs.

    HoughLinesP emits many short fragments per pipe run. This phase:
      1. Groups segments by dominant angle (±_MERGE_ANGLE_TOL_DEG).
      2. Within each angle group, sub-groups by perpendicular offset
         (within _MERGE_PERP_TOL px) — these are collinear.
      3. Projects each sub-group onto the direction axis and sorts.
      4. Merges adjacent segments whose gap ≤ _MERGE_GAP_THRESH into one.

    Returns a smaller list of longer segments. The is_dashed flag is NOT
    handled here — callers re-classify the merged result.
    """
    if not lines:
        return lines

    angle_tol = math.radians(_MERGE_ANGLE_TOL_DEG)

    def seg_angle(x1: int, y1: int, x2: int, y2: int) -> float:
        a = math.atan2(y2 - y1, x2 - x1)
        if a < 0:
            a += math.pi
        return a

    # Snap each segment to a canonical angle bucket (multiples of angle_tol).
    def angle_bucket(a: float) -> int:
        return int(round(a / angle_tol))

    groups: Dict[int, List[int]] = {}
    angles = []
    for i, (x1, y1, x2, y2) in enumerate(lines):
        a = seg_angle(x1, y1, x2, y2)
        angles.append(a)
        bucket = angle_bucket(a)
        groups.setdefault(bucket, []).append(i)

    merged: List[Tuple[int, int, int, int]] = []

    for bucket, idxs in groups.items():
        ref_angle = bucket * angle_tol
        cos_a, sin_a = math.cos(ref_angle), math.sin(ref_angle)
        # Perpendicular direction.
        perp_cos, perp_sin = -sin_a, cos_a

        # Project each segment midpoint onto perp axis for collinear grouping.
        def perp_offset(x1: int, y1: int, x2: int, y2: int) -> float:
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            return mx * perp_cos + my * perp_sin

        def proj_along(x: int, y: int) -> float:
            return x * cos_a + y * sin_a

        # Sub-group by perp offset.
        sub_groups: List[List[int]] = []
        assigned = [False] * len(idxs)
        for ii, i in enumerate(idxs):
            if assigned[ii]:
                continue
            x1, y1, x2, y2 = lines[i]
            po = perp_offset(x1, y1, x2, y2)
            grp = [i]
            assigned[ii] = True
            for jj, j in enumerate(idxs):
                if assigned[jj]:
                    continue
                xA, yA, xB, yB = lines[j]
                if abs(perp_offset(xA, yA, xB, yB) - po) <= _MERGE_PERP_TOL:
                    grp.append(j)
                    assigned[jj] = True
            sub_groups.append(grp)

        for grp in sub_groups:
            # Build one (low_proj, high_proj, lx, ly, hx, hy) tuple per segment,
            # oriented so low_proj <= high_proj, then sort by low_proj.
            # This avoids the old endpoint-by-endpoint bug where a single segment
            # longer than _MERGE_GAP_THRESH was incorrectly split into two
            # zero-length stubs (its endpoints looked like a "gap" to the old loop).
            seg_ranges: List[Tuple[float, float, int, int, int, int]] = []
            for i in grp:
                x1, y1, x2, y2 = lines[i]
                p1 = proj_along(x1, y1)
                p2 = proj_along(x2, y2)
                if p1 <= p2:
                    seg_ranges.append((p1, p2, x1, y1, x2, y2))
                else:
                    seg_ranges.append((p2, p1, x2, y2, x1, y1))
            seg_ranges.sort()   # by low_proj

            # Sliding merge: extend current run while next segment's start is
            # within _MERGE_GAP_THRESH of the current run's far end.
            cur_lo, cur_hi, cur_lx, cur_ly, cur_hx, cur_hy = seg_ranges[0]

            for p_lo, p_hi, lx, ly, hx, hy in seg_ranges[1:]:
                gap = p_lo - cur_hi   # distance from run far-end to next seg start
                if gap > _MERGE_GAP_THRESH:
                    merged.append((cur_lx, cur_ly, cur_hx, cur_hy))
                    cur_lo, cur_hi = p_lo, p_hi
                    cur_lx, cur_ly, cur_hx, cur_hy = lx, ly, hx, hy
                elif p_hi > cur_hi:
                    # Extend run — new segment goes further along the axis.
                    cur_hi = p_hi
                    cur_hx, cur_hy = hx, hy
            merged.append((cur_lx, cur_ly, cur_hx, cur_hy))

    # Drop degenerate near-zero-length merged segments.
    min_len_sq = _HOUGH_MIN_LINE_LENGTH ** 2
    merged = [
        (x1, y1, x2, y2) for (x1, y1, x2, y2) in merged
        if (x2 - x1) ** 2 + (y2 - y1) ** 2 >= min_len_sq
    ]
    return merged


def _filter_border_lines(
    lines: List[Dict],
    drawing_w: int,
    drawing_h: int,
    border_margin: float = 0.02,
    title_block_frac: float = 0.14,
) -> List[Dict]:
    """Remove lines that form the outer border or title-block dividers.

    Called on full-drawing-coordinate lines (after Phase 7 offsets).

    Excluded cases:
      - Both endpoints within border_margin of the same edge (left/right/top/bottom).
        These are the four sides of the outer bounding rectangle.
      - Both endpoints in the bottom title_block_frac of the drawing AND running
        nearly horizontally (|dy| < 2% of drawing height) — title block dividers.
    """
    if drawing_w <= 0 or drawing_h <= 0:
        return lines

    bm_x = border_margin * drawing_w
    bm_y = border_margin * drawing_h
    tb_top = drawing_h * (1.0 - title_block_frac)

    result = []
    for ln in lines:
        x1, y1 = ln["startX"], ln["startY"]
        x2, y2 = ln["endX"],   ln["endY"]

        # Left border.
        if x1 < bm_x and x2 < bm_x:
            continue
        # Right border.
        if x1 > drawing_w - bm_x and x2 > drawing_w - bm_x:
            continue
        # Top border.
        if y1 < bm_y and y2 < bm_y:
            continue
        # Bottom border.
        if y1 > drawing_h - bm_y and y2 > drawing_h - bm_y:
            continue
        # Title-block horizontal dividers (in bottom fraction, nearly flat).
        if y1 > tb_top and y2 > tb_top:
            if abs(y2 - y1) < bm_y:
                continue

        result.append(ln)

    before = len(lines)
    after  = len(result)
    if before != after:
        logger.info(
            "[line-detect] border/title filter: removed %d / %d segments",
            before - after, before,
        )
    return result


def _process_tile(
    tile_path: Path,
    yolo_bboxes: List[List[float]],
    tile_xmin: int,
    tile_ymin: int,
) -> List[Dict]:
    """Run Phases 1–7 on a single tile PNG.

    Returns line segments with coordinates already offset to full-drawing space.
    All internal processing is in tile-local pixels; the offset is the last step.
    """
    import cv2

    img_bgr = cv2.imread(str(tile_path))
    if img_bgr is None:
        logger.warning("Could not load tile image: %s", tile_path)
        return []

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    tile_h, tile_w = gray.shape

    # Phase 1 — suppress text strokes
    binary, bg_val = _binarize(gray)
    binary, gray = _suppress_text_strokes(binary, gray, bg_val)

    # Phase 2 — mask YOLO symbol bboxes
    gray, binary = _mask_yolo_symbols(gray, binary, yolo_bboxes, bg_val)

    # Phase 3 — drop noise blobs
    binary = _drop_noise_blobs(binary)

    if cv2.countNonZero(binary) == 0:
        return []

    # Phase 4 — skeletonize
    skeleton = _skeletonize(binary)

    if cv2.countNonZero(skeleton) == 0:
        return []

    # Phase 5 — Hough line detection
    lines = _detect_hough_lines(skeleton)

    # Phase 6 — filter tile-edge artifacts
    lines = _filter_edge_artifacts(lines, tile_w, tile_h)

    # Phase 6.5 — merge collinear/overlapping segments into single runs.
    # Reduces fragmented pipe representations to one segment per run.
    lines = _merge_collinear_segments(lines)

    # Phase 5.5 — classify solid vs dashed (after merge so flags are on merged segs)
    dashed_flags = _classify_dashed(lines, skeleton)

    # Phase 7 — offset to full-drawing coordinates
    offset_lines = [
        {
            "startX":   tile_xmin + x1,
            "startY":   tile_ymin + y1,
            "endX":     tile_xmin + x2,
            "endY":     tile_ymin + y2,
            "is_dashed": dashed_flags[i],
        }
        for i, (x1, y1, x2, y2) in enumerate(lines)
    ]

    logger.debug(
        "%s → %d Hough segments (yolo_masks=%d)",
        tile_path.name, len(offset_lines), len(yolo_bboxes),
    )
    return offset_lines


# ── Public API ────────────────────────────────────────────────────────────────

_TILE_RE = re.compile(r"tile_p(\d+)_r(\d+)_c(\d+)\.png$")


def detect_lines_for_job(
    job_id: int,
    job_dir: Path,
    gpu_detections_json: Optional[str],
) -> None:
    """Process all tiles for a job and write clean topology.json (Phase 8).

    Called from pipeline_runner._run_line_detection() after YOLO inference so
    that YOLO bboxes are available for Phase 2 symbol masking.

    Tile offset values (xmin, ymin) are derived by reading the stored full-page
    images in job_dir/tmp/ and applying the same overlap formula as pdf_to_tiles.py
    — NOT by multiplying tile index × tile size, which would ignore the 20% overlap
    and give wrong offsets for all non-zero tiles.

    Writes:
      job_dir/graph_outputs/topology.json
        {"lines": [{startX, startY, endX, endY}, ...],
         "drawing_width": int, "drawing_height": int}
    """
    tmp_dir = job_dir / "tmp"
    if not tmp_dir.exists():
        logger.warning("[line-detect] job %d: tmp/ not found, skipping", job_id)
        return

    tile_files = sorted(tmp_dir.glob("tile_p*_r*_c*.png"))
    if not tile_files:
        logger.warning("[line-detect] job %d: no tile PNGs in %s", job_id, tmp_dir)
        return

    # Build (page, row, col) → [bbox_list] lookup from YOLO detections.
    # inference.py stores bbox in tile-local coords + tile_page/row/col fields.
    tile_detections: Dict[Tuple[int, int, int], List[List[float]]] = {}
    if gpu_detections_json:
        try:
            parsed = json.loads(gpu_detections_json)
            dets = parsed if isinstance(parsed, list) else parsed.get("detections", [])
            for det in dets:
                p = det.get("tile_page")
                r = det.get("tile_row")
                c = det.get("tile_col")
                bbox = det.get("bbox", [])
                if p is not None and r is not None and c is not None and len(bbox) == 4:
                    key = (int(p), int(r), int(c))
                    tile_detections.setdefault(key, []).append(
                        [float(v) for v in bbox]
                    )
        except Exception as exc:
            logger.warning(
                "[line-detect] job %d: failed to parse gpu_detections: %s", job_id, exc
            )

    all_lines: List[Dict] = []
    drawing_width = 0
    drawing_height = 0

    for tile_path in tile_files:
        m = _TILE_RE.match(tile_path.name)
        if not m:
            continue
        page, row, col = int(m.group(1)), int(m.group(2)), int(m.group(3))

        # Get tile bbox using the stored full-page image — same formula as
        # pdf_to_tiles.py so the offset accounts for the 20% overlap correctly.
        page_img_path = tmp_dir / f"page_{page}_full.png"
        bbox = _compute_tile_bbox(page_img_path, row, col)
        if bbox is None:
            logger.warning(
                "[line-detect] job %d: cannot compute bbox for %s — skipping",
                job_id, tile_path.name,
            )
            continue

        tile_xmin, tile_ymin, tile_xmax, tile_ymax = bbox
        drawing_width  = max(drawing_width,  tile_xmax)
        drawing_height = max(drawing_height, tile_ymax)

        yolo_bboxes = tile_detections.get((page, row, col), [])

        try:
            lines = _process_tile(tile_path, yolo_bboxes, tile_xmin, tile_ymin)
            all_lines.extend(lines)
        except Exception as exc:
            logger.error(
                "[line-detect] job %d: error processing %s: %s",
                job_id, tile_path.name, exc,
            )
            # Non-fatal — continue processing remaining tiles

    # Phase 8a — remove outer border lines + title-block dividers.
    # Runs on full-drawing coords after all tiles are merged.
    all_lines = _filter_border_lines(all_lines, drawing_width, drawing_height)

    # Phase 8 — write clean topology.json
    output_dir = job_dir / "graph_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    topo_path = output_dir / "topology.json"

    topology = {
        "lines": all_lines,
        "drawing_width":  drawing_width,
        "drawing_height": drawing_height,
    }
    try:
        with topo_path.open("w") as f:
            json.dump(topology, f)
        size_kb = topo_path.stat().st_size // 1024
        logger.info(
            "[line-detect] job %d: wrote %d segments → %s (%d KB)",
            job_id, len(all_lines), topo_path, size_kb,
        )
    except Exception as exc:
        logger.error("[line-detect] job %d: failed to write topology.json: %s", job_id, exc)
