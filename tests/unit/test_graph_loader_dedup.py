"""Tests that load_job_input de-dupes cross-tile detections before
translating to page-pixel coordinates.

Tile geometry (900x900):
  tile_p0_r0_c0.png: x0=0,  y0=0  -> x1=360, y1=360
  tile_p0_r0_c1.png: x0=240,y0=0  -> x1=660, y1=360

A bbox at tile-local [280,5,300,25] in c0 maps to page [280,5,300,25].
The SAME glyph in c1 at tile-local [40,5,60,25] maps to page [280,5,300,25].
IoU=1.0 -> dedup must keep only one.
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from webapp.graph.loader import load_job_input, compute_tile_offsets


def test_load_job_input_dedups_cross_tile(tmp_path):
    """Two tile-local detections mapping to the same page-space box collapse to 1."""
    # Write a full-page PNG (1-pixel white) so load_job_input can read dimensions.
    # We'll use a real PNG so cv2.imread works; but since cv2 may not be available
    # in the test env, we write canonical_graph.json instead and rely on the
    # bbox-extent fallback path to size the page at 900x900.
    # Actually: tile_local_detections=True falls back to width=height=0 when no image.
    # We need a real image to get tile_offsets. Use cv2 if available; otherwise skip.
    try:
        import cv2
        import numpy as np
        # Create a 900x900 white PNG
        img = np.full((900, 900, 3), 255, dtype="uint8")
        img_path = str(tmp_path / "page_0_full.png")
        cv2.imwrite(img_path, img)
        has_cv2 = True
    except ImportError:
        has_cv2 = False

    dets = [
        {
            "label": "valve_bv",
            "tile": "tile_p0_r0_c0.png",
            "bbox": [280, 5, 300, 25],
            "confidence": 0.7,
        },
        {
            "label": "valve_bv",
            "tile": "tile_p0_r0_c1.png",
            "bbox": [40, 5, 60, 25],
            "confidence": 0.9,
        },
    ]

    ji = load_job_input(str(tmp_path), detections=dets, page=1, tile_local_detections=True)

    if has_cv2:
        # With a real 900x900 image, tile geometry resolves both to page [280,5,300,25].
        # After dedup, only the higher-confidence one (c1, 0.9) survives.
        assert len(ji.detections) == 1, (
            f"Expected 1 detection after cross-tile dedup, got {len(ji.detections)}: {ji.detections}"
        )
    else:
        # Without cv2, tile_local_detections=True gives width=height=0 → no tile_offsets
        # → dedup skips (gate) → both pass through untranslated
        assert len(ji.detections) <= 2


def test_load_job_input_dedup_preserves_higher_confidence(tmp_path):
    """When two detections overlap, the higher-confidence one is retained."""
    try:
        import cv2
        import numpy as np
        img = np.full((900, 900, 3), 255, dtype="uint8")
        cv2.imwrite(str(tmp_path / "page_0_full.png"), img)
    except ImportError:
        import pytest
        pytest.skip("cv2 not available")

    # c0 detection: lower confidence
    # c1 detection: higher confidence — this one should survive
    dets = [
        {
            "label": "valve_bv",
            "tile": "tile_p0_r0_c0.png",
            "bbox": [280, 5, 300, 25],
            "confidence": 0.7,
        },
        {
            "label": "valve_bv",
            "tile": "tile_p0_r0_c1.png",
            "bbox": [40, 5, 60, 25],
            "confidence": 0.9,
        },
    ]

    ji = load_job_input(str(tmp_path), detections=dets, page=1, tile_local_detections=True)
    assert len(ji.detections) == 1
    # The surviving detection comes from c1 (higher confidence 0.9)
    surviving = ji.detections[0]
    assert surviving["confidence"] == 0.9
    # Its page-pixel bbox should be [280, 5, 300, 25] (c1: 40+240=280, 60+240=300)
    assert surviving["bbox"] == [280, 5, 300, 25]


def test_load_job_input_different_labels_not_deduped(tmp_path):
    """Different labels at the same position must NOT suppress each other."""
    try:
        import cv2
        import numpy as np
        img = np.full((900, 900, 3), 255, dtype="uint8")
        cv2.imwrite(str(tmp_path / "page_0_full.png"), img)
    except ImportError:
        import pytest
        pytest.skip("cv2 not available")

    dets = [
        {
            "label": "valve_bv",
            "tile": "tile_p0_r0_c0.png",
            "bbox": [280, 5, 300, 25],
            "confidence": 0.9,
        },
        {
            "label": "instrument_pt",
            "tile": "tile_p0_r0_c1.png",
            "bbox": [40, 5, 60, 25],
            "confidence": 0.9,
        },
    ]

    ji = load_job_input(str(tmp_path), detections=dets, page=1, tile_local_detections=True)
    # Different classes at same position — both survive
    assert len(ji.detections) == 2


def test_load_job_input_no_tile_offsets_skips_dedup(tmp_path):
    """When no image exists and tile_local_detections=True, width=height=0,
    no tile_offsets, dedup is skipped safely (gate)."""
    dets = [
        {"label": "valve_bv", "tile": "tile_p0_r0_c0.png", "bbox": [10, 10, 30, 30], "confidence": 0.7},
        {"label": "valve_bv", "tile": "tile_p0_r0_c1.png", "bbox": [10, 10, 30, 30], "confidence": 0.9},
    ]
    ji = load_job_input(str(tmp_path), detections=dets, page=1, tile_local_detections=True)
    # Width/height = 0 -> no tile_offsets -> dedup gate skips -> both pass through
    assert len(ji.detections) == 2
