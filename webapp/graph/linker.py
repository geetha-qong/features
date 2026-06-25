"""Step C — bbox → tag linker.

Crop each YOLO bbox, OCR it (rapidocr), fuzzy-match the OCR'd tag into the
canonical entity list (rapidfuzz Levenshtein), and fall back to a class-prior
mapping when OCR is empty. Outputs ``(entity_id, tag, link_quality)``.

All pure-python; the OCR engine is imported lazily so the module imports cleanly
without the onnxruntime model present, and OCR can be monkeypatched in tests.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Link-quality flags
MATCH = "match"
WEAK_MATCH = "weak_match"
NONE = "none"
CLASS_FALLBACK = "class_fallback"


# ── Class-prior mapping (ported from webapp/routers/api_v1.py:_yolo_class_to_canonical) ──


def yolo_class_to_canonical(label: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Map a YOLO class string to ``(entity_class, sub_class_or_None)``.

    Verbatim port of ``webapp/routers/api_v1.py:_yolo_class_to_canonical`` so the
    graph package stays import-independent of the router module. Keep in sync if
    that mapping changes.
    """
    if not label:
        return None, None
    if label.startswith("valve_"):
        return "valve", label[len("valve_"):].upper()
    if label.startswith("inst_") or label in {"interlock", "SIS-R"}:
        return "instrument", None
    # v1-9 used "Pump_Dwg_Pump" (underscore); v1-10 uses "Pump/Dwg Pump"
    if label in {"Motor", "Pump/Dwg Pump", "Pump_Dwg_Pump"}:
        return "equipment", None
    if label.startswith("arrow_") or label.startswith("connector_"):
        return None, None
    return None, None


# ── Crop + OCR ──────────────────────────────────────────────────────────────


def crop_bbox(image: np.ndarray, bbox: Sequence[float]) -> np.ndarray:
    """Crop ``[x1, y1, x2, y2]`` (page-pixel) out of ``image``.

    Coordinates are clamped to image bounds and rounded to ints. Returns an
    empty array if the crop is degenerate (zero area / out of bounds).
    """
    if image is None or image.size == 0 or bbox is None:
        return np.empty((0, 0), dtype=getattr(image, "dtype", np.uint8))
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
    x1, x2 = sorted((int(round(x1)), int(round(x2))))
    y1, y2 = sorted((int(round(y1)), int(round(y2))))
    x1 = max(0, min(x1, w))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h))
    y2 = max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return np.empty((0, 0), dtype=image.dtype)
    return image[y1:y2, x1:x2]


# Module-level singleton so the (heavy) rapidocr model loads once.
_OCR_ENGINE = None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR  # lazy import

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def ocr_crop(crop: np.ndarray) -> str:
    """OCR a small crop, return the best-guess text (uppercased, stripped).

    Returns ``""`` on empty crop or no recognized text. rapidocr returns
    ``(result, elapse)`` where result is a list of ``[box, text, score]``; we
    join recognized fragments by their reading order.
    """
    if crop is None or getattr(crop, "size", 0) == 0:
        return ""
    engine = _get_ocr_engine()
    result, _elapse = engine(crop)
    if not result:
        return ""
    parts = []
    for item in result:
        # item: [box, text, score]
        if len(item) >= 2 and item[1]:
            parts.append(str(item[1]).strip())
    return " ".join(parts).strip().upper()


# ── Fuzzy canonical match ─────────────────────────────────────────────────────


def _entity_tag(entity: Any) -> Optional[str]:
    """Read a tag from a canonical entity (dict or object)."""
    if isinstance(entity, dict):
        return entity.get("tag")
    return getattr(entity, "tag", None)


def _entity_id(entity: Any) -> Optional[str]:
    if isinstance(entity, dict):
        eid = entity.get("entity_id")
    else:
        eid = getattr(entity, "entity_id", None)
    return str(eid) if eid is not None else None


def link_to_canonical(
    ocr_tag: str, canonical_entities: Sequence[Any]
) -> Tuple[Optional[str], Optional[str], str]:
    """Fuzzy-match an OCR'd tag to a canonical entity by Levenshtein distance.

    Returns ``(entity_id, matched_tag, quality)``:
      - distance ≤ 2 → ``MATCH``
      - distance ≤ 4 → ``WEAK_MATCH``
      - otherwise    → ``NONE`` (entity_id/tag None)

    Empty ``ocr_tag`` → ``(None, None, NONE)`` (caller should try class fallback).
    """
    if not ocr_tag:
        return None, None, NONE

    from rapidfuzz.distance import Levenshtein

    best_dist = None
    best_entity = None
    target = ocr_tag.strip().upper()
    for ent in canonical_entities:
        tag = _entity_tag(ent)
        if not tag:
            continue
        dist = Levenshtein.distance(target, str(tag).strip().upper())
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_entity = ent

    if best_entity is None or best_dist is None:
        return None, None, NONE

    if best_dist <= 2:
        return _entity_id(best_entity), _entity_tag(best_entity), MATCH
    if best_dist <= 4:
        return _entity_id(best_entity), _entity_tag(best_entity), WEAK_MATCH
    return None, None, NONE


def class_prior_link(
    label: Optional[str], canonical_entities: Sequence[Any], consumed: set
) -> Tuple[Optional[str], Optional[str], str]:
    """Fallback when OCR is empty: pick an unconsumed canonical entity whose
    class (and sub_class if available) matches the YOLO class prior.

    ``consumed`` is a set of already-assigned entity_ids, mutated in place.
    Returns ``(entity_id, tag, CLASS_FALLBACK)`` or ``(None, None, NONE)``.
    """
    cls, sub = yolo_class_to_canonical(label)
    if not cls:
        return None, None, NONE

    def _ent_attr(ent, key):
        return ent.get(key) if isinstance(ent, dict) else getattr(ent, key, None)

    # Pass 1: class + sub_class exact.
    for ent in canonical_entities:
        eid = _entity_id(ent)
        if eid is None or eid in consumed:
            continue
        if _ent_attr(ent, "entity_class") != cls:
            continue
        if sub and (str(_ent_attr(ent, "sub_class") or "").upper() != sub):
            continue
        consumed.add(eid)
        return eid, _entity_tag(ent), CLASS_FALLBACK

    # Pass 2: class-only (sub_class didn't match anything).
    if sub:
        for ent in canonical_entities:
            eid = _entity_id(ent)
            if eid is None or eid in consumed:
                continue
            if _ent_attr(ent, "entity_class") != cls:
                continue
            consumed.add(eid)
            return eid, _entity_tag(ent), CLASS_FALLBACK

    return None, None, NONE


def link_detection(
    image: np.ndarray,
    detection: Dict[str, Any],
    canonical_entities: Sequence[Any],
    consumed: set,
) -> Tuple[Optional[str], Optional[str], str]:
    """Full link strategy for one detection: OCR → fuzzy match → class fallback.

    A node is always linkable to *something* or remains unlinked (tag/entity
    None) — never raises. ``consumed`` tracks class-fallback assignments so two
    same-class detections don't grab the same entity.
    """
    bbox = detection.get("bbox") or detection.get("bbox_tile")
    label = detection.get("label") or detection.get("yolo_class")

    ocr_tag = ""
    if bbox is not None and image is not None and getattr(image, "size", 0) > 0:
        try:
            crop = crop_bbox(image, bbox)
            ocr_tag = ocr_crop(crop)
        except Exception:
            ocr_tag = ""

    if ocr_tag:
        eid, tag, quality = link_to_canonical(ocr_tag, canonical_entities)
        if eid is not None:
            consumed.add(eid)
            return eid, tag, quality
        # OCR produced text but no canonical hit — still try class fallback.

    return class_prior_link(label, canonical_entities, consumed)
