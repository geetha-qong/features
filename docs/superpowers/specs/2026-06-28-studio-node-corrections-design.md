# Studio node corrections — real, unified add/remove

**Date:** 2026-06-28
**Status:** design approved (brainstorming) → ready for implementation plan
**Scope:** end-user node editing in Studio. **Out of scope:** GT-freeze + scorer-reads-merged-graph (separate follow-up), training-signal-on-reject (best-effort only).

## Problem

A user can correct **edges** in Studio (draw/flip/delete/reject — verified working), but **not nodes**:
- "Mark Symbol" creates a `UserAnnotation` (and a deliverable entity if tagged) but the symbol **never becomes a graph node** — it can't be connected with edges.
- There is **no way to remove a false-positive YOLO node** from the graph, and deleting only works on user-added annotations.

Because graph correctness (and the headline isomorphism metric) depends on both the right **node set** and the right **edges**, users cannot produce a correct graph. This blocks ground-truth creation and undermines the digital-twin value. (Verified empirically 2026-06-28 on local job 2: adding via `POST /annotations` returned 201 but the node did **not** appear in `GET /graph`; graph stayed at 31 nodes.)

## Goal

Make node corrections **real and unified**: a single add/remove in Studio updates **both** the process graph **and** the deliverables (valve list, instrument index, datasheets) in sync. Clean, low-risk, reusing existing stores and the existing read-time merge pattern.

## Key principle: `entity_id` is the spine

Graph nodes, canonical entities, deliverable rows, and edge endpoints all already key on `entity_id`. All corrections key on `entity_id`. (Graph `node_id` like `n_007` encodes a *post-dedup* detection index and is NOT a reliable cross-store key — do not use it for corrections.)

## Architecture (Approach A — read-time merge, reuse stores)

No new tables. Reuse the proven pattern already used for user **edges** (merged into `GET /graph` at read time).

### Data model — reuse

- **Add a node** → existing `UserAnnotation` (`webapp/models.py`): `entity_id` (uuid4.hex, stable), `bbox`, `entity_class`, `sub_class`, `tag`/`placeholder_tag`, `status`, `source`. No schema change. Created by the existing `POST /jobs/{id}/annotations` (Mark Symbol).
- **Remove a node** → existing `EntityOverride` with a reserved field `field_name = "__rejected__"`, `new_value = true`, keyed by `entity_id`. Reversible (delete the row). No schema change. `EntityOverride` is already the canonical edit store and is already loaded by the deliverable merge.

### Read-merge — `webapp/routers/graph.py` `GET /jobs/{job_id}/graph`

Today this loads `canonical_graph.json` and merges user **edges** from `graph_corrections` (incl. `auto_rejection` sentinels). Extend the **node** list the same way:

```
nodes_out =
    [ n for n in canonical_graph.json.nodes if n.entity_id not in rejected_ids ]
  + [ node_from_annotation(a) for a in UserAnnotation(job)
        if a.status in {user_added, user_confirmed}
        and a.entity_id not in rejected_ids ]
```

where `rejected_ids = { ov.entity_id for ov in EntityOverride(job) if ov.field_name == "__rejected__" and truthy(ov.new_value) }`.

`node_from_annotation` maps a `UserAnnotation` to the node dict shape the canvas already consumes: `{ id: entity_id, entity_id, tag, class: sub_class-or-entity_class, bbox, tile, confidence: 1.0, source: "user" }`. Annotation nodes are valid edge endpoints because `graph_corrections` edges key on `entity_id`.

Edge merge is unchanged, except: drop any edge whose `source`/`target` `entity_id` is now rejected (so removing a node also drops its dangling edges from the response).

### Deliverable unification — `webapp/deliverables/overrides.py` `load_canonical_with_overrides`

The single function both the deliverable generators and the entities API call. Add one filter: **drop entities whose `entity_id` has a truthy `__rejected__` override.** This makes a removed node vanish from valve list / instrument index / datasheets / bulk review with one change. Added (tagged) annotations already sync into canonical via `_sync_annotation_to_canonical`, so they already flow into deliverables — no change needed there.

`__rejected__` must be excluded from the normal field-override application loop (it is a control flag, not an entity field).

## API

| Action | Endpoint | Persistence |
|---|---|---|
| Add node | `POST /jobs/{id}/annotations` (existing) | `UserAnnotation` (+ canonical sync if tagged) |
| Remove (detected) | `POST /jobs/{id}/nodes/{entity_id}/reject` (new) | `EntityOverride __rejected__=true`; best-effort `ModelCorrection(action=delete)` only if a detection index is recoverable by bbox match |
| Undo remove | `DELETE /jobs/{id}/nodes/{entity_id}/reject` (new) | deletes the `__rejected__` override |
| Remove (user-added) | `DELETE /jobs/{id}/annotations/{entity_id}` (existing) | hard-delete the annotation |
| OCR tag suggest | `POST /jobs/{id}/ocr-bbox` (existing) | none (returns suggestion) |

Reject endpoints are idempotent (re-reject = no-op; undo of a non-reject = 404/no-op). New endpoints require the same auth as the existing graph/annotation routes and validate `entity_id` belongs to the job.

## Canvas UX (`webapp/frontend/src/studio/`)

Reuse existing affordances; no new layout paradigm.

- **Add:** existing "Mark Symbol" mode → drop box → on drop, auto-run `ocr-bbox` to prefill the tag (user edits/confirms in the existing tag field). The node renders immediately (it comes back in `GET /graph`); once a tag is confirmed it appears in the deliverable. Untagged → graph-only until tagged.
- **Remove:** select **any** node (detected or user-added) → **Remove** button in `PropertiesPanel` (today's Delete button; widen the gate beyond `source === 'user'`). Detected → calls the reject endpoint (soft); user-added → existing hard delete. Show a **toast with Undo** after reject. Rejected detected-nodes render **ghosted** (dimmed) until undo or refresh, so the action is visible and reversible.
- **Connect with direction:** already works (Draw Edge + line types + flip). No change.
- After add/remove, refresh the graph + the affected deliverable counts (the SPA already refetches `GET /graph` and entities).

## Error handling

- Reject of an unknown `entity_id` → 404. Reject when already rejected → 200 no-op. Undo when not rejected → 404 (frontend treats as already-undone).
- Canonical/graph file missing (legacy job) → reject still records the override; graph merge tolerates a missing file (returns annotation-only nodes).
- OCR failure on add → tag stays blank, user types manually (existing behavior).
- All writes are non-fatal to read paths: a failed deliverable re-gen does not roll back the override.

## Testing

**Backend unit (pytest, `tests/unit/`):**
- `overrides.py`: entity with `__rejected__=true` is dropped; `__rejected__` not applied as a field; non-rejected entities + normal overrides unchanged.
- `graph.py` read-merge: annotation nodes included; rejected `entity_id` excluded from nodes AND from its edges; missing graph file → annotation-only nodes.
- reject/undo endpoints: create/delete override, idempotency, 404s, job-scoping.

**Frontend (vitest):** PropertiesPanel gate shows Remove for detected + user nodes; reject calls the right endpoint by source; Undo path.

**E2E (Playwright, local):** on a real job — add a symbol (with OCR prefill) → assert it's a node in `GET /graph`; draw a directed edge to it → assert edge present; remove a detected node → assert it's gone from `GET /graph` AND from the valve_list/instrument_index entities; Undo → assert it returns. (Mirrors the verification run on 2026-06-28.)

## Files to change (for the plan)

| Layer | File | Change |
|---|---|---|
| Graph read-merge | `webapp/routers/graph.py` | include annotation nodes; exclude rejected entity_ids (nodes + their edges) |
| Reject endpoints | `webapp/routers/graph.py` (or `annotations.py`) | `POST`/`DELETE /jobs/{id}/nodes/{entity_id}/reject` |
| Deliverable filter | `webapp/deliverables/overrides.py` | drop `__rejected__` entities; exclude flag from field-apply loop |
| Canvas | `webapp/frontend/src/studio/PidCanvas.tsx` | render annotation nodes + ghost rejected; ensure add/connect/select work for them |
| Properties panel | `webapp/frontend/src/studio/PropertiesPanel.tsx` | widen Remove gate; route reject vs delete; Undo toast |
| Studio glue | `webapp/frontend/src/studio/Studio.tsx` + `api.ts` | reject/undo API calls; refresh graph + deliverable counts; auto-OCR on mark |

## Non-goals (explicit)

- GT-freeze (snapshot merged graph → `tests/graph_ground_truth/job_N.json`) and pointing the scorer at the merged graph — **separate follow-up spec**.
- Reliable reject→YOLO training signal — best-effort only here.
- No graph-node-rebuild / pipeline re-run on edit.
- No change to how the pipeline first builds nodes from detections.
