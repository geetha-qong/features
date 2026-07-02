# Orientation-Aware Line-Number Detection (Pass 4.5)

**Date:** 2026-06-26
**Status:** Approved (design) — implementation behind `LINE_ORIENT_OCR=1`
**Owner:** line-list / extraction

## Goal

Increase engineering **Line Number** completeness — detect vertical, rotated
(90/180/270°), and pipeline-attached annotations, and eliminate truncated /
duplicate line numbers — **without changing the production extraction
architecture**. Gemini Vision (via `extractor.get_client()`) remains the single
OCR engine. The OpenCV tracer and candidate-region logic only choose *better
crops and orientations*; they never recognise text.

This is an **additive** coverage pass that runs after Pass 4 and only touches
pipelines Pass 4 left **unresolved**, so it cannot regress current output.

## Non-negotiable constraints (from approval)

1. **Single OCR engine** — Gemini Vision only. No EasyOCR / PaddleOCR / Tesseract
   / RapidOCR in this path.
2. **Tracer is for coverage, not OCR** — detect pipes, find pipes without line
   numbers, generate ROIs, estimate orientation, hand better crops to Vision.
3. **Do not depend only on the tracer** — also search pipeline annotations,
   continuation tables, off-page connector tables, and engineering text regions
   (disconnected/hidden/overlapping pipes mean the tracer alone misses some).
4. **Full-page ROIs** — crop from the original full-resolution page image
   (`tmp/page_0_full.png`), never re-tile. Tile generation is unchanged. This
   removes split line numbers / tile-boundary truncation / duplicate OCR.
5. **Orientation order** — original → estimated pipe orientation → 90° → 270° →
   180°. Keep the candidate yielding the **most complete** engineering line
   number.
6. **Engineering-aware validation** — require a complete identifier (numeric
   size prefix, ≥3 dash segments, well-formed segments). Reject truncated forms
   like `4"-X`, `20"-W`, `BGA`, `XXXX-AS1LC`. Accept full forms like
   `300-WWE-XXXX-AS1LC`, `50-ABL-XXXX-AS2LC`, `3"-P-62151007-BGA`.
7. **Merge before output** — the same line number from Pass 4 / continuation
   table / orientation pass / off-page connector / neighbouring ROI collapses to
   one record. Never emit duplicates.
8. **Coverage report** — write `line_coverage.json` (pipeline id, traced,
   line_number_found, extraction_source, validation_status). **QA only** — not
   exposed in any production API response.
9. **API-cost protection** — only query Vision for: traced pipes with no line
   number; detected line numbers that are incomplete; ROIs whose OCR validation
   failed; truncation signals. Never re-run Gemini on every pipe. Hard cap on
   ROI calls via `LINE_ORIENT_OCR_MAX_CALLS` (default 40).
10. **Production safety** — entire feature behind `LINE_ORIENT_OCR=1`. Unset →
    byte-identical behaviour, API usage, and output. No existing workflow
    changes.
11. **Success criteria** — increases recall; detects vertical & rotated
    annotations; removes truncated & duplicate line numbers; preserves
    production behaviour; no unnecessary Vision calls; fully compatible with
    `extractor.py`.

## Architecture

New module `line_orient_ocr.py` (repo root, beside `extractor.py`). Imports
`get_client`, `image_to_base64`, `extract_json_object`, `DEFAULT_MODEL` from
`extractor`, and `OpenCVLineTracer` / `LineSegment` from `webapp.graph.tracer`
(read-only use). **Never imports `detector.py`.**

Entry point: `apply_orientation_pass(job_dir, model=DEFAULT_MODEL) -> dict`.

### Steps

1. **Load state** — `canonical.json` (entities → `fields.line`, bbox),
   `line_list_data.json` (Pass-4 finds), full page `tmp/page_0_full.png`.
   Missing page or canonical → `{"skipped": ...}` (no-op).
2. **Inventory resolved line numbers** — normalise existing line numbers; mark
   which pass `_engineering_line_valid`. Incomplete/invalid ones become
   re-resolve targets (req 6, 9).
3. **Trace pipes** — `OpenCVLineTracer().trace(page_gray, bbox_mask)` →
   polylines. Build `bbox_mask` from `Job.gpu_detections` / canonical bboxes so
   symbol glyphs aren't traced (same approach as graph stage).
4. **Build unresolved candidate ROIs** from multiple sources (req 2, 3):
   - **pipe** — traced pipe with no existing line number nearby.
   - **truncated** — re-crop around an entity whose `fields.line` failed
     validation.
   - **edge-band** — right/bottom margin bands where continuation tables /
     off-page connector tables live.
   Cap total ROIs at `LINE_ORIENT_OCR_MAX_CALLS`.
5. **Per ROI: orientation sweep** (req 4, 5) — crop from full page; for each
   angle in [0, est_pipe_angle, 90, 270, 180] (deduped) rotate the crop
   horizontal, send to Vision with a focused single-line-number prompt, collect
   the returned string. Stop early once a candidate passes validation.
6. **Validate** (req 6) — `_engineering_line_valid`. Keep the most-complete
   passing candidate per ROI; tag with `extraction_source`.
7. **Merge** (req 7) — normalise + dedup against Pass-4 results and across ROIs;
   prefer the most complete value; record merged sources. Update
   `line_list_data.json` in place (only adds/repairs; never deletes Pass-4 data).
8. **Coverage report** (req 8) — write `line_coverage.json` for QA.

### Validation helper

```
_LINE_PREFIX_RE = ^\d+(?:/\d+)?"?$            # first segment is a numeric size
valid(s):
  parts = s.strip().upper().split("-")
  len(parts) >= 3
  _LINE_PREFIX_RE.match(parts[0])
  every part matches ^[A-Z0-9/".]+$ and is non-empty
```

Rejects `4"-X` (2 parts), `20"-W` (2 parts), `BGA` (1 part), `XXXX-AS1LC`
(first part not numeric). Accepts the approved examples.

### Pipeline integration

`webapp/pipeline_runner.py`, immediately after the Pass-4 block:

```python
if os.environ.get("LINE_ORIENT_OCR") == "1":
    try:
        from line_orient_ocr import apply_orientation_pass
        _po = apply_orientation_pass(str(job_dir))
        print(f"[graph-pass4.5] job {job_id}: {_po}")
    except Exception as _po_err:
        print(f"[graph-pass4.5] job {job_id}: {_po_err}", file=sys.stderr)
```

Flag unset → block is skipped entirely (req 10).

## Out of scope / untouched

`pdf_to_tiles` tiling, Neo4j, `GraphLayer.tsx` / `EdgeDetails` / draw-line /
`buildElements.ts`, `pipeline.py:15`, `detector.py`, production API responses.

## Validation plan

Run flagged on a real job (23 or 11); diff `line_list_data.json` vs current;
eyeball `line_coverage.json` against the drawing for recall/no-truncation/no-dupes.
