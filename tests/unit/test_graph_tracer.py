"""Unit tests for webapp/graph/tracer.py (predecessor spec §8).

Synthetic black-on-white images: two rectangles connected by a line → exactly
one segment; empty image → []; an all-bbox image (everything masked) → [].
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.tracer import (  # noqa: E402
    LineSegment,
    NoopLineTracer,
    OpenCVLineTracer,
    _rdp,
)


def _two_rects_one_line() -> np.ndarray:
    """White (255) background, two dark rectangles joined by a dark line."""
    img = np.full((120, 300), 255, dtype=np.uint8)
    # Left rectangle
    img[40:80, 20:60] = 0
    # Right rectangle
    img[40:80, 240:280] = 0
    # Connecting horizontal line at y=60 between the rects
    img[58:62, 60:240] = 0
    return img


def test_noop_tracer_returns_empty():
    img = _two_rects_one_line()
    assert NoopLineTracer().trace(img) == []


def test_empty_image_returns_empty():
    blank = np.full((100, 100), 255, dtype=np.uint8)
    tracer = OpenCVLineTracer(min_length_px=20)
    assert tracer.trace(blank) == []


def test_two_rects_one_line_yields_a_segment():
    img = _two_rects_one_line()
    # Mask out the two rectangle interiors so only the connecting line traces.
    mask = np.zeros_like(img, dtype=bool)
    mask[40:80, 20:60] = True
    mask[40:80, 240:280] = True
    tracer = OpenCVLineTracer(min_length_px=20)
    segments = tracer.trace(img, mask)
    assert len(segments) >= 1
    # The dominant segment should span most of the horizontal gap.
    longest = max(segments, key=lambda s: abs(s.polyline[-1][0] - s.polyline[0][0]))
    span = abs(longest.polyline[-1][0] - longest.polyline[0][0])
    assert span > 100
    assert isinstance(longest, LineSegment)
    assert 0.0 <= longest.confidence <= 1.0


def test_all_bbox_masked_yields_empty():
    """If everything is masked to background, nothing can be traced."""
    img = _two_rects_one_line()
    full_mask = np.ones_like(img, dtype=bool)
    tracer = OpenCVLineTracer(min_length_px=20)
    assert tracer.trace(img, full_mask) == []


def test_large_image_downscales_and_returns_page_pixel_coords():
    """A page larger than max_trace_dim is traced on a downscaled copy, but the
    emitted polyline coords must be scaled BACK to page-pixel space."""
    W, H = 4800, 400
    img = np.full((H, W), 255, dtype=np.uint8)
    img[185:215, 100:4700] = 0  # long thick horizontal dark line (survives downscale)
    tracer = OpenCVLineTracer(min_length_px=20, max_trace_dim=1000)
    segs = tracer.trace(img)
    assert len(segs) >= 1
    longest = max(segs, key=lambda s: abs(s.polyline[-1][0] - s.polyline[0][0]))
    span = abs(longest.polyline[-1][0] - longest.polyline[0][0])
    # Page-pixel span (~4600), NOT downscaled (~1000) — proves coords scaled back.
    assert span > 3000
    for x, y in longest.polyline:
        assert 0 <= x <= W
        assert 0 <= y <= H


def test_small_image_not_downscaled():
    """Images already under max_trace_dim trace unchanged (existing fixtures)."""
    img = _two_rects_one_line()
    mask = np.zeros_like(img, dtype=bool)
    mask[40:80, 20:60] = True
    mask[40:80, 240:280] = True
    tracer = OpenCVLineTracer(min_length_px=20, max_trace_dim=4000)
    segs = tracer.trace(img, mask)
    assert len(segs) >= 1
    longest = max(segs, key=lambda s: abs(s.polyline[-1][0] - s.polyline[0][0]))
    assert abs(longest.polyline[-1][0] - longest.polyline[0][0]) > 100


def test_rdp_simplifies_collinear_points():
    pts = [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]
    out = _rdp(pts, epsilon=2.0)
    assert out[0] == (0, 0)
    assert out[-1] == (4, 0)
    # A straight line collapses to its 2 endpoints.
    assert len(out) == 2


def test_rdp_keeps_a_corner():
    pts = [(0, 0), (5, 0), (10, 0), (10, 5), (10, 10)]
    out = _rdp(pts, epsilon=2.0)
    # The corner at (10, 0) must survive.
    assert (10, 0) in out
    assert out[0] == (0, 0)
    assert out[-1] == (10, 10)
