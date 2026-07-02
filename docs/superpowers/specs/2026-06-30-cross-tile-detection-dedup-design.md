# Design: Cross-tile detection de-duplication + 1:1 entity matching

**Date:** 2026-06-30
**Status:** pending spec review
**Branch:** `feat/detection-dedup` (off `dev`, which includes #135)
**Related:** #66 (graph pipeline / `dedupe_nodes_by_entity`), #135 (type-B node adoption), the cross-tile-dup investigation (memory `project_cross_tile_detection_dup`)

## Problem

Clicking one element in Studio highlights several detections on the P&ID. Root cause (measured): pages are tiled **3×3 with 20% overlap**, and `Job.gpu_detections` is **never de-duplicated across overlapping tiles** — so a glyph on a tile seam is detected once per overlapping tile (up to **4×** at a 4-tile corner). Across 7 OCR-cached jobs, **972/2490 detections (39%) are cross-tile duplicates** (consistently 38–48% per job).

The OCR/entity matcher then binds every duplicate to one canonical entity, because `bbox_ocr.py` resolves `ent = tag_to_entity.get(tag)` with **no 1:1 consumption** (instrument path ~199-206, valve path ~349). So `61-HS-00471` ends up bound to 9 detections.

Two distinct things are conflated in that "9":
- **Phantom tile-duplicates** — the same glyph detected 4× (the bulk; ~39% problem).
- **Genuinely-distinct glyphs that share a tag** — a BPCS circle + SIS diamond for one loop tag. **Domain rule: BPCS and SIS are TWO separate entities**, so each should resolve to its own entity, not both to one.

## Goals

1. Remove phantom cross-tile duplicate detections (page-space NMS) so the canvas, graph, entity-matching, and the #135 type-B set all operate on one detection per physical glyph.
2. Make tag→entity matching **1:1** so each canonical entity binds to exactly one detection. Post-dedup this is correct (no same-class duplicates left to wrongly split). Consequence: when a tag labels two distinct glyphs (BPCS circle + SIS diamond) but canonical has one entity, the circle claims it and the **diamond surfaces as a type-B node** the user adopts as its own entity via #135 — yielding the two separate entities the domain requires.

Out of scope (tracked separately): the valve-proximity bleed (600px window; only 2 cases across all jobs); auto-creating the second (SIS) entity without a user adopt (the #135 adopt path covers it).

## Non-destructive, read-time (no re-inference)

`gpu_detections` on disk is left as-is. De-dup is applied at the read-time points that consume it, so all 56 existing jobs are fixed immediately with no GPU re-run.

## Component 1 — shared NMS helper (pure)

New `webapp/graph/detection_dedup.py`:

```
dedupe_detections_page_space(
    detections: List[Dict], tile_offsets: Dict[str, TileBox], iou_threshold: float = 0.5
) -> List[Dict]
```

- For each detection compute its **page-space** bbox using `tile_offsets` (mirror `loader.to_page_pixel_detections`: `page_bbox = tile_local_bbox + tile.x0/y0`; detections whose `tile` is unknown or bbox isn't length-4 are treated as already-page-space / pass through).
- Group by class (`label`). Within a class run **greedy NMS**: sort by `confidence` desc (missing confidence → treat as 0, tie-break larger area), keep a detection, suppress any later same-class detection whose page-space IoU ≥ `iou_threshold`.
- Return the **surviving subset of the original detection dicts** (unchanged objects — drop suppressed, never mutate a bbox or tile). Different classes never suppress each other (so the BPCS circle and SIS diamond both survive).
- Reuse `bbox_iou` from `webapp/graph/orphan_dedup.py` (no duplicated IoU math).

## Component 2 — apply the helper at the 3 read-time call sites

Page dims come from `canonical_graph.json` `page_width/height` (fallback: full-page image; else skip de-dup safely) via a small shared `_page_dims(job)` helper — same sourcing #135's claim resolver uses (`annotations.py:_page_dims_from_canonical_graph`); factor it so both reuse one implementation.

1. **`bbox_ocr.compute_tagged_detections`** — de-dup `raw_dets` **before** `_attach_entity_ids` + `_run_valve_ocr`. Cleans the rendered OCR cache, makes matching operate on unique glyphs, and **cuts ~39% of per-detection OCR API calls**.
2. **`api_v1.api_job_detections`** — de-dup so the pre-OCR first paint (before the tagged cache lands) is also clean.
3. **graph loader `build_job_input`** — de-dup right after `to_page_pixel_detections`, so graph nodes build from unique detections (complements the post-match `dedupe_nodes_by_entity` from #66).

## Component 3 — 1:1 consume in tag→entity matching (`bbox_ocr.py`)

In both the instrument-OCR path and `_run_valve_ocr`, track a `consumed: Set[str]` of entity_ids already assigned. When `ent = tag_to_entity.get(tag)` resolves, assign it only if `str(ent.entity_id) not in consumed`; then add it. If already consumed, leave the detection **unmatched** (`entity_id=None`, keep `entity_tag` so the label still shows) → it renders as a type-B node, adoptable via #135. Mirrors the `consumed` discipline already in `api_v1._attach_entity_ids`.

This is safe **only because de-dup runs first** — without it, 1:1 consume would wrongly split the phantom same-class duplicates. Order is enforced by call-site sequencing (de-dup precedes matching in `compute_tagged_detections`).

## Testing

- **Unit (helper):** two overlapping same-class boxes → highest-confidence survivor only; distinct adjacent same-class low-IoU → both kept; **different-class same location (circle+diamond) → both kept**; missing bbox/tile → passthrough; missing page dims → returns input unchanged.
- **Unit (matching consume):** two same-tag detections + one canonical entity → first claims it (`user`/matched), second is unmatched (`entity_id=None`, `entity_tag` retained).
- **Integration:** `/detections` and `/detections-tagged` return de-duplicated lists; a job-38-shaped fixture (a glyph duplicated across 4 tiles) collapses to one detection.
- **Regression:** existing `bbox_ocr` / `api_v1` detection tests still pass; graph tests still pass.

## Acceptance (measured post-deploy)

- Re-run the blast-radius script: cross-tile duplicate rate drops from ~39% toward ~0; no genuine distinct symbol lost (counts don't *under*-shoot on a known-good job).
- Job 38: the circle (BPCS) claims `61-HS-00471`; the diamond (SIS) becomes a type-B node; clicking `61-HS-00471` highlights **one** detection (the circle). The diamond is then adoptable as the separate SIS entity (#135).

## Rollout

- Per-job, read-time, additive. No migration, no re-inference, no `gpu_detections` rewrite.
- Ship to `dev` via the same reviewed multi-agent flow as #135. FEATURES entry on completion.
