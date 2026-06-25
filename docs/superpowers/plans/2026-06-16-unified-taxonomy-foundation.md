# Unified Taxonomy Foundation (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a single source-of-truth symbol taxonomy (`taxonomy.json` + `webapp/taxonomy.py`) proven byte-for-byte equivalent to today's scattered class lists, with **no consumer switched yet**.

**Architecture:** File-first source of truth (`webapp/config/taxonomy.json`), read through a small cached Python module (`webapp/taxonomy.py`). Parity tests assert the module reproduces the current `inference.py:CLASS_NAMES` ordering and the current `api_v1.py:_yolo_class_to_canonical()` routing exactly. Consumers are switched in later phases — this phase is purely additive and safe to merge.

**Tech Stack:** Python 3.12 (server) / 3.9 (local), pytest, stdlib `json`. No new dependencies.

**Branch:** `feat/taxonomy-foundation` off `dev`. Merge via PR (CLAUDE.md feature-branch policy). Do NOT commit directly to `dev`.

**Reference docs:** spec at `docs/superpowers/specs/2026-06-16-unified-taxonomy-design.md`. Current lists: `webapp/inference.py:65-92` (CLASS_NAMES), `webapp/routers/api_v1.py:264-283` (`_yolo_class_to_canonical`).

---

## File Structure

> **Gotcha (hit during execution):** do NOT create `webapp/config/` as a package
> — a `webapp/config.py` module already exists (exports `DATABASE_URL`), and a
> `webapp/config/` directory shadows it, breaking the app's config import. The
> taxonomy file therefore lives at **`webapp/taxonomy.json`**, alongside
> `webapp/taxonomy.py` (loader path `Path(__file__).parent / "taxonomy.json"`).

- **Create** `webapp/taxonomy.json` — the source of truth: ordered YOLO classes + routing rules + per-class metadata (color/glyph/display seeded for later phases but unused this phase).
- **Create** `webapp/taxonomy.py` — loader + accessors: `load_taxonomy()`, `class_names()`, `yolo_to_canonical()`, `display_name()`, `color()`, `glyph_kind()`.
- **Create** `tests/unit/test_taxonomy.py` — unit tests for the module.
- **Create** `tests/unit/test_taxonomy_parity.py` — parity tests vs the current hard-coded lists (the safety gate).

No existing files are modified in Phase 1.

---

## Task 1: Taxonomy source file + package marker

**Files:**
- Create: `webapp/config/__init__.py`
- Create: `webapp/config/taxonomy.json`

- [ ] **Step 1: Create the package marker**

Create `webapp/config/__init__.py` with a single comment line:

```python
# Package marker so webapp.config resolves; taxonomy.json lives alongside.
```

- [ ] **Step 2: Author `webapp/config/taxonomy.json`**

The 23 classes mirror `inference.py:CLASS_NAMES` in exact order (the `order` field = ONNX channel index — must not change). `sub_class` for valves is the label suffix upper-cased; instruments/equipment have `sub_class: null` (their sub_class comes from OCR downstream, not the model). `color`/`glyph_kind`/`display_name` are seeded from `paletteColors.ts`/`labelMap.ts`/`PidSymbol.subClassToSymKind` for later phases; they are NOT read in Phase 1.

```json
{
  "schema_version": 1,
  "classes": [
    {"order": 0,  "yolo_label": "valve_bv",            "entity_class": "valve",      "sub_class": "BV",            "display_name": "Ball Valve",            "color": "#86D8C4", "glyph_kind": "valve_bv"},
    {"order": 1,  "yolo_label": "valve_ncbv",          "entity_class": "valve",      "sub_class": "NCBV",          "display_name": "NC Ball Valve",         "color": "#86A8E8", "glyph_kind": "valve_bv"},
    {"order": 2,  "yolo_label": "valve_gt",            "entity_class": "valve",      "sub_class": "GT",            "display_name": "Gate Valve",            "color": "#7EC9C2", "glyph_kind": "valve_gt"},
    {"order": 3,  "yolo_label": "valve_bf",            "entity_class": "valve",      "sub_class": "BF",            "display_name": "Butterfly Valve",       "color": "#FF6B6B", "glyph_kind": "valve_bf"},
    {"order": 4,  "yolo_label": "valve_ck",            "entity_class": "valve",      "sub_class": "CK",            "display_name": "Check Valve",           "color": "#D8C794", "glyph_kind": "valve_ck"},
    {"order": 5,  "yolo_label": "valve_db",            "entity_class": "valve",      "sub_class": "DB",            "display_name": "Double Block",          "color": "#7FD4D2", "glyph_kind": "valve_gen"},
    {"order": 6,  "yolo_label": "valve_relief_safety", "entity_class": "valve",      "sub_class": "RELIEF_SAFETY", "display_name": "Relief/Safety Valve",   "color": "#A8DD92", "glyph_kind": "valve_gen"},
    {"order": 7,  "yolo_label": "valve_gl",            "entity_class": "valve",      "sub_class": "GL",            "display_name": "Globe Valve",           "color": "#A8DD92", "glyph_kind": "valve_gl"},
    {"order": 8,  "yolo_label": "valve_3way_relief",   "entity_class": "valve",      "sub_class": "3WAY_RELIEF",   "display_name": "3-Way Relief Valve",    "color": "#C49AE2", "glyph_kind": "valve_gen"},
    {"order": 9,  "yolo_label": "inst_field",          "entity_class": "instrument", "sub_class": null,            "display_name": "Field Instrument",      "color": "#E5CBA0", "glyph_kind": "inst_field"},
    {"order": 10, "yolo_label": "inst_bpcs",           "entity_class": "instrument", "sub_class": null,            "display_name": "BPCS Instrument",       "color": "#C5BCEC", "glyph_kind": "inst_field"},
    {"order": 11, "yolo_label": "Motor",               "entity_class": "equipment",  "sub_class": null,            "display_name": "Motor",                 "color": "#8CCC76", "glyph_kind": "valve_gen"},
    {"order": 12, "yolo_label": "Pump/Dwg Pump",       "entity_class": "equipment",  "sub_class": null,            "display_name": "Pump",                  "color": "#8CCC76", "glyph_kind": "pump"},
    {"order": 13, "yolo_label": "inst_sis",            "entity_class": "instrument", "sub_class": null,            "display_name": "SIS Instrument",        "color": "#8585D6", "glyph_kind": "inst_field"},
    {"order": 14, "yolo_label": "SIS-R",               "entity_class": "instrument", "sub_class": null,            "display_name": "SIS Relay",             "color": "#B4ACE6", "glyph_kind": "inst_field"},
    {"order": 15, "yolo_label": "interlock",           "entity_class": "instrument", "sub_class": null,            "display_name": "Interlock",             "color": "#EC9696", "glyph_kind": "inst_field"},
    {"order": 16, "yolo_label": "inst_local_panel",    "entity_class": "instrument", "sub_class": null,            "display_name": "Local Panel",           "color": "#C6C6CE", "glyph_kind": "inst_field"},
    {"order": 17, "yolo_label": "arrow_up",            "entity_class": null,         "sub_class": null,            "display_name": "Arrow Up",              "color": "#9498AE", "glyph_kind": "valve_gen"},
    {"order": 18, "yolo_label": "arrow_left",          "entity_class": null,         "sub_class": null,            "display_name": "Arrow Left",            "color": "#9498AE", "glyph_kind": "valve_gen"},
    {"order": 19, "yolo_label": "arrow_right",         "entity_class": null,         "sub_class": null,            "display_name": "Arrow Right",           "color": "#9498AE", "glyph_kind": "valve_gen"},
    {"order": 20, "yolo_label": "arrow_down",          "entity_class": null,         "sub_class": null,            "display_name": "Arrow Down",            "color": "#9498AE", "glyph_kind": "valve_gen"},
    {"order": 21, "yolo_label": "connector_out",       "entity_class": null,         "sub_class": null,            "display_name": "Connector Out",         "color": "#9498AE", "glyph_kind": "valve_gen"},
    {"order": 22, "yolo_label": "connector_in",        "entity_class": null,         "sub_class": null,            "display_name": "Connector In",          "color": "#9498AE", "glyph_kind": "valve_gen"}
  ],
  "yolo_routing": [
    {"match": "prefix", "value": "valve_",     "entity_class": "valve",      "sub_class": "suffix_upper"},
    {"match": "prefix", "value": "inst_",      "entity_class": "instrument", "sub_class": null},
    {"match": "exact",  "value": "interlock",  "entity_class": "instrument", "sub_class": null},
    {"match": "exact",  "value": "SIS-R",      "entity_class": "instrument", "sub_class": null},
    {"match": "exact",  "value": "Motor",          "entity_class": "equipment", "sub_class": null},
    {"match": "exact",  "value": "Pump/Dwg Pump",  "entity_class": "equipment", "sub_class": null},
    {"match": "exact",  "value": "Pump_Dwg_Pump",  "entity_class": "equipment", "sub_class": null},
    {"match": "prefix", "value": "arrow_",     "entity_class": null, "sub_class": null},
    {"match": "prefix", "value": "connector_", "entity_class": null, "sub_class": null}
  ]
}
```

- [ ] **Step 3: Verify JSON is valid**

Run: `python3 -c "import json; d=json.load(open('webapp/config/taxonomy.json')); print(len(d['classes']), 'classes', len(d['yolo_routing']), 'rules')"`
Expected: `23 classes 9 rules`

- [ ] **Step 4: Commit**

```bash
git add webapp/config/__init__.py webapp/config/taxonomy.json
git commit -m "feat(taxonomy): add taxonomy.json source of truth (Phase 1, no consumer switch)"
```

---

## Task 2: `webapp/taxonomy.py` loader + accessors (TDD)

**Files:**
- Create: `webapp/taxonomy.py`
- Test: `tests/unit/test_taxonomy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_taxonomy.py`:

```python
from webapp import taxonomy


def test_class_names_order_and_count():
    names = taxonomy.class_names()
    assert len(names) == 23
    assert names[0] == "valve_bv"
    assert names[12] == "Pump/Dwg Pump"
    assert names[22] == "connector_in"


def test_yolo_to_canonical_valve_suffix_upper():
    assert taxonomy.yolo_to_canonical("valve_bv") == ("valve", "BV")
    assert taxonomy.yolo_to_canonical("valve_relief_safety") == ("valve", "RELIEF_SAFETY")
    assert taxonomy.yolo_to_canonical("valve_3way_relief") == ("valve", "3WAY_RELIEF")


def test_yolo_to_canonical_instrument_and_equipment():
    assert taxonomy.yolo_to_canonical("inst_field") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("interlock") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("SIS-R") == ("instrument", None)
    assert taxonomy.yolo_to_canonical("Motor") == ("equipment", None)
    assert taxonomy.yolo_to_canonical("Pump/Dwg Pump") == ("equipment", None)
    assert taxonomy.yolo_to_canonical("Pump_Dwg_Pump") == ("equipment", None)


def test_yolo_to_canonical_non_entities_and_unknown():
    assert taxonomy.yolo_to_canonical("arrow_up") == (None, None)
    assert taxonomy.yolo_to_canonical("connector_in") == (None, None)
    assert taxonomy.yolo_to_canonical("totally_unknown") == (None, None)
    assert taxonomy.yolo_to_canonical(None) == (None, None)
    assert taxonomy.yolo_to_canonical("") == (None, None)


def test_metadata_accessors():
    assert taxonomy.display_name("valve", "BV") == "Ball Valve"
    assert taxonomy.color("valve", "BF") == "#FF6B6B"
    assert taxonomy.glyph_kind("instrument", None) in {"inst_field"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/unit/test_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.taxonomy'`

- [ ] **Step 3: Implement `webapp/taxonomy.py`**

```python
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

_TAXONOMY_PATH = Path(__file__).parent / "config" / "taxonomy.json"

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/unit/test_taxonomy.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add webapp/taxonomy.py tests/unit/test_taxonomy.py
git commit -m "feat(taxonomy): webapp/taxonomy.py loader + accessors (Phase 1)"
```

---

## Task 3: Parity tests — the safety gate

**Files:**
- Test: `tests/unit/test_taxonomy_parity.py`

This proves the new module reproduces the current behaviour exactly, so later
phases can switch consumers with confidence. It imports BOTH the new module and
the legacy constants/function and asserts equivalence.

- [ ] **Step 1: Write the parity tests**

Create `tests/unit/test_taxonomy_parity.py`:

```python
"""Parity gate: the taxonomy module must reproduce today's hard-coded lists
exactly. If these fail, do NOT switch consumers — fix taxonomy.json first."""
from webapp import taxonomy
from webapp.inference import CLASS_NAMES
from webapp.routers.api_v1 import _yolo_class_to_canonical


def test_class_names_match_inference_constant():
    # Same labels in the same ONNX channel order.
    assert taxonomy.class_names() == list(CLASS_NAMES)


def test_routing_matches_legacy_for_every_known_label():
    for label in CLASS_NAMES:
        assert taxonomy.yolo_to_canonical(label) == _yolo_class_to_canonical(label), label


def test_routing_matches_legacy_for_edge_cases():
    edge_labels = [
        None, "", "valve_", "valve_bv", "valve_3way_relief", "Pump_Dwg_Pump",
        "Pump/Dwg Pump", "SIS-R", "interlock", "arrow_up", "connector_in",
        "totally_unknown", "inst_", "inst_field",
    ]
    for label in edge_labels:
        assert taxonomy.yolo_to_canonical(label) == _yolo_class_to_canonical(label), label
```

- [ ] **Step 2: Run the parity tests**

Run: `python3 -m pytest tests/unit/test_taxonomy_parity.py -v`
Expected: PASS (3 tests). If `test_class_names_match_inference_constant` fails,
the `order`/labels in `taxonomy.json` diverge from `inference.CLASS_NAMES` — fix
the JSON, not the test.

- [ ] **Step 3: Run the full unit suite to confirm no import side-effects**

Run: `python3 -m pytest tests/unit/test_taxonomy.py tests/unit/test_taxonomy_parity.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_taxonomy_parity.py
git commit -m "test(taxonomy): parity gate vs inference.CLASS_NAMES + legacy routing"
```

---

## Self-Review

**Spec coverage (Phase 1 scope only):**
- "One source of truth file" → Task 1 (`taxonomy.json`). ✓
- "Backend module single import surface" → Task 2 (`webapp/taxonomy.py` with `class_names`, `yolo_to_canonical`, metadata accessors). ✓
- "Parity tests gate the change" → Task 3. ✓
- Out of Phase 1 (later plans): consumer switches (inference.py, api_v1 routing), frontend generated module, triage DB/API/UI, LS XML generation. Explicitly deferred — see spec Rollout phases 2–4.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. ✓

**Type consistency:** `yolo_to_canonical` returns `(Optional[str], Optional[str])` in both the module and tests; `class_names()` returns `List[str]`; accessor names (`display_name`/`color`/`glyph_kind`) consistent between module and `test_taxonomy.py`. The `sub_class: "suffix_upper"` sentinel in the JSON is consumed only in `yolo_to_canonical`. ✓

**Note for the engineer:** `webapp.inference` imports `onnxruntime`/`numpy` lazily (guarded), so importing `CLASS_NAMES` in the parity test does NOT require the native ONNX wheel — the constant is module-level. If the import still fails locally, run inside the web container (`docker compose exec web python3 -m pytest ...`).
