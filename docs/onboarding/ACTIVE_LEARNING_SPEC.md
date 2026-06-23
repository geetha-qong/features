# ACTIVE_LEARNING_SPEC.md

How reviewer corrections become better detection models. This is the accuracy flywheel that differentiates this product from a one-shot detector.

## Principle

A reviewer correction is worth ten synthetic training samples. The reviewer just told the model, with high confidence, that its prediction was wrong on a real-world sheet that matters to a paying customer. The pipeline must capture, label, store, and feed every one of these corrections back into model training.

The improvement loop targets the **two models that dominate accuracy on real P&IDs**:

1. **Symbol detector** (YOLOv11 → RT-DETR migration path)
2. **Line + direction model** (segmentation U-Net → Relationformer migration path)

Tag-OCR is fine-tuned less aggressively (PaddleOCR retraining is expensive and the wins are smaller). Association is rule-based; corrections feed thresholds, not weights.

## End-to-end data flow

```
Reviewer correction in UI
       |
       v
ReviewEvent written to Postgres (audit + replay)
       |
       v
TrainingEvent written to Postgres (separate table)
       |
       v
Hourly job: TrainingEvent rows -> per-model staging buckets in MinIO
       |
       v
Weekly job: staged examples + validation set -> training run on GPU
       |
       v
New model artifacts -> shadow inference + eval harness
       |
       v
If eval passes: signed bundle -> client update channel
If eval fails: roll back, alert, do not ship
```

## TrainingEvent schema

Separate from `ReviewEvent` so the training pipeline can be reasoned about without touching the audit log. One ReviewEvent can produce zero, one, or more TrainingEvents.

```python
class TrainingEvent(BaseModel):
    training_event_id: UUID
    source_review_event_id: UUID         # back-reference for audit
    sheet_id: UUID
    model_target: Literal[
        "symbol_detector",
        "line_segmenter",
        "direction_classifier",
        "ocr_finetune",
        "association_threshold"
    ]
    sample_type: Literal[
        "positive",                       # reviewer confirmed model was right
        "hard_negative",                  # reviewer said "this is not a valve"
        "corrected_label",                # reviewer changed class
        "corrected_geometry",             # reviewer moved/resized bbox
        "new_instance",                   # reviewer created an element model missed
        "deleted_instance"                # reviewer removed a false positive
    ]
    image_tile_ref: str                   # MinIO path to the image patch
    annotation: dict                      # YOLO/COCO/segmentation mask format depending on model_target
    quality_signal: float                 # see "Quality weighting" below
    created_at: datetime
    used_in_training_run: UUID | None     # NULL until consumed
```

## Per-stage handling

### Symbol detector

| Reviewer action | TrainingEvent |
|---|---|
| Confirm a high-confidence detection | `positive` (down-weighted; the model already got it right) |
| Confirm a low-confidence detection (<0.6) | `positive` (full weight; this is informative) |
| Change class | `corrected_label` (full weight) |
| Move or resize bbox | `corrected_geometry` (full weight) |
| Delete (false positive) | `hard_negative` (full weight) |
| Create new symbol model missed | `new_instance` (full weight) |
| Mark as bad detection | `hard_negative` (full weight) |

Output format: YOLO-compatible image tile + label file. Tile size 640 x 640 cropped around the corrected element with 80 px padding.

### Line segmenter

| Reviewer action | TrainingEvent |
|---|---|
| Confirm a line as-is | `positive` |
| Redraw a line | `corrected_geometry` — capture before AND after geometries |
| Delete a line | `hard_negative` |
| Create a line model missed | `new_instance` |
| Change line type (process / signal / electrical) | `corrected_label` |

Output format: image tile + a 1-channel segmentation mask. The mask is the union of all confirmed line pixels in that tile.

### Direction classifier

| Reviewer action | TrainingEvent |
|---|---|
| Confirm direction | `positive` |
| Flip direction | `corrected_label` |
| Add direction to a line that had none | `new_instance` |
| Remove direction from a bidirectional line | `corrected_label` |

Output format: image tile centered on the arrowhead region, plus a single discrete label (`up`, `down`, `left`, `right`, `none`, `bidirectional`).

### Association thresholds

Rule-based. No model retraining. Reviewer corrections feed a Bayesian update of the per-rule thresholds (e.g. "max distance from symbol to tag text for valid association"). This is a different machinery from the detector retraining and lives in `pipeline/associate/threshold_tuner.py`.

## Quality weighting

Not all corrections are equal. A reviewer who corrects 200 elements in an hour is signal. A reviewer who flips through and confirms everything in three minutes is noise.

`quality_signal` is computed per TrainingEvent as a function of:
- The reviewer's historical agreement rate with a second reviewer on the same sheets (we sample 5% of sheets for double-review; quality scores propagate from there)
- The `time_to_action_ms` field — implausibly fast (< 200 ms) actions are down-weighted
- The reviewer's seniority (set explicitly per user, never inferred)

`quality_signal` is in [0, 1]. The training loader uses it as the sample weight. Samples below 0.3 are discarded.

## Training cadence

- **Hourly:** TrainingEvent rows are picked up and converted into model-ready artifacts (tiles, masks, label files) in per-model MinIO buckets.
- **Weekly:** Full re-training run on the staging artifacts plus the held-back validation set. Triggered by a GitHub Action (when we wire CI) or manually.
- **Per-release:** Eval harness runs against a frozen "golden" test set of real P&IDs with hand-labeled ground truth. If the new model regresses on any metric in `PROJECT_VISION.md`, the release is blocked.

The "weekly" cadence is a starting point. Once we have a paying customer producing > 500 TrainingEvents per day, move to nightly. Do not move to continuous training in v1 — it is operationally expensive and the wins are marginal at this data volume.

## Eval harness

Single Python script: `training/eval/run.py`. Takes a model path and a test-set path. Produces a JSON report with:
- mAP@0.5 (symbols)
- Per-class precision and recall
- Line F1
- Direction F1
- End-to-end graph isomorphism score (using `networkx.is_isomorphic` on the predicted graph vs ground truth)
- Inference latency per A1 sheet on the target hardware

The graph isomorphism score is the headline metric. The others are diagnostic.

## Model versioning

Every model artifact is versioned `MAJOR.MINOR.PATCH`:
- `MAJOR` bumps when the model architecture changes
- `MINOR` bumps when the training data composition changes meaningfully (new client's data added)
- `PATCH` bumps for routine retraining

Artifacts are stored in MinIO at `models/{model_target}/{version}/`. The active model at a client site is pinned in `deploy/manifest.json` and changed only by signed update bundles.

## Rollback

If a deployed model regresses on a real client site (reviewer accuracy correction rate spikes), the client's sysadmin can run `deploy/rollback.sh` which atomically restores the previous version from the local model cache. No internet needed.

The rollback path must be tested in CI on every release. If it ever breaks, the release is blocked.

## What does NOT feed the loop

- Synthetic data (we already have it; corrections are the marginal signal)
- Test-set ground truth (never trains on data that evaluates it)
- Drafts and unsaved corrections (only persisted, confirmed corrections count)
- Reviewer actions on sheets marked "training disabled" (some customers will require this for confidential designs)

## A non-obvious failure mode to guard against

If the model gets too good at the kinds of sheets reviewers correct, it gets worse at the kinds of sheets reviewers confirm without thinking. The training loader must oversample `positive` events from sheets where the original model was wrong — not just from the easy ones. Otherwise the model collapses toward the median sheet style.

The technical mitigation: stratified sampling of `positive` events, weighted by the original detection confidence (lower confidence = higher sampling weight).

## When to consider abandoning this design

If, after six months of operation, the weekly retraining is not measurably improving any metric in `PROJECT_VISION.md`, the active learning loop is not working. Possible causes: not enough corrections, low-quality reviewers, model architecture is the bottleneck (not data). At that point, do NOT just keep training. Diagnose first.
