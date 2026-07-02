# Design: Type-B graph nodes → full first-class entities

**Date:** 2026-06-30
**Status:** revised (annotation→canonical sync already exists; core work is graph-side), pending spec review
**Branch:** `feat/graph-typeb-first-class` (off `dev`)
**Related:** FEATURES #129 (node corrections), #128 (graph GT loop — the motivating use), #66 (graph pipeline), annotation→canonical sync (2026-06-17 product rule)

## Problem

In the Studio review canvas, a job's graph contains two kinds of nodes:

- **Type-A** — nodes with an `entity_id`. Clickable, listed in the right-hand element
  panel, editable, connectable, rejectable.
- **Type-B** — nodes with **no `entity_id`**. They render in the graph overlay but:
  - aren't in the right-hand element list (`buildElements.ts:115` skips detections
    without `entity_id`),
  - can't be selected (a click resolves to `onSelect(null)`, `GraphLayer.tsx:346`),
  - can't have pipes drawn to them (edge-snap skips `!entity_id`, `PidCanvas.tsx:802`),
  - can't be rejected (rejection keys on `entity_id`),
  - yet **do** land in the frozen ground-truth graph as `auto` nodes
    (`freeze_graph_gt.py` keeps every non-rejected auto node).

On **job 38**, 33 of 91 nodes (36%) are type-B — mostly valves the canonical matcher
(D1.5) never bound to an entity (BV×17, BF×7, DB×5, CK×1, 2 motors, 1 BPCS instrument).

This blocks the graph ground-truth workflow (#128): you can't connect the true pipes to
36% of the nodes, can't remove the wrong ones, and re-marking with the current
Mark-Symbol tool **duplicates** them — `onDropMark` hardcodes `linked_detection_index: null`
(`Studio.tsx:472`), so a mark never claims the existing detection. That duplication is what
produced last session's "USER-TT junk nodes" on job 38.

## Goal

Let a user "adopt" a type-B node so it becomes a **full first-class entity**: selectable
+ connectable + rejectable in the graph **and** present in the right-hand element list and
in every deliverable (valve list, instrument index, datasheets) — with **no duplicate** node
left behind in the graph or the frozen GT.

## What already exists (do NOT rebuild)

The deliverable side of "first-class" is **already implemented** via the annotation→canonical
sync (2026-06-17 product rule), in `webapp/routers/annotations.py`:

- `_sync_annotation_to_canonical` (line 276) — upserts a **tagged** annotation
  (`status in _EXPORTABLE_STATUSES` and non-empty `tag`) into `canonical.json`, and removes
  it when untagged / rejected / deleted. `canonical.json` is what the deliverable path reads
  (`load_canonical_with_overrides`), so a tagged annotation already appears in valve list /
  instrument index / datasheets / DatasheetDrawer / Bulk Review.
- `_entity_dict_from_annotation` (line 245) — the annotation→canonical-entity field mapping.
- `_refresh_canonical_db_index` (line 262) — keeps the admin `canonical_entities` DB index
  in sync too.
- `_detection_label_to_class` (line 307) — maps a YOLO label → `(entity_class, sub_class)`,
  e.g. `valve_bv → ("valve","BV")`; returns `(None, None)` for non-editable labels
  (arrows/connectors).

Implication: once a type-B node becomes a **tagged** `UserAnnotation` that **claims** its
detection (so it isn't duplicated), it is already a full first-class deliverable entity. The
earlier draft's read-time "canonical injection" is therefore **dropped** — it would duplicate
this existing write-time sync.

## The genuinely missing work

### Component 1 — Adopt affordance (UI)

Type-B nodes carry their YOLO `class`/`sub_class`. Make a type-B node click open a one-click
**"Confirm as &lt;class&gt;"** action in `PropertiesPanel` (class pre-filled from the detection
via the label→class mapping; editable) instead of the current `onSelect(null)` no-op.

On confirm:
1. Resolve `linked_detection_index` from the node (Component 3).
2. `POST /api/v1/jobs/{id}/annotations` with `entity_class`/`sub_class` from the node and
   the resolved `linked_detection_index` (≥ 0 → claims the detection, no canonical duplicate).
3. OCR the node bbox to pre-fill a tag (mirrors `onDropMark`'s best-effort OCR →
   `patchAnnotation(tag)`), since a non-empty tag is what makes `_sync_annotation_to_canonical`
   export it. Tag is editable; if OCR misses, the user types it in the drawer.

Secondary: fix `onDropMark` (`Studio.tsx:472`) so a Mark-Symbol dropped *onto* an existing
detection passes that detection's index instead of the hardcoded `null` — same claim path,
reached via the palette tool rather than node-click.

### Component 2 — Graph orphan dedup (the core new logic)

Today, adopting a type-B node leaves the original entity-id-less **auto** node in the graph
*next to* the new `source:"user"` node — the merge dedups annotation nodes against canonical
nodes **by `entity_id`** (`graph.py:869`), but an orphan auto node has no `entity_id` to match,
so both survive. That is the duplicate.

Fix: dedup the orphan **by spatial overlap**. When merging annotation nodes (live `GET /graph`)
and when building the frozen GT, drop any **auto node with no `entity_id`** whose bbox overlaps
an adopted annotation's bbox above an IoU threshold.

- New pure helper `supersedes(auto_node, annotation_nodes, iou_threshold=0.5) -> bool` (or a
  set-builder `superseded_auto_ids(auto_nodes, annotation_nodes) -> set[str]`) in a shared
  module so the live merge and the freeze use identical logic (same pattern already used for
  edge omission, which the freeze mirrors from the merge).
- Apply in `webapp/routers/graph.py` (the `_annotation_nodes` merge step) and in
  `webapp/scripts/freeze_graph_gt.py` (the auto-node loop).
- IoU threshold default `0.5`; bbox is page-pixel in both the auto node and the annotation
  (`UserAnnotation.bbox`), so they're directly comparable.
- Edges that referenced the dropped orphan auto node (by `node_id`) must be re-pointed or
  dropped consistently — reuse the existing rejected-node edge-omission path
  (`reject_keys` includes node ids), treating a superseded orphan like a rejected node id.

### Component 3 — Claim linkage (resolve `linked_detection_index`)

`linked_detection_index` is the index into `Job.gpu_detections`. The canvas already holds the
detections array (index-aligned with `Job.gpu_detections`). Resolve the index by matching the
clicked node's `bbox` (page-pixel) to the detection bbox (same space, highest IoU). Pass it on
the adopt POST. The backend's existing `linked_detection_index >= 0` path then claims the
detection. (TDD will confirm the canvas detections array is index-aligned with
`Job.gpu_detections`; if not, resolve server-side from the node bbox.)

## Scope boundaries / non-goals (v1)

- **No read-time canonical injection** — dropped; the write-time `_sync_annotation_to_canonical`
  already covers deliverables and the admin index.
- **OCR tag re-resolution** beyond the single at-adopt OCR read is out of scope.
- **Auto-adopt / bulk-adopt** all type-B nodes at once is out of scope (v1 is per-node, deliberate,
  so the user vets each — these are unmatched detections that may include false positives).

## Unknowns to resolve in TDD (failing test first, not hand-waved)

1. **Detection-index alignment.** Confirm the canvas detections array is index-aligned with
   `Job.gpu_detections` so the bbox→index resolver yields the right `linked_detection_index`;
   otherwise resolve server-side. Test the resolver against a fixture.
2. **Edge re-pointing on dedup.** When an orphan auto node is superseded by an adopted node,
   verify edges that touched the orphan are dropped (not dangling) in both the live graph and
   the freeze. Failing test asserts no edge references a superseded orphan id.

## Testing strategy

- **Unit (backend):** `superseded_auto_ids` / `supersedes` — orphan with no `entity_id` and
  high-IoU overlap is superseded; an auto node *with* an `entity_id` is never superseded; low
  overlap is not superseded.
- **Unit (backend):** `GET /graph` merge drops the superseded orphan and its dangling edges;
  a non-adopted job's graph is unchanged.
- **Unit (backend):** `freeze_graph_gt` output for an adopted job contains the user node and
  not the orphan (node count unchanged vs. pre-adopt, not +1).
- **API:** adopt a node (POST /annotations claim + PATCH tag) → assert it appears in valve-list
  export output AND that `GET /graph` shows exactly one node at that position.
- **Frontend:** `PropertiesPanel` shows "Confirm as &lt;class&gt;" for a type-B node; confirm fires
  the adopt POST with a resolved `linked_detection_index`; the bbox→index resolver picks the
  highest-IoU detection.
- **Regression:** existing `test_annotation_canonical_sync.py` and `overrides.py` tests still
  pass; freeze output unchanged for jobs with no adopted nodes.

## Coordination — overlap with `feature/orphan-promotion` (swaraj, unmerged)

An unmerged teammate branch `feature/orphan-promotion` (commit `e56ec21`, 2026-06-29) adds
`_promote_orphan_detections` in `webapp/routers/bbox_ocr.py`: it **automatically** promotes
every OCR-tagged orphan detection into `canonical.json` during the OCR background job.

Relationship to this design (we proceed with our per-node approach; flag the overlap):
- **Overlaps** the deliverable-inclusion half — but via *automatic* promotion (no per-node
  human gate → higher false-positive risk), which we deliberately did not choose.
- It is **backend-only** and does **not** address the graph orphan-dedup, connect/reject, or
  adopt UI — i.e. it does not solve the core of this design.
- It **zeroes bbox** (`(0.0, 0.0, 0.0, 0.0)`) on promoted entities, so promoted entities
  cannot position in the graph — a bug for graph use that our bbox-preserving path avoids.
- It writes `canonical.json` from a **second** code path alongside the already-merged
  `_sync_annotation_to_canonical`. If both land, two mechanisms mutate canonical.json.

**Decision (2026-06-30):** `feature/orphan-promotion` will be **rejected / not merged** (per
product owner) so there is no competing auto-promotion path. This design is the single
mechanism for making orphan/type-B nodes first-class, reusing the already-merged
`_sync_annotation_to_canonical` (no third canonical-mutation path is introduced).

## Rollout

- Per-job, additive. No migration. `canonical.json` is still written only by the existing
  annotation sync. No impact on other customers' deliverables.
- Ship to `dev` via PR off `feat/graph-typeb-first-class`; FEATURES entry on merge.
