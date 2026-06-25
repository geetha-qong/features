"""Unit tests for the stale-detection predicate that decides whether stored
``gpu_detections`` should be re-inferred instead of trusted.

Root cause this guards (job 43, 2026-06-24): old jobs held detections from an
obsolete model whose class names (``valve_gen``/``valve_gl``) were dropped from
the 23-class taxonomy. The skip-guard in ``_run_inplace_inference`` trusted them
forever, so the graph was built from 7 stale boxes while the live model finds
268. We re-infer when any label is outside the current taxonomy.

Key constraint: the live Windows GPU worker still writes the LEGACY *schema*
(``yolo_class``/``bbox_tile``) but with CURRENT taxonomy names — that must NOT be
treated as stale, or every live GPU result gets clobbered.
"""
from webapp.pipeline_runner import _detections_are_stale


def test_empty_list_is_not_stale():
    assert _detections_are_stale([]) is False


def test_current_schema_current_taxonomy_is_not_stale():
    dets = [{"label": "valve_bv", "bbox": [0, 0, 1, 1]}]
    assert _detections_are_stale(dets) is False


def test_legacy_schema_current_taxonomy_is_not_stale():
    # Live GPU worker shape: yolo_class with a CURRENT taxonomy name.
    dets = [{"yolo_class": "valve_bv", "bbox_tile": [0, 0, 1, 1]}]
    assert _detections_are_stale(dets) is False


def test_obsolete_taxonomy_label_is_stale():
    # job 43's killer signal: valve_gen/valve_gl no longer exist in taxonomy.
    dets = [
        {"yolo_class": "valve_gen", "bbox_tile": [0, 0, 1, 1]},
        {"yolo_class": "valve_gl", "bbox_tile": [0, 0, 1, 1]},
    ]
    assert _detections_are_stale(dets) is True


def test_mixed_one_obsolete_label_is_stale():
    dets = [
        {"label": "valve_bv", "bbox": [0, 0, 1, 1]},
        {"label": "valve_gen", "bbox": [0, 0, 1, 1]},  # obsolete
    ]
    assert _detections_are_stale(dets) is True


def test_detections_without_any_label_are_not_stale():
    # No label/yolo_class at all — can't prove obsolete; leave it alone.
    dets = [{"bbox": [0, 0, 1, 1]}]
    assert _detections_are_stale(dets) is False
