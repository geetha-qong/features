"""
OCR-based tag locator for the API-extraction path.

The offline YOLO detector attaches bbox_tile / tile_x0 / tile_y0 to each raw valve,
so visualize.generate_annotated_pdf can draw numbered boxes. The API extractor
returns tag strings only — no spatial info.

This module bridges that gap: given the tile list (from pdf_to_tiles) and the list
of CSV tag strings, it OCRs each tile, translates bboxes to full-page coordinates,
and matches each tag to its OCR text by digit-core + fuzzy ratio. Returns
raw_valves-shaped dicts so visualize works unchanged in API mode.

Per-tile OCR (vs one pass over the page render) is significantly more accurate on
P&ID drawings because individual tag labels are ~10-15px tall on the full page but
~30-50px on a tile — well within OCR's effective range.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import List, Dict, Optional


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().upper())


def _bbox_from_polygon(poly) -> Optional[List[int]]:
    try:
        xs = [int(p[0]) for p in poly]
        ys = [int(p[1]) for p in poly]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:
        return None


def _digit_core(s: str) -> str:
    """Longest digit run, used as a unique key for matching short tags whose
    OCR'd version may have lost the type prefix (e.g. 'PV-01156' OCR'd as '01156')."""
    runs = re.findall(r"\d{3,}", s)
    return max(runs, key=len) if runs else ""


def locate_tags(tiles: List[Dict], tags: List[str], min_score: int = 85) -> List[Dict]:
    """OCR each tile and match each CSV tag to its location.

    `tiles` is the list returned by pdf_to_tiles.pdf_to_tiles(): each dict has
    'path', 'x0', 'y0'. Bboxes in the result are full-page coordinates (so they
    drop into visualize.generate_annotated_pdf with tile_x0=tile_y0=0).

    Returns raw_valves-shaped dicts:
        {valve_tag, bbox_tile=[x1,y1,x2,y2], tile_x0=0, tile_y0=0, ocr_score}

    Tags without a confident match are dropped silently — caller compares
    len(tags) vs len(result) for coverage.
    """
    if not tiles or not tags:
        return []

    try:
        from rapidocr_onnxruntime import RapidOCR
        from rapidfuzz import fuzz
    except ImportError as e:
        print(f"  [ocr_locate] OCR libs not installed ({e}); annotated PDF will have no boxes")
        return []

    ocr = RapidOCR()

    segments: List[tuple] = []
    for tile in tiles:
        path = tile.get("path")
        if not path or not Path(path).exists():
            continue
        tx0, ty0 = tile.get("x0", 0), tile.get("y0", 0)
        result, _ = ocr(str(path))
        for entry in (result or []):
            poly, text = entry[0], entry[1]
            bbox = _bbox_from_polygon(poly)
            if bbox is None:
                continue
            full_bbox = [bbox[0] + tx0, bbox[1] + ty0, bbox[2] + tx0, bbox[3] + ty0]
            segments.append((_normalize(text), full_bbox))

    print(f"  [ocr_locate] OCR found {len(segments)} text segments across {len(tiles)} tiles")
    if not segments:
        return []

    # Index by digit-core for fast exact-suffix lookup.
    by_digit: Dict[str, List[tuple]] = {}
    for text, bbox in segments:
        for run in re.findall(r"\d{3,}", text):
            by_digit.setdefault(run, []).append((text, bbox))

    out: List[Dict] = []
    used_bboxes: set = set()
    for tag in tags:
        norm = _normalize(tag)
        if not norm:
            continue
        digit_key = _digit_core(norm)
        best_score, best_bbox = 0, None

        if digit_key and digit_key in by_digit:
            for text, bbox in by_digit[digit_key]:
                if tuple(bbox) in used_bboxes:
                    continue
                # When digit matches, partial_ratio captures prefix similarity
                score = max(fuzz.partial_ratio(norm, text), 90)
                if score > best_score:
                    best_score, best_bbox = score, bbox

        if best_bbox is None:
            for text, bbox in segments:
                if tuple(bbox) in used_bboxes:
                    continue
                score = fuzz.partial_ratio(norm, text)
                if score > best_score:
                    best_score, best_bbox = score, bbox

        if best_bbox is not None and best_score >= min_score:
            out.append({
                "valve_tag": tag,
                "bbox_tile": best_bbox,
                "tile_x0": 0,
                "tile_y0": 0,
                "ocr_score": best_score,
            })
            used_bboxes.add(tuple(best_bbox))

    print(f"  [ocr_locate] located {len(out)}/{len(tags)} tags")
    return out
