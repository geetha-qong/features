"""Unit tests for the graph-only backfill guard (FEATURES #123).

The decision guard must REFUSE any job that would require re-inference or has no
output dir, so the backfill can never silently re-run YOLO or a deliverables
pipeline (honours the "never auto-rerun jobs" policy).
"""
import json
import types

from webapp.scripts.backfill_graph import _backfill_decision, _detections


def _job(**kw):
    kw.setdefault("output_csv_path", "/app/job_outputs/38/out.csv")
    kw.setdefault("gpu_detections", json.dumps([{"label": "valve_bv", "bbox": [0, 0, 1, 1]}]))
    return types.SimpleNamespace(**kw)


# ── _detections ────────────────────────────────────────────────────────────────

def test_detections_parses_json_string():
    job = _job(gpu_detections=json.dumps([{"label": "x"}]))
    assert _detections(job) == [{"label": "x"}]


def test_detections_none_is_empty():
    assert _detections(_job(gpu_detections=None)) == []


def test_detections_bad_json_is_empty():
    assert _detections(_job(gpu_detections="{nope")) == []


# ── _backfill_decision ──────────────────────────────────────────────────────────

def test_decision_ok_for_fresh_job_with_dets():
    job = _job()
    ok, reason = _backfill_decision(job, _detections(job), stale=False)
    assert ok is True and reason == "ok"


def test_decision_refuses_missing_job():
    ok, reason = _backfill_decision(None, [], stale=False)
    assert ok is False and reason == "MISSING"


def test_decision_refuses_no_detections():
    job = _job(gpu_detections=None)
    ok, reason = _backfill_decision(job, [], stale=False)
    assert ok is False
    assert "backfill_gpu_detections" in reason


def test_decision_refuses_stale_detections():
    job = _job()
    ok, reason = _backfill_decision(job, _detections(job), stale=True)
    assert ok is False
    assert "STALE" in reason


def test_decision_refuses_no_output_path():
    job = _job(output_csv_path=None)
    ok, reason = _backfill_decision(job, _detections(job), stale=False)
    assert ok is False
    assert "output_csv_path" in reason
