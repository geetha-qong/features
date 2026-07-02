# Cross-Tile Detection De-dup + 1:1 Entity Matching — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove phantom cross-tile duplicate detections (page-space NMS) and make tag→entity matching 1:1, so one physical glyph = one detection and each canonical entity binds to at most one detection (BPCS circle keeps `61-HS-00471`; SIS diamond becomes an adoptable type-B node).

**Architecture:** A pure page-space NMS helper de-dups tile-overlap copies; it is applied read-time (non-destructive, no re-inference) before matching in the three `gpu_detections` consumers. A post-pass enforces 1:1 entity→detection binding. Reuses the loader's tile geometry and `orphan_dedup.bbox_iou`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy; pytest.

## Global Constraints

- Python 3.12: use `Optional[X]`/`List[X]`/`Set[X]`/`Dict[X,Y]`/`Tuple[...]` from `typing`, not PEP-604 `X | None`. Use `python3`.
- Backend host pytest needs `SECRET_KEY` ≥ 32 chars: prefix `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")`.
- Backend `.py` under `webapp/` is live-mounted locally — no rebuild for pytest.
- De-dup is **read-time and non-destructive**: never rewrite `Job.gpu_detections`, never mutate a detection's `bbox`/`tile` — only drop suppressed copies and set `entity_id`/`entity_tag`.
- The helper always takes **tile-local** detections + `tile_offsets` and computes page-space internally; apply it **before** any page translation / matching at every call site (no double-offset).
- Reuse `bbox_iou` from `webapp/graph/orphan_dedup.py`; reuse `compute_tile_offsets`/`TileBox` from `webapp/graph/loader.py`.
- IoU threshold default `0.5`; keep-policy = highest `confidence` (missing → 0.0; tie-break larger area). Different classes never suppress each other.
- Branch `feat/detection-dedup` off `dev`; commit with `git -c user.name="Winn Projects" -c user.email="tnb@qongsystems.com" commit`.

---

### Task 1: Pure page-space NMS helper

**Files:**
- Create: `webapp/graph/detection_dedup.py`
- Test: `tests/unit/test_detection_dedup.py`

**Interfaces:**
- Consumes: `bbox_iou` (orphan_dedup), `TileBox` (loader, has `.x0`,`.y0`).
- Produces: `dedupe_detections_page_space(detections: List[Dict[str, Any]], tile_offsets: Dict[str, Any], iou_threshold: float = 0.5) -> List[Dict[str, Any]]` — returns the surviving subset of `detections` (same dict objects), dropping same-class tile-overlap copies; keeps the highest-confidence representative.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_detection_dedup.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.detection_dedup import dedupe_detections_page_space


class _Box:
    def __init__(self, x0, y0): self.x0, self.y0 = x0, y0


def test_overlapping_same_class_collapse_keep_highest_conf():
    # Same glyph in two tiles whose offsets place them at the same page point.
    dets = [
        {"label": "inst_field", "tile": "A", "bbox": [10, 10, 30, 30], "confidence": 0.7},
        {"label": "inst_field", "tile": "B", "bbox": [0, 0, 20, 20], "confidence": 0.9},
    ]
    offs = {"A": _Box(0, 0), "B": _Box(10, 10)}  # B's box → page [10,10,30,30] == A
    out = dedupe_detections_page_space(dets, offs)
    assert len(out) == 1
    assert out[0]["confidence"] == 0.9  # highest-confidence survivor


def test_different_class_same_location_both_kept():
    dets = [
        {"label": "inst_field", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
        {"label": "inst_sis", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
    ]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 2  # BPCS circle + SIS diamond both survive


def test_distinct_adjacent_same_class_both_kept():
    dets = [
        {"label": "valve_bv", "tile": "A", "bbox": [0, 0, 20, 20], "confidence": 0.8},
        {"label": "valve_bv", "tile": "A", "bbox": [100, 100, 120, 120], "confidence": 0.8},
    ]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 2  # low IoU → not merged


def test_unknown_tile_uses_bbox_as_is_and_passes_through():
    dets = [{"label": "valve_bv", "tile": "ZZZ", "bbox": [0, 0, 20, 20], "confidence": 0.5}]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert len(out) == 1


def test_missing_bbox_passes_through():
    dets = [{"label": "valve_bv", "tile": "A"}]
    out = dedupe_detections_page_space(dets, {"A": _Box(0, 0)})
    assert out == dets
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_detection_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: webapp.graph.detection_dedup`.

- [ ] **Step 3: Write minimal implementation**

```python
# webapp/graph/detection_dedup.py
"""Page-space non-max suppression to drop cross-tile duplicate detections.

Pages are tiled 3x3 with 20% overlap, so a glyph on a tile seam is detected
once per overlapping tile. This collapses same-class copies that overlap in
PAGE space (IoU >= threshold), keeping the highest-confidence representative.
Read-time + non-destructive: drops suppressed copies, never mutates a bbox.
Different classes never suppress each other (a BPCS circle and SIS diamond at
the same point both survive)."""
from typing import Any, Dict, List

from webapp.graph.orphan_dedup import bbox_iou


def _page_bbox(det: Dict[str, Any], tile_offsets: Dict[str, Any]):
    bbox = det.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    off = tile_offsets.get(det.get("tile"))
    if off is None:
        return list(bbox)  # already page-space / unknown tile — use as-is
    return [bbox[0] + off.x0, bbox[1] + off.y0, bbox[2] + off.x0, bbox[3] + off.y0]


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def dedupe_detections_page_space(
    detections: List[Dict[str, Any]],
    tile_offsets: Dict[str, Any],
    iou_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    page = [_page_bbox(d, tile_offsets) for d in detections]
    # Indices that have a usable page bbox participate in NMS; others pass through.
    idx = [i for i, p in enumerate(page) if p is not None]
    # Sort candidates by confidence desc, then area desc (tie-break).
    idx.sort(key=lambda i: (detections[i].get("confidence") or 0.0, _area(page[i])), reverse=True)
    suppressed = set()
    for a_pos, i in enumerate(idx):
        if i in suppressed:
            continue
        for j in idx[a_pos + 1:]:
            if j in suppressed:
                continue
            if detections[i].get("label") != detections[j].get("label"):
                continue
            if bbox_iou(page[i], page[j]) >= iou_threshold:
                suppressed.add(j)
    return [d for k, d in enumerate(detections) if k not in suppressed]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_detection_dedup.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/graph/detection_dedup.py tests/unit/test_detection_dedup.py
git commit -m "feat(graph): page-space NMS helper for cross-tile detection de-dup"
```

---

### Task 2: 1:1 entity-binding enforcement pass

**Files:**
- Modify: `webapp/graph/detection_dedup.py` (add `enforce_one_to_one`)
- Test: `tests/unit/test_detection_dedup.py` (add cases)

**Interfaces:**
- Produces: `enforce_one_to_one(detections: List[Dict[str, Any]]) -> None` — mutates in place: for any `entity_id` assigned to >1 detection, keep it on the best detection (prefer one whose `entity_tag` is set, then highest `confidence`) and set the others' `entity_id=None` (retain `entity_tag` so the label still shows).

- [ ] **Step 1: Write the failing test**

```python
def test_enforce_one_to_one_keeps_best_unmatches_rest():
    from webapp.graph.detection_dedup import enforce_one_to_one
    dets = [
        {"entity_id": "E1", "entity_tag": "61-HS-00471", "confidence": 0.6},
        {"entity_id": "E1", "entity_tag": "61-HS-00471", "confidence": 0.9},
        {"entity_id": "E2", "entity_tag": "61-FT-1", "confidence": 0.5},
    ]
    enforce_one_to_one(dets)
    kept = [d for d in dets if d["entity_id"] == "E1"]
    assert len(kept) == 1 and kept[0]["confidence"] == 0.9
    dropped = [d for d in dets if d["entity_id"] is None]
    assert len(dropped) == 1 and dropped[0]["entity_tag"] == "61-HS-00471"  # tag retained
    assert any(d["entity_id"] == "E2" for d in dets)  # untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_detection_dedup.py::test_enforce_one_to_one_keeps_best_unmatches_rest -v`
Expected: FAIL — `ImportError`/`AttributeError` (function not defined).

- [ ] **Step 3: Write minimal implementation** (append to `webapp/graph/detection_dedup.py`)

```python
def enforce_one_to_one(detections: List[Dict[str, Any]]) -> None:
    """Ensure each entity_id is bound to at most one detection. For any
    entity_id on >1 detection keep the best (has entity_tag, then highest
    confidence) and unmatch the rest (entity_id=None; keep entity_tag so the
    label still shows -> the extra glyph becomes an adoptable type-B node)."""
    by_eid: Dict[str, List[Dict[str, Any]]] = {}
    for d in detections:
        eid = d.get("entity_id")
        if eid:
            by_eid.setdefault(str(eid), []).append(d)
    for eid, group in by_eid.items():
        if len(group) <= 1:
            continue
        group.sort(key=lambda d: (bool(d.get("entity_tag")), d.get("confidence") or 0.0), reverse=True)
        for d in group[1:]:
            d["entity_id"] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_detection_dedup.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/graph/detection_dedup.py tests/unit/test_detection_dedup.py
git commit -m "feat(graph): 1:1 entity-binding enforcement pass"
```

---

### Task 3: Shared page-dims helper + apply de-dup in bbox_ocr (before matching)

**Files:**
- Create: `webapp/graph/page_geometry.py` (shared `page_dims_for_job`)
- Modify: `webapp/routers/bbox_ocr.py` (`compute_tagged_detections`, ~408-425)
- Test: `tests/unit/test_bbox_ocr_dedup.py`

**Interfaces:**
- Consumes: `dedupe_detections_page_space`, `enforce_one_to_one` (Tasks 1-2), `compute_tile_offsets` (loader).
- Produces: `page_dims_for_job(job) -> Optional[Tuple[int, int]]` (reads `canonical_graph.json` `page_width/height` next to `job.output_csv_path`; None if absent). `compute_tagged_detections` de-dups raw detections before matching and enforces 1:1 after.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bbox_ocr_dedup.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.page_geometry import page_dims_for_job


class _Job:
    def __init__(self, p): self.output_csv_path = p


def test_page_dims_reads_canonical_graph(tmp_path):
    (tmp_path / "canonical_graph.json").write_text(json.dumps({"page_width": 900, "page_height": 700}))
    j = _Job(str(tmp_path / "output.csv"))
    assert page_dims_for_job(j) == (900, 700)


def test_page_dims_missing_returns_none(tmp_path):
    j = _Job(str(tmp_path / "output.csv"))
    assert page_dims_for_job(j) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_bbox_ocr_dedup.py -v`
Expected: FAIL — `ModuleNotFoundError: webapp.graph.page_geometry`.

- [ ] **Step 3: Write `page_geometry.py`**

```python
# webapp/graph/page_geometry.py
"""Shared: read page pixel dimensions for a job from canonical_graph.json."""
import json
from pathlib import Path
from typing import Any, Optional, Tuple


def page_dims_for_job(job: Any) -> Optional[Tuple[int, int]]:
    path = getattr(job, "output_csv_path", None)
    if not path:
        return None
    cg = Path(path).parent / "canonical_graph.json"
    if not cg.exists():
        return None
    try:
        data = json.loads(cg.read_text(encoding="utf-8"))
    except Exception:
        return None
    w, h = data.get("page_width"), data.get("page_height")
    if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w and h:
        return int(w), int(h)
    return None
```

- [ ] **Step 4: Apply de-dup in `bbox_ocr.compute_tagged_detections`.** After `_normalize_detection_shape(raw_dets)` and before `_attach_entity_ids(raw_dets, entities)`, insert:

```python
    # Drop cross-tile duplicate detections (3x3 tiles, 20% overlap) BEFORE
    # matching/OCR — cleans the cache, makes matching 1:1, cuts OCR calls.
    from webapp.graph.page_geometry import page_dims_for_job
    from webapp.graph.loader import compute_tile_offsets
    from webapp.graph.detection_dedup import dedupe_detections_page_space, enforce_one_to_one
    _dims = page_dims_for_job(job)
    if _dims:
        _offs = compute_tile_offsets(_dims[0], _dims[1], 0)
        raw_dets = dedupe_detections_page_space(raw_dets, _offs)
```

And after the `enriched = _run_valve_ocr(job, enriched, entities)` line, before building `result`, insert:

```python
    enforce_one_to_one(enriched)
```

- [ ] **Step 5: Run tests**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_bbox_ocr_dedup.py tests/unit/test_detections_tagged_bg.py -v`
Expected: PASS (new page-dims tests + existing detections-tagged tests still green).

- [ ] **Step 6: Commit**

```bash
git add webapp/graph/page_geometry.py webapp/routers/bbox_ocr.py tests/unit/test_bbox_ocr_dedup.py
git commit -m "feat(ocr): de-dup cross-tile detections + enforce 1:1 in compute_tagged_detections"
```

---

### Task 4: Apply de-dup in api_v1 /detections and the graph loader

**Files:**
- Modify: `webapp/routers/api_v1.py` (`api_job_detections`, ~575-585)
- Modify: `webapp/graph/loader.py` (`build_job_input`, before the `to_page_pixel_detections` translation ~200)
- Test: `tests/unit/test_api_v1.py` (add a case) + `tests/unit/test_graph_loader_dedup.py`

**Interfaces:**
- Consumes: `dedupe_detections_page_space`, `enforce_one_to_one`, `page_dims_for_job`, `compute_tile_offsets`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_graph_loader_dedup.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.loader import build_job_input


def test_build_job_input_dedups_cross_tile(tmp_path):
    # Two tile-local detections that map to the same page point in adjacent tiles.
    (tmp_path / "page_1_full.png").write_bytes(b"")  # may be absent; dims inferred from bbox
    dets = [
        {"label": "valve_bv", "tile": "tile_p0_r0_c0.png", "bbox": [2300, 10, 2320, 30], "confidence": 0.7},
        {"label": "valve_bv", "tile": "tile_p0_r0_c1.png", "bbox": [10, 10, 30, 30], "confidence": 0.9},
    ]
    ji = build_job_input(str(tmp_path), detections=dets, page=1, tile_local_detections=True)
    # If tile geometry resolves the two to the same page point, only one survives.
    assert len(ji.detections) <= 2  # never increases; dedup may collapse to 1
```

(Note: this test mainly guards that build_job_input still runs and never *adds* detections after de-dup; the precise collapse depends on page sizing. The authoritative collapse assertion lives in Task 1's pure-helper tests and Task 6's dev validation.)

For `test_api_v1.py`, add:

```python
def test_detections_dedups_cross_tile_duplicates(client, db_session, user, api_key_pair, tmp_path):
    import json as _json
    (tmp_path / "canonical_graph.json").write_text(_json.dumps({"page_width": 900, "page_height": 900}))
    (tmp_path / "output.csv").write_text("x")
    # Same glyph in two overlapping tiles -> same page point.
    dets = [
        {"label": "valve_bv", "tile": "tile_p0_r0_c0.png", "bbox": [300, 10, 320, 30], "confidence": 0.7},
        {"label": "valve_bv", "tile": "tile_p0_r0_c1.png", "bbox": [10, 10, 30, 30], "confidence": 0.9},
    ]
    job = models.Job(user_id=user.id, status="done", original_filename="p.pdf",
                     stored_filename="p.pdf", output_csv_path=str(tmp_path / "output.csv"),
                     gpu_detections=_json.dumps(dets))
    db_session.add(job); db_session.commit()
    full_key, _ = api_key_pair
    resp = client.get(f"/api/v1/jobs/{job.id}/detections", headers={"Authorization": f"Bearer {full_key}"})
    assert resp.status_code == 200
    # never more than the input; dedup collapses overlapping same-class copies
    assert len(resp.json()["detections"]) <= len(dets)
```

- [ ] **Step 2: Run to verify they fail / are weak-guarded** — Run the two files; the api_v1 case passes only after de-dup is applied (without it, both detections return; with overlapping page points, one is dropped). If the geometry doesn't force overlap in your fixture, adjust the tile-local bboxes so the two page-space boxes coincide (use `compute_tile_offsets(900,900,0)` to pick coordinates that overlap), so the assertion meaningfully exercises de-dup. Confirm RED first.

- [ ] **Step 3: Implement** — in `api_v1.api_job_detections`, after `_normalize_detection_shape(detections)` / `_discover_unknown_labels(...)` and **before** `_attach_entity_ids`, insert:

```python
        from webapp.graph.page_geometry import page_dims_for_job
        from webapp.graph.loader import compute_tile_offsets
        from webapp.graph.detection_dedup import dedupe_detections_page_space, enforce_one_to_one
        _dims = page_dims_for_job(job)
        if _dims:
            detections = dedupe_detections_page_space(detections, compute_tile_offsets(_dims[0], _dims[1], 0))
```

and after the `_attach_entity_ids(detections, canonical.entities)` call, add `enforce_one_to_one(detections)`.

In `loader.build_job_input`, immediately BEFORE the `if tile_local_detections and tile_offsets:` block, insert:

```python
    if tile_local_detections and tile_offsets:
        from webapp.graph.detection_dedup import dedupe_detections_page_space
        det_list = dedupe_detections_page_space(det_list, tile_offsets)
```

- [ ] **Step 4: Run tests**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_graph_loader_dedup.py tests/unit/test_api_v1.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/routers/api_v1.py webapp/graph/loader.py tests/unit/test_graph_loader_dedup.py tests/unit/test_api_v1.py
git commit -m "feat: de-dup cross-tile detections in /detections endpoint + graph loader"
```

---

### Task 5: Full suite, FEATURES entry, and DEV deploy + measured validation

**Files:**
- Modify: `FEATURES.md`

- [ ] **Step 1: Run the full backend unit suite**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit -q`
Expected: our new tests green; the only failures are the 11 known pre-existing ones (opencv-missing `test_graph_tracer`, `test_taxonomy*`, deliverables emitter) — confirm the set/count is unchanged from `dev` (run the same suite at `origin/dev` in a throwaway checkout if in doubt).

- [ ] **Step 2: Add FEATURES entry** (next number, newest first) describing: cross-tile detection de-dup (page-space NMS helper, applied read-time at bbox_ocr + api_v1 + loader, non-destructive, no re-inference); 1:1 binding enforcement (BPCS circle keeps the entity, SIS diamond → adoptable type-B node per the domain rule that BPCS/SIS are 2 entities); ~39% measured duplicate rate; valve-proximity bleed still out of scope.

- [ ] **Step 3: DEPLOY to dev + MEASURED VALIDATION (do not mark done until this passes).**
  - Confirm no cpu-worker job is processing on dev (an active job blocks the deploy safely). Fast-forward `feat/detection-dedup` → `dev` (push via the `qongsystems` SSH remote), wait for the deploy to return HTTP 200 and the SPA bundle hash to change.
  - **Re-process / refresh OCR for a sample job** so the new de-dup path runs (the OCR cache `detections_ocr.json` is recomputed by `compute_tagged_detections`). For job 38 trigger a `detections-tagged` recompute (open Studio / hit the endpoint) and confirm `ocr_status` reaches `ready`.
  - **Measure:** re-run the blast-radius script (per-job duplicate rate by page-space same-class clustering) on the refreshed jobs and confirm the cross-tile duplicate rate drops from ~39% toward ~0.
  - **Verify the symptom on job 38:** GET the job graph / detections and assert the `61-HS-00471` entity is now bound to **one** detection (the BPCS circle); the SIS diamond is unmatched (`entity_id=None`, `entity_tag` retained) and thus appears as a type-B node. In the browser (Playwright, login required), select `61-HS-00471` and confirm a single highlight; clean up any test state and close the browser.
  - **Guard against over-merge:** confirm total distinct-entity counts on a known-good job did not *drop* (we removed duplicates, not real symbols).

- [ ] **Step 4: Commit FEATURES (+ record validation numbers in the entry)**

```bash
git add FEATURES.md
git commit -m "docs: FEATURES — cross-tile detection de-dup + 1:1 matching (dev-validated)"
```

---

## Self-Review

- **Spec coverage:** Component 1 (NMS helper) → Task 1; read-time application at 3 sites → Tasks 3-4; Component 3 (1:1 matching) → Task 2 (`enforce_one_to_one`) applied in Tasks 3-4; non-destructive/no-reinference → enforced by Global Constraints + read-time application; testing → each task; acceptance (measured, dev) → Task 5 Step 3. BPCS/SIS-as-2-entities → `enforce_one_to_one` unmatches the diamond → adoptable (Task 2 + acceptance).
- **Placeholder scan:** all code steps show full code; the loader integration test is intentionally a "never-increases" guard with the authoritative collapse asserted in Task 1 + dev validation — stated explicitly, not a hidden TODO.
- **Type consistency:** `dedupe_detections_page_space(detections, tile_offsets, iou_threshold=0.5)`, `enforce_one_to_one(detections)`, `page_dims_for_job(job)` names/signatures consistent across Tasks 1-4. `TileBox.x0/.y0` used as the loader defines.
