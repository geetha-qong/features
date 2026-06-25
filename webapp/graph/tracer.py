"""Step D — line tracing.

``LineSegment`` + the ``LineTracer`` Protocol define the architectural seam for
the future CV-CUDA migration (predecessor spec §4). ``OpenCVLineTracer`` is the
v0 classical-CV implementation; ``NoopLineTracer`` is a stub used in tests and
when CV is disabled.

All coordinates emitted are **page-pixel** space (matching ``Job.gpu_detections``
and the full-page canvas). The tracer operates on a single full-page grayscale
image; bbox interiors are masked to background before skeletonisation so symbol
glyphs don't get traced as lines.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Protocol, Sequence, Tuple

import numpy as np


class LineSegment(NamedTuple):
    """A traced polyline in page-pixel coordinates.

    ``polyline`` is an ordered list of ``(x, y)`` integer points (simplified via
    Douglas-Peucker). ``tile`` is the originating tile filename (or ``"page"``
    when traced on the full page). ``confidence`` is a heuristic in [0, 1].
    """

    polyline: List[Tuple[int, int]]
    tile: str
    confidence: float


class LineTracer(Protocol):
    """Swap-point Protocol. Implementations return page-pixel ``LineSegment``s.

    ``image`` is a 2-D grayscale ``np.ndarray`` (page-pixel). ``bbox_mask`` is a
    boolean/uint8 mask, same H×W as ``image``, True where a YOLO bbox interior
    sits (those pixels are treated as background so symbols aren't traced).
    """

    def trace(
        self, image: np.ndarray, bbox_mask: Optional[np.ndarray] = None
    ) -> List[LineSegment]:
        ...


class NoopLineTracer:
    """Returns no segments. Used when CV tracing is disabled / in tests."""

    def trace(
        self, image: np.ndarray, bbox_mask: Optional[np.ndarray] = None
    ) -> List[LineSegment]:
        return []


def _rdp(points: Sequence[Tuple[int, int]], epsilon: float) -> List[Tuple[int, int]]:
    """Ramer-Douglas-Peucker polyline simplification (iterative).

    Pure-python so we don't depend on cv2.approxPolyDP shape quirks. Keeps the
    two endpoints and any vertex whose perpendicular distance to the current
    chord exceeds ``epsilon``.
    """
    if len(points) < 3:
        return list(points)

    pts = [(float(x), float(y)) for x, y in points]
    keep = [False] * len(pts)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(pts) - 1)]

    while stack:
        start, end = stack.pop()
        ax, ay = pts[start]
        bx, by = pts[end]
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy

        dmax = 0.0
        index = -1
        for i in range(start + 1, end):
            px, py = pts[i]
            if seg_len_sq == 0.0:
                dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                # perpendicular distance from point to segment a-b
                t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
                projx = ax + t * dx
                projy = ay + t * dy
                dist = ((px - projx) ** 2 + (py - projy) ** 2) ** 0.5
            if dist > dmax:
                dmax = dist
                index = i

        if dmax > epsilon and index != -1:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))

    return [(int(round(pts[i][0])), int(round(pts[i][1]))) for i in range(len(pts)) if keep[i]]


def _order_component_pixels(ys: np.ndarray, xs: np.ndarray) -> List[Tuple[int, int]]:
    """Order a small set of skeleton pixels into a rough polyline.

    For a thin line component the pixels form a 1-px chain. We approximate an
    ordering by projecting onto the dominant axis (PCA-lite via bbox aspect):
    sort by x if the component is wider than tall, else by y. This is adequate
    for RDP on near-straight pipe runs; the resolver only cares about endpoints.
    """
    if len(xs) == 0:
        return []
    width = int(xs.max() - xs.min())
    height = int(ys.max() - ys.min())
    if width >= height:
        order = np.argsort(xs, kind="stable")
    else:
        order = np.argsort(ys, kind="stable")
    return [(int(xs[i]), int(ys[i])) for i in order]


class OpenCVLineTracer:
    """v0 classical-CV pipe tracer.

    Pipeline: adaptive binarize → mask bbox interiors to background →
    skeletonize → connected components → drop tiny → RDP simplify.
    """

    def __init__(
        self,
        *,
        min_length_px: int = 20,
        min_length_frac: float = 0.012,
        rdp_epsilon: float = 2.0,
        adaptive_block_size: int = 35,
        adaptive_C: int = 10,
        tile: str = "page",
        max_trace_dim: int = 4000,
    ) -> None:
        # Effective minimum line length is max(min_length_px, frac * max(H, W)).
        # The fraction makes the floor scale with resolution: on a ~1600px tile
        # 20px wins; on a 5500px hi-DPI page it rises to ~66px so text strokes,
        # borders and hatching stop registering as "pipes". Small synthetic test
        # images (<~1600px) keep the flat 20px floor, so unit fixtures are
        # unaffected.
        self.min_length_px = min_length_px
        self.min_length_frac = min_length_frac
        self.rdp_epsilon = rdp_epsilon
        # cv2 requires an odd block size > 1
        if adaptive_block_size % 2 == 0:
            adaptive_block_size += 1
        self.adaptive_block_size = adaptive_block_size
        self.adaptive_C = adaptive_C
        self.tile = tile
        # Trace on a copy downscaled so its longest side ≤ max_trace_dim. The
        # full-res connected-components label array is int32 (~350 MB on an
        # 8000px page) and the per-component pixel scan rescans it once per
        # component — together that OOM-kills small boxes and hangs for minutes.
        # Downscaling cuts memory by scale² and time far more; segment coords are
        # scaled back to page-pixel space before emitting. 0/None disables it.
        self.max_trace_dim = max_trace_dim

    def trace(
        self, image: np.ndarray, bbox_mask: Optional[np.ndarray] = None
    ) -> List[LineSegment]:
        # Imported lazily so importing this module doesn't require cv2/skimage
        # at module load (keeps `from webapp.graph import ...` cheap).
        import cv2
        from skimage.morphology import skeletonize

        if image is None or image.size == 0:
            return []

        img = image
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = img.astype(np.uint8, copy=False)

        # Downscale large pages so the int32 label array + per-component scans
        # stay small (memory/time). Segment coords are scaled back below.
        h0, w0 = img.shape[:2]
        scale = 1.0
        if self.max_trace_dim and max(h0, w0) > self.max_trace_dim:
            scale = self.max_trace_dim / float(max(h0, w0))
            new_w = max(1, int(round(w0 * scale)))
            new_h = max(1, int(round(h0 * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            if bbox_mask is not None and bbox_mask.shape == (h0, w0):
                bbox_mask = cv2.resize(
                    bbox_mask.astype(np.uint8), (new_w, new_h),
                    interpolation=cv2.INTER_NEAREST,
                ).astype(bool)
        inv_scale = 1.0 / scale

        # Adaptive threshold → foreground (linework) = 255 on black background.
        # P&ID linework is dark on white paper, so THRESH_BINARY_INV.
        binary = cv2.adaptiveThreshold(
            img,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            self.adaptive_block_size,
            self.adaptive_C,
        )

        # Mask bbox interiors to background so symbol glyphs aren't traced.
        # adaptiveThreshold returns a fresh array we own — mutate it in place
        # (no defensive .copy(), which would double peak memory on big pages).
        if bbox_mask is not None and bbox_mask.shape == binary.shape:
            binary[bbox_mask.astype(bool)] = 0

        # Skeletonize expects a boolean image; returns 1-px-wide skeleton.
        skeleton = skeletonize(binary > 0)
        del binary
        skel_u8 = (skeleton.astype(np.uint8)) * 255
        del skeleton

        num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            skel_u8, connectivity=8
        )
        h_img, w_img = skel_u8.shape[:2]
        del skel_u8

        effective_min = max(self.min_length_px, int(max(h_img, w_img) * self.min_length_frac))

        segments: List[LineSegment] = []
        for label in range(1, num):  # 0 is background
            area = int(stats[label, cv2.CC_STAT_AREA])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            left = int(stats[label, cv2.CC_STAT_LEFT])
            top = int(stats[label, cv2.CC_STAT_TOP])
            # span = bounding extent of the component; drop components whose
            # longest extent is below the (resolution-scaled) minimum line length.
            span = max(w, h)
            if span < effective_min:
                continue
            if area < 2:
                continue
            # Line-likeness via skeleton-area vs span. A 1-px-wide line (any
            # angle, incl. diagonals and a few right-angle bends) has skeleton
            # pixel-count close to its longest extent (area/span ≈ 1–2.5).
            # Branchy clusters — text, title-block stamps, hatching knots — pack
            # many pixels into a small bbox, so area/span balloons. Drop those.
            # Robust to diagonals (unlike a bbox aspect-ratio test).
            if area / max(1, span) > 3.0:
                continue

            # Windowed extraction: scan only this component's bbox window, not
            # the whole page. Turns the per-component cost from O(page) to
            # O(component) — the other half of the OOM/hang fix.
            sub = _labels[top:top + h, left:left + w]
            ys, xs = np.where(sub == label)
            if len(xs) == 0:
                continue
            xs = xs + left
            ys = ys + top
            ordered = _order_component_pixels(ys, xs)
            if len(ordered) < 2:
                continue
            polyline = _rdp(ordered, self.rdp_epsilon)
            if len(polyline) < 2:
                continue

            # Scale polyline back to page-pixel space if we downscaled.
            if scale != 1.0:
                polyline = [
                    (int(round(x * inv_scale)), int(round(y * inv_scale)))
                    for x, y in polyline
                ]

            # Heuristic confidence: longer, straighter lines score higher.
            # Use the page-pixel span so the score is resolution-independent.
            confidence = min(1.0, 0.4 + (span * inv_scale) / 400.0)
            segments.append(
                LineSegment(polyline=polyline, tile=self.tile, confidence=round(confidence, 3))
            )

        del _labels
        return segments
