"""Single source of truth for the P&ID symbol taxonomy.

Reads ``webapp/config/taxonomy.json`` once (cached) and exposes accessors that
every consumer (inference class list, YOLO->canonical routing, palette colors,
display names, glyphs) will read in later phases. Phase 1 ships the module +
parity tests only; no consumer is switched yet.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def load_taxonomy() -> Dict[str, Any]:
    """Return the parsed taxonomy dict (cached, thread-safe)."""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        with _TAXONOMY_PATH.open() as fh:
            _cache = json.load(fh)
        return _cache


def class_names() -> List[str]:
    """Ordered YOLO labels (ONNX channel order). Equivalent to the legacy
    ``inference.CLASS_NAMES`` constant."""
    classes = sorted(load_taxonomy()["classes"], key=lambda c: c["order"])
    return [c["yolo_label"] for c in classes]


def yolo_to_canonical(label: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Map a YOLO class string to ``(entity_class, sub_class_or_None)`` using the
    file's ``yolo_routing`` rules. Returns ``(None, None)`` for arrows,
    connectors, and unknown labels. Behaviour-equivalent to the legacy
    ``api_v1._yolo_class_to_canonical``."""
    if not label:
        return None, None
    for rule in load_taxonomy()["yolo_routing"]:
        matched = (
            (rule["match"] == "prefix" and label.startswith(rule["value"]))
            or (rule["match"] == "exact" and label == rule["value"])
        )
        if not matched:
            continue
        entity_class = rule["entity_class"]
        sub = rule["sub_class"]
        if sub == "suffix_upper":
            sub = label[len(rule["value"]):].upper()
        return entity_class, sub
    return None, None


def _by_class_sub(entity_class: Optional[str], sub_class: Optional[str]) -> Optional[Dict[str, Any]]:
    for c in load_taxonomy()["classes"]:
        if c["entity_class"] == entity_class and c["sub_class"] == sub_class:
            return c
    return None


def display_name(entity_class: Optional[str], sub_class: Optional[str]) -> Optional[str]:
    c = _by_class_sub(entity_class, sub_class)
    return c["display_name"] if c else None


def color(entity_class: Optional[str], sub_class: Optional[str]) -> Optional[str]:
    c = _by_class_sub(entity_class, sub_class)
    return c["color"] if c else None


def glyph_kind(entity_class: Optional[str], sub_class: Optional[str]) -> Optional[str]:
    c = _by_class_sub(entity_class, sub_class)
    return c["glyph_kind"] if c else None
