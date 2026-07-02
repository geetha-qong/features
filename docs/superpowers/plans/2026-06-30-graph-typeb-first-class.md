# Type-B Graph Nodes → First-Class Entities — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user adopt a type-B graph node (a YOLO detection with no `entity_id`) so it becomes a full first-class entity — selectable/connectable/rejectable in the graph and present in the element list + all deliverables — with no duplicate node left in the graph or frozen GT.

**Architecture:** Adoption creates a *claiming* `UserAnnotation` (`linked_detection_index ≥ 0`, bbox preserved) which the already-merged `_sync_annotation_to_canonical` mirrors into `canonical.json` once tagged → deliverables. New work is graph-side: a shared bbox-IoU helper drops the superseded orphan auto-node (no `entity_id`) in both the live `GET /graph` merge and the freeze, reusing the existing reject-edge omission for dangling edges. A small UI affordance ("Confirm as &lt;class&gt;") triggers adoption.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy (backend), pytest; React + TypeScript + Vite + vitest (frontend).

## Global Constraints

- Python: use `Optional[X]` not `X | None`; `python3` not `python`.
- Backend host pytest needs `SECRET_KEY` ≥ 32 chars: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))")`.
- Local backend `.py` under `webapp/` is mounted — no rebuild for pytest; `docker compose restart web` only to pick up a running-server change.
- Frontend type-check: `npx tsc --noEmit` from `webapp/frontend/`; tests `npx vitest run`.
- Deliverables read `canonical.json` (file) + `entity_overrides`; do NOT add a second canonical-mutation path — reuse `_sync_annotation_to_canonical`.
- Adopted entity must preserve the node bbox (page-pixel); never write `(0,0,0,0)`.
- Branch: `feat/graph-typeb-first-class` off `dev`; PR back with 2 approvals.

---

### Task 1: bbox-IoU orphan-dedup helper (pure, shared)

**Files:**
- Create: `webapp/graph/orphan_dedup.py`
- Test: `tests/unit/test_orphan_dedup.py`

**Interfaces:**
- Produces: `bbox_iou(a: Sequence[float], b: Sequence[float]) -> float` and
  `superseded_auto_ids(auto_nodes: List[Dict], annotation_nodes: List[Dict], iou_threshold: float = 0.5) -> Set[str]`.
  An auto node is "superseded" iff it has no truthy `entity_id`, has a `bbox`, and its bbox
  IoU with any annotation node's bbox ≥ `iou_threshold`. Returns the set of superseded auto
  node `id`s.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_orphan_dedup.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from webapp.graph.orphan_dedup import bbox_iou, superseded_auto_ids


def test_bbox_iou_identical_is_one():
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0


def test_bbox_iou_disjoint_is_zero():
    assert bbox_iou([0, 0, 10, 10], [100, 100, 110, 110]) == 0.0


def test_orphan_superseded_by_overlapping_annotation():
    auto = [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [1, 1, 11, 11]}]  # high overlap
    assert superseded_auto_ids(auto, anns) == {"n_1"}


def test_auto_node_with_entity_id_never_superseded():
    auto = [{"id": "n_1", "entity_id": "e-keep", "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [0, 0, 10, 10]}]
    assert superseded_auto_ids(auto, anns) == set()


def test_low_overlap_not_superseded():
    auto = [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10]}]
    anns = [{"entity_id": "e-x", "bbox": [8, 8, 18, 18]}]  # small overlap
    assert superseded_auto_ids(auto, anns) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_orphan_dedup.py -v`
Expected: FAIL with `ModuleNotFoundError: webapp.graph.orphan_dedup`.

- [ ] **Step 3: Write minimal implementation**

```python
# webapp/graph/orphan_dedup.py
"""Drop orphan auto graph-nodes (no entity_id) superseded by an adopted
user-annotation node at the same position. Shared by the live GET /graph merge
and the frozen-GT builder so both stay identical (mirrors the reject-edge
omission pattern)."""
from typing import Any, Dict, List, Sequence, Set


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def superseded_auto_ids(
    auto_nodes: List[Dict[str, Any]],
    annotation_nodes: List[Dict[str, Any]],
    iou_threshold: float = 0.5,
) -> Set[str]:
    ann_boxes = [a.get("bbox") for a in annotation_nodes if a.get("bbox")]
    out: Set[str] = set()
    for n in auto_nodes:
        if (n.get("entity_id") or ""):
            continue  # has an entity — never an orphan
        box = n.get("bbox")
        nid = n.get("id")
        if not box or not nid:
            continue
        if any(bbox_iou(box, ab) >= iou_threshold for ab in ann_boxes):
            out.add(nid)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_orphan_dedup.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add webapp/graph/orphan_dedup.py tests/unit/test_orphan_dedup.py
git commit -m "feat(graph): bbox-IoU orphan-dedup helper for adopted nodes"
```

---

### Task 2: Apply orphan dedup in the live GET /graph merge

**Files:**
- Modify: `webapp/routers/graph.py` (merge region ~865-880, where `_canonical_eids` dedups annotation nodes and `reject_keys` is built)
- Test: `tests/unit/test_graph_orphan_dedup_merge.py`

**Interfaces:**
- Consumes: `superseded_auto_ids` (Task 1).
- Produces: `get_job_graph` drops superseded orphan auto-nodes and treats their ids as
  rejected for edge omission.

- [ ] **Step 1: Write the failing test** — a job whose graph has an orphan auto-node (no entity_id) plus an overlapping user annotation; assert the merged graph has exactly one node at that bbox and no edge dangles to the orphan.

```python
# tests/unit/test_graph_orphan_dedup_merge.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from webapp.database import Base
from webapp import models
from webapp.routers.graph import get_job_graph


@pytest.fixture()
def db_session(tmp_path):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close(); eng.dispose()


def _super_admin(db):
    u = models.User(username="sa", password_hash="x", credits_remaining=9, is_active=True, role="super_admin")
    db.add(u); db.commit(); db.refresh(u); return u


def test_adopted_orphan_is_deduped_in_merge(db_session, tmp_path):
    user = _super_admin(db_session)
    jobdir = tmp_path / "job"; jobdir.mkdir()
    (jobdir / "output.csv").write_text("x")
    # canonical_graph.json with one orphan auto node (no entity_id) + an edge to it
    (jobdir / "canonical_graph.json").write_text(json.dumps({
        "nodes": [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10], "class": "valve_bv"}],
        "edges": [{"id": "e1", "source": "n_1", "target": "n_1"}],
        "page_width": 100, "page_height": 100,
    }))
    job = models.Job(user_id=user.id, status="done", original_filename="p.pdf",
                     stored_filename="p.pdf", output_csv_path=str(jobdir / "output.csv"))
    db_session.add(job); db_session.commit()
    # adopted annotation overlapping the orphan
    ann = models.UserAnnotation(job_id=job.id, entity_id="e-x", user_id=user.id, source="user",
                                status="user_confirmed", entity_class="valve", sub_class="BV",
                                bbox=[1, 1, 11, 11], sheet_number=1, tag="62-BV-1")
    db_session.add(ann); db_session.commit()

    g = get_job_graph(job.id, db=db_session, current_user=user)
    ids = [n["id"] for n in g["nodes"]]
    assert "n_1" not in ids                      # orphan superseded → dropped
    assert any(n.get("entity_id") == "e-x" for n in g["nodes"])
    assert all(e.get("source") != "n_1" and e.get("target") != "n_1" for e in g["edges"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_graph_orphan_dedup_merge.py -v`
Expected: FAIL — `n_1` still present (and/or edge dangles).

- [ ] **Step 3: Implement** — in `webapp/routers/graph.py`, add the import at top with the other graph imports:

```python
from webapp.graph.orphan_dedup import superseded_auto_ids
```

Then in the merge region, immediately AFTER the `graph["nodes"] = list(...) + [a for a in annotation_nodes if ...]` line and BEFORE `rejected_node_ids = {...}`, insert:

```python
    # Drop orphan auto nodes (no entity_id) superseded by an adopted annotation
    # node at the same position, so the graph shows ONE node, not a duplicate.
    _superseded = superseded_auto_ids(
        [n for n in graph["nodes"] if n.get("source") == "auto"],
        [n for n in graph["nodes"] if n.get("source") == "user"],
    )
    if _superseded:
        graph["nodes"] = [n for n in graph["nodes"] if n.get("id") not in _superseded]
```

Then extend `reject_keys` so superseded ids drop their dangling edges — change:

```python
    reject_keys = rejected_ids | rejected_node_ids
```
to:
```python
    reject_keys = rejected_ids | rejected_node_ids | _superseded
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_graph_orphan_dedup_merge.py tests/unit/test_graph_router_and_sync.py -v`
Expected: PASS (new test + existing graph-router tests still green).

- [ ] **Step 5: Commit**

```bash
git add webapp/routers/graph.py tests/unit/test_graph_orphan_dedup_merge.py
git commit -m "feat(graph): dedup superseded orphan auto-nodes in live merge"
```

---

### Task 3: Apply orphan dedup in the freeze builder

**Files:**
- Modify: `webapp/scripts/freeze_graph_gt.py` (node loop ~59-81)
- Test: `tests/unit/test_freeze_graph_gt.py` (add a case)

**Interfaces:**
- Consumes: `superseded_auto_ids` (Task 1). Produces: frozen GT excludes superseded orphan
  nodes and their edges.

- [ ] **Step 1: Write the failing test** — add to `tests/unit/test_freeze_graph_gt.py`:

```python
def test_freeze_drops_orphan_superseded_by_adopted_node(db_session, tmp_path):
    # build_frozen_graph reads canonical_graph.json + annotations; adopted
    # annotation at same bbox as an orphan auto node → only one node frozen.
    from webapp.scripts.freeze_graph_gt import build_frozen_graph
    job = _job_with_graph(db_session, tmp_path, nodes=[
        {"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10], "class": "valve_bv"},
    ], edges=[{"id": "e1", "source": "n_1", "target": "n_1"}])
    _add_annotation(db_session, job, entity_id="e-x", bbox=[1, 1, 11, 11],
                    entity_class="valve", sub_class="BV", status="user_confirmed", tag="62-BV-1")
    g = build_frozen_graph(job.id, db_session)
    ids = [n["id"] for n in g["nodes"]]
    assert "n_1" not in ids
    assert any(n.get("entity_id") == "e-x" for n in g["nodes"])
    assert all(e.get("source") != "n_1" and e.get("target") != "n_1" for e in g["edges"])
```

(If `_job_with_graph` / `_add_annotation` helpers don't exist in the test file, add them mirroring the existing fixtures in that file — build a Job with `output_csv_path` pointing at a tmp dir containing `canonical_graph.json`, and insert a `UserAnnotation`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_freeze_graph_gt.py -k orphan -v`
Expected: FAIL — `n_1` still in frozen nodes.

- [ ] **Step 3: Implement** — in `webapp/scripts/freeze_graph_gt.py`, add import near the other imports:

```python
from webapp.graph.orphan_dedup import superseded_auto_ids
```

After `nodes = auto_nodes + user_nodes`, insert:

```python
    # Drop orphan auto nodes (no entity_id) superseded by an adopted user node.
    _superseded = superseded_auto_ids(auto_nodes, user_nodes)
    if _superseded:
        nodes = [n for n in nodes if n.get("id") not in _superseded]
        rejected_node_ids = rejected_node_ids | _superseded
```

(`rejected_node_ids` is already folded into `reject_keys` on the next line, so superseded
orphans' edges are dropped by the existing `_touches` filter.)

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_freeze_graph_gt.py -v`
Expected: PASS (new + existing 5 freeze tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/scripts/freeze_graph_gt.py tests/unit/test_freeze_graph_gt.py
git commit -m "feat(graph): dedup superseded orphans in frozen GT builder"
```

---

### Task 4: Frontend bbox→detection-index resolver

**Files:**
- Create: `webapp/frontend/src/studio/resolveDetectionIndex.ts`
- Test: `webapp/frontend/src/studio/__tests__/resolveDetectionIndex.test.ts`

**Interfaces:**
- Produces: `resolveDetectionIndex(nodeBbox: [number,number,number,number], detections: {bbox:number[]}[]): number` — returns the index of the highest-IoU detection, or `-1` if none overlaps (IoU ≤ 0).

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect } from "vitest";
import { resolveDetectionIndex } from "../resolveDetectionIndex";

describe("resolveDetectionIndex", () => {
  it("picks the highest-IoU detection", () => {
    const dets = [{ bbox: [100, 100, 110, 110] }, { bbox: [1, 1, 11, 11] }];
    expect(resolveDetectionIndex([0, 0, 10, 10], dets)).toBe(1);
  });
  it("returns -1 when nothing overlaps", () => {
    expect(resolveDetectionIndex([0, 0, 10, 10], [{ bbox: [50, 50, 60, 60] }])).toBe(-1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/studio/__tests__/resolveDetectionIndex.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```typescript
// webapp/frontend/src/studio/resolveDetectionIndex.ts
function iou(a: number[], b: number[]): number {
  const ix1 = Math.max(a[0], b[0]), iy1 = Math.max(a[1], b[1]);
  const ix2 = Math.min(a[2], b[2]), iy2 = Math.min(a[3], b[3]);
  const iw = Math.max(0, ix2 - ix1), ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  if (inter <= 0) return 0;
  const areaA = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1]);
  const areaB = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const union = areaA + areaB - inter;
  return union > 0 ? inter / union : 0;
}

export function resolveDetectionIndex(
  nodeBbox: [number, number, number, number],
  detections: { bbox: number[] }[],
): number {
  let best = -1, bestIou = 0;
  detections.forEach((d, i) => {
    if (!d.bbox || d.bbox.length !== 4) return;
    const v = iou(nodeBbox, d.bbox);
    if (v > bestIou) { bestIou = v; best = i; }
  });
  return best;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/studio/__tests__/resolveDetectionIndex.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/resolveDetectionIndex.ts webapp/frontend/src/studio/__tests__/resolveDetectionIndex.test.ts
git commit -m "feat(studio): bbox->detection-index resolver for node adoption"
```

---

### Task 5: Adopt affordance — type-B node click → "Confirm as <class>" → claiming annotation

**Files:**
- Modify: `webapp/frontend/src/studio/GraphLayer.tsx` (node `onClick` ~342-347 — route type-B clicks to an `onAdoptNode` callback)
- Modify: `webapp/frontend/src/studio/Studio.tsx` (add `adoptNode` handler; pass through)
- Modify: `webapp/frontend/src/studio/PropertiesPanel.tsx` (render "Confirm as &lt;class&gt;" when a type-B node is the active adopt target)
- Test: `webapp/frontend/src/studio/PropertiesPanel.test.tsx`

**Interfaces:**
- Consumes: `resolveDetectionIndex` (Task 4); existing `createAnnotation` + `patchAnnotation` + `ocrBbox`.
- Produces: `adoptNode(node)` → `createAnnotation({entity_class, sub_class, bbox: node.bbox, sheet_number, linked_detection_index: resolveDetectionIndex(node.bbox, detections)})` then best-effort `ocrBbox`→`patchAnnotation(tag)`. `node.class` (e.g. `"valve_bv"`) maps to `entity_class`/`sub_class` by splitting on `_` (mirror of backend `_detection_label_to_class`).

- [ ] **Step 1: Write the failing test** — `PropertiesPanel` shows a "Confirm as BV" button for a type-B node (no entity_id, class `valve_bv`) and clicking it calls `onAdopt` with the node.

```tsx
// add to PropertiesPanel.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { PropertiesPanel } from "./PropertiesPanel";

it("offers Confirm-as for a type-B (no entity_id) node", () => {
  const onAdopt = vi.fn();
  render(<PropertiesPanel adoptTarget={{ id: "n_1", entity_id: null, class: "valve_bv", bbox: [0,0,10,10] }} onAdopt={onAdopt} /* …other required props with minimal stubs… */ />);
  const btn = screen.getByRole("button", { name: /confirm as bv/i });
  fireEvent.click(btn);
  expect(onAdopt).toHaveBeenCalledWith(expect.objectContaining({ id: "n_1" }));
});
```

(Fill the other required `PropertiesPanel` props with minimal stubs already used by the existing tests in this file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/studio/PropertiesPanel.test.tsx`
Expected: FAIL — no "Confirm as" button / prop not supported.

- [ ] **Step 3: Implement**

In `GraphLayer.tsx`, change the node `onClick` so a type-B node routes to adoption:

```tsx
onClick={(ev) => {
  ev.stopPropagation();
  if (onNodeClick) onNodeClick(n.id);
  if (n.entity_id) onSelect(n.entity_id as string, n.class ?? undefined);
  else if (onAdoptTarget) onAdoptTarget(n);   // type-B → adopt flow
}}
```

Add `onAdoptTarget?: (n: GraphNode) => void;` to GraphLayer props and thread it from `PidCanvas`/`Studio`.

In `PropertiesPanel.tsx`, when `adoptTarget` is set, render a panel section:

```tsx
{adoptTarget && (
  <div className="adopt-panel">
    <p>Unmatched detection — adopt it as a first-class entity?</p>
    <button onClick={() => onAdopt(adoptTarget)}>
      Confirm as {subClassFromLabel(adoptTarget.class)}
    </button>
  </div>
)}
```

with a local helper `subClassFromLabel(label?: string)` returning the upper-cased suffix after `_` (e.g. `"valve_bv" → "BV"`).

In `Studio.tsx`, add the handler:

```tsx
async function adoptNode(node: { class?: string; bbox: [number,number,number,number] }) {
  const [entity_class, sub_raw] = (node.class ?? "").split("_");
  if (entity_class !== "valve" && entity_class !== "instrument" && entity_class !== "equipment") return;
  const sub_class = (sub_raw ?? "").toUpperCase();
  const idx = resolveDetectionIndex(node.bbox, detections);   // detections already in Studio scope
  const row = await createAnnotation({
    entity_class, sub_class, bbox: node.bbox,
    sheet_number: activeSheetNumber,
    linked_detection_index: idx >= 0 ? idx : null,
  });
  if (row) {
    try {
      const norm = toNormalizedBbox(node.bbox);                // existing helper used by onDropMark
      const r = await ocrBbox(project.id, norm);
      if (r.found && r.text) await patchAnnotation(row.entity_id, { tag: r.text });
    } catch { /* OCR is a bonus */ }
    await refreshGraphAndCounts();
  }
}
```

- [ ] **Step 4: Run test + typecheck**

Run: `cd webapp/frontend && npx vitest run src/studio/PropertiesPanel.test.tsx && npx tsc --noEmit`
Expected: PASS + clean typecheck.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/GraphLayer.tsx webapp/frontend/src/studio/PropertiesPanel.tsx webapp/frontend/src/studio/Studio.tsx webapp/frontend/src/studio/PropertiesPanel.test.tsx
git commit -m "feat(studio): adopt type-B node via Confirm-as; claims detection, no duplicate"
```

---

### Task 6: Claim-on-mark fix (Mark-Symbol onto an existing detection)

**Files:**
- Modify: `webapp/frontend/src/studio/Studio.tsx` (`onDropMark`, ~457-472)
- Test: covered by an `onDropMark` unit test if present; otherwise assert via the resolver.

**Interfaces:**
- Consumes: `resolveDetectionIndex`. Produces: `onDropMark` passes the resolved index instead of hardcoded `null` so a mark dropped on a detection claims it.

- [ ] **Step 1: Write the failing test** (if `Studio` has no unit harness, add a focused test of the index decision by extracting a tiny pure helper `markLinkIndex(bbox, detections) = resolveDetectionIndex(bbox, detections)` and asserting it returns the overlapping detection's index). Place in `src/studio/__tests__/resolveDetectionIndex.test.ts`:

```typescript
it("mark dropped on a detection resolves to its index (claim, not fresh)", () => {
  const dets = [{ bbox: [0, 0, 10, 10] }];
  expect(resolveDetectionIndex([0, 0, 10, 10], dets)).toBe(0);
});
```

- [ ] **Step 2: Run test to verify it fails / passes** — this asserts the resolver; it passes once Task 4 lands. The behavioral change is in Step 3.

- [ ] **Step 3: Implement** — in `onDropMark`, replace the hardcoded `linked_detection_index: null` with:

```tsx
    const linkIdx = resolveDetectionIndex(bbox, detections);
    const row = await createAnnotation({
      entity_class,
      sub_class,
      bbox,
      sheet_number: activeSheetNumber,
      linked_detection_index: linkIdx >= 0 ? linkIdx : null,
    });
```

- [ ] **Step 4: Run test + typecheck**

Run: `cd webapp/frontend && npx vitest run src/studio && npx tsc --noEmit`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/studio/Studio.tsx webapp/frontend/src/studio/__tests__/resolveDetectionIndex.test.ts
git commit -m "fix(studio): Mark-Symbol claims overlapping detection instead of duplicating"
```

---

### Task 7: API integration test — adopt → deliverable + single graph node

**Files:**
- Test: `tests/unit/test_adopt_node_e2e.py`

**Interfaces:**
- Consumes: POST `/api/v1/jobs/{id}/annotations`, PATCH tag, `load_canonical_with_overrides`, `get_job_graph`.

- [ ] **Step 1: Write the test** — seed a job with `canonical.json` (no orphan entity) + `canonical_graph.json` (one orphan auto node) + `Job.gpu_detections` (one detection at that bbox); POST an adopt annotation with `linked_detection_index=0`; PATCH a tag; assert (a) the entity appears in `load_canonical_with_overrides(...).entities`, and (b) `get_job_graph` shows exactly one node at that bbox (orphan deduped).

```python
# tests/unit/test_adopt_node_e2e.py — fixtures mirror test_annotation_canonical_sync.py
def test_adopt_node_flows_to_canonical_and_dedups_graph(client, job_with_canonical_and_graph):
    job, eid_before = job_with_canonical_and_graph
    r = client.post(f"/api/v1/jobs/{job.id}/annotations", json={
        "entity_class": "valve", "sub_class": "BV",
        "bbox": [1, 1, 11, 11], "sheet_number": 1, "linked_detection_index": 0})
    assert r.status_code == 201, r.text
    eid = r.json()["entity_id"]
    assert client.patch(f"/api/v1/jobs/{job.id}/annotations/{eid}",
                        json={"tag": "62-BV-9"}).status_code == 200
    # deliverable inclusion
    from webapp.deliverables.overrides import load_canonical_with_overrides
    canon = load_canonical_with_overrides(job.output_csv_path, job.id, db_for(client))
    assert any(str(e.entity_id) == eid for e in canon.entities)
    # graph dedup
    g = client.get(f"/api/v1/jobs/{job.id}/graph").json()
    boxes = [n for n in g["nodes"] if n.get("bbox")]
    assert len([n for n in boxes if n["bbox"][0] in (0, 1)]) == 1
```

(Build `job_with_canonical_and_graph` mirroring the existing `job_with_canonical` fixture in `test_annotation_canonical_sync.py`, adding `canonical_graph.json` and `Job.gpu_detections`.)

- [ ] **Step 2: Run** — `SECRET_KEY=… python3 -m pytest tests/unit/test_adopt_node_e2e.py -v`. Expected: PASS (relies on Tasks 2 + the existing sync).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_adopt_node_e2e.py
git commit -m "test: adopt node flows to canonical + dedups graph (e2e)"
```

---

### Task 8: Full suite, FEATURES entry, manual-verify notes

**Files:**
- Modify: `FEATURES.md` (new entry, newest first)

- [ ] **Step 1: Run the full unit suite**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit -q` and `cd webapp/frontend && npx vitest run && npx tsc --noEmit`
Expected: all green.

- [ ] **Step 2: Add FEATURES entry** (`#135` or next free number) describing: type-B nodes adoptable as first-class entities; reuses `_sync_annotation_to_canonical`; new bbox-IoU orphan-dedup helper shared by live merge + freeze; claim-on-mark fix; `feature/orphan-promotion` rejected as the competing auto path.

- [ ] **Step 3: Manual verification on a real job (record results in the FEATURES entry):**
  1. Open job 38 in Studio (`/jobs/38/review`), graph mode.
  2. Click a type-B (amber/unmatched) valve node → "Confirm as BV" → confirm.
  3. Verify: node turns solid (adopted), appears in the element list, a pipe can be drawn to it, and it can be removed.
  4. Verify it appears in the valve-list export.
  5. `python -m webapp.scripts.freeze_graph_gt --job-id 38 --status verified` (after full correction) → confirm node count has no orphan duplicate.

- [ ] **Step 4: Commit**

```bash
git add FEATURES.md
git commit -m "docs: FEATURES #135 — type-B node adoption + graph orphan dedup"
```

---

## Self-Review

- **Spec coverage:** Adopt affordance → Task 5. Claim linkage → Tasks 4+6. Graph orphan dedup (live + freeze) → Tasks 2+3 (helper Task 1). Deliverable inclusion → reuses existing sync, asserted in Task 7. Non-goals (no canonical injection, no auto/bulk adopt) respected.
- **Placeholder scan:** test fixtures referencing existing helpers say "mirror the existing fixture" with the concrete file to copy from — acceptable since the code to copy exists; all production code steps show full code.
- **Type consistency:** `superseded_auto_ids`/`bbox_iou` names consistent across Tasks 1-3; `resolveDetectionIndex` consistent across Tasks 4-6; `linked_detection_index` matches `AnnotationCreate`.
