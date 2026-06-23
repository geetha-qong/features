# Self-Learning Loop — design (2026-06-17)

**Goal:** turn the human-in-the-loop corrections we already capture into a
**closed loop** that measurably improves the detection model + tag/graph quality
over time, with safety gates. "Earliest achievable" = ship the measurement +
aggregation first (high value, low risk), then the gated retrain.

## Key insight: capture is ~80% built. The missing links are MEASURE → RETRAIN → GATE → PROMOTE.

### What already exists (verified 2026-06-17)
| Stage | Exists today | Where |
|---|---|---|
| Capture detection corrections | `model_corrections` (action add/delete/reclassify + `new_bbox`/`new_label`) | `models.py:196`, written by `annotations.py` POST |
| Capture marked symbols | `user_annotations` (user_added/confirmed/rejected, bbox, tag, sub_class) | `models.py`, `annotations.py` |
| Capture corrected tags/fields | `entity_overrides` + the annotation→canonical sync (#55) + AI re-read (#57/#58) | `entities.py`, `annotations.py` |
| Capture graph corrections | `graph_corrections` (user_added/confirmed/rejected edges, directed) | `models.py`, `edges.py` |
| Export → YOLO labels | `export_annotations_for_yolo.py` (UserAnnotation user_added/confirmed → tile `<cls> cx cy w h`) | `webapp/scripts/` |
| Export → graph training | `export_graph_for_training.py` (JSONL, incl. `directed` per #53) | `webapp/scripts/` |
| Train | `train_gpu.py` / `train.py` + AWS burst (g5.xlarge spot) — trained v1-10/v1-11 | repo root, FEATURES #02/#42 |
| Deploy model | ONNX swap baked into image | FEATURES #30/#42 (manual) |

### What's missing (the loop's open links)
1. **MEASURE — correction-rate surface (build FIRST).** A dashboard of accept /
   reject / reclassify / tag-edit rates **per class and per job**. This:
   - quantifies model weakness → *where* to retrain (active learning), and
   - directly answers the recurring "OCR/tag names are wrong" question with real
     numbers (per-class tag-edit rate). No retraining needed to start delivering value.
2. **AGGREGATE — one versioned training-set builder.** Unify the two exporters +
   tag corrections into a single dated dataset (YOLO dir for detection, JSONL for
   graph/tags), with a manifest (counts per class, source job ids, since-date).
3. **TRIGGER — "retrain readiness".** A counter: "N new labeled corrections since
   model v1-11". Surface it; retrain when it crosses a threshold (manual button first).
4. **EVALUATE + GATE — the safety valve.** Before promoting a candidate model, run
   it on a frozen holdout and compare to prod: detection recall (target ≥90%,
   CLAUDE.md) + graph isomorphism (`networkx.is_isomorphic`, the headline metric).
   Promote ONLY if not worse. Never auto-promote without this gate.
5. **PROMOTE / ROLLBACK — versioned model registry.** One-click promote (swap ONNX
   + redeploy) + instant rollback to the previous version.

## Phased plan (earliest value first)

**Phase 1 — Measurement + Aggregation (days, low risk, high value).**
- `corrections_summary` admin surface: per-class & per-job accept/reject/reclassify
  + tag-edit rates, from `model_corrections` + `user_annotations` + `entity_overrides`.
  Ship as `/api/v1/admin/learning/summary` + a small `/admin/learning` page.
- `build_training_set` script: merges the existing exporters + tag corrections into
  `datasets/learning/<date>/` with a `manifest.json` (class counts, job ids, since).
- "Retrain readiness" number on the same page (new-corrections-since-v1-11).
- **DoD:** the page shows real per-class error rates on dev; the builder produces a
  manifest. This alone makes the system *measurably* self-aware.

**Phase 2 — Gated retrain (the actual loop).**
- One-click / cron retrain that calls the AWS burst trainer on the latest dataset.
- Eval harness: candidate vs prod on a frozen holdout (recall + graph isomorphism);
  emit a comparison report; block promotion if worse.
- Versioned model registry + promote/rollback (extends the v1-N ONNX-swap path).
- **DoD:** a correction → (threshold) → retrain → eval-gate → promote happens with
  one human approval; rollback is one click.

**Phase 3 — Tighten the cadence.** Auto-trigger on threshold; weekly cadence;
per-class targeted retraining for the weakest classes the Phase-1 surface flags.

## Principles
- **Never auto-promote without the eval gate.** A bad model silently shipping is
  worse than slow improvement.
- **Human stays in the loop** at promotion (Phase 1/2); automation tightens later.
- **Measurement before automation** — you can't improve (or trust) what you can't measure.
- Headline metrics stay: ≥90% detection recall + graph isomorphism vs human ground truth.

## Recommended first task
Build **Phase 1** — the correction-rate measurement surface + training-set builder.
Highest leverage, lowest risk, and it doubles as the quantified answer to "how
wrong are our tags/detections?" that's been asked repeatedly this week.
