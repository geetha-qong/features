"""Unit tests for background-OCR detections-tagged (FEATURES #122).

The GET endpoint must return instantly: serve cache when present, answer
"empty" inline when there's nothing to OCR, otherwise enqueue the heavy
pipeline on the cpu-worker and return ocr_status="pending". The OCR pipeline
itself moves to `compute_tagged_detections` / `run_detections_ocr_rq`.
"""
import json
import types

import pytest

from webapp.routers import bbox_ocr


# ── _parse_raw_detections ──────────────────────────────────────────────────────

def test_parse_none_is_empty():
    job = types.SimpleNamespace(gpu_detections=None)
    assert bbox_ocr._parse_raw_detections(job) == []


def test_parse_invalid_json_is_empty():
    job = types.SimpleNamespace(gpu_detections="{not json")
    assert bbox_ocr._parse_raw_detections(job) == []


def test_parse_non_list_is_empty():
    job = types.SimpleNamespace(gpu_detections=json.dumps({"a": 1}))
    assert bbox_ocr._parse_raw_detections(job) == []


def test_parse_valid_list():
    dets = [{"label": "valve_bv", "bbox": [0, 0, 1, 1]}]
    job = types.SimpleNamespace(gpu_detections=json.dumps(dets))
    assert bbox_ocr._parse_raw_detections(job) == dets


# ── compute_tagged_detections (empty path, no OCR calls) ───────────────────────

def test_compute_empty_writes_terminal_cache(tmp_path):
    job = types.SimpleNamespace(
        gpu_detections=None,
        output_csv_path=str(tmp_path / "out.csv"),
    )
    result = bbox_ocr.compute_tagged_detections(job)
    assert result == {"detections": [], "ocr_run": False, "ocr_status": "empty"}
    cached = json.loads((tmp_path / "detections_ocr.json").read_text())
    assert cached["ocr_status"] == "empty"


# ── endpoint decision logic (called directly with fakes) ───────────────────────

class _FakeQuery:
    def __init__(self, job):
        self._job = job

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._job


class _FakeDB:
    def __init__(self, job):
        self._job = job

    def query(self, _model):
        return _FakeQuery(self._job)


def _user(uid=1, role="user"):
    return types.SimpleNamespace(id=uid, role=role)


def test_endpoint_enqueues_and_returns_pending(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bbox_ocr, "_enqueue_detections_ocr", lambda jid: calls.append(jid))
    job = types.SimpleNamespace(
        id=5, user_id=1,
        gpu_detections=json.dumps([{"label": "valve_bv", "bbox": [0, 0, 1, 1], "tile": "t.png"}]),
        output_csv_path=str(tmp_path / "out.csv"),  # no cache file present
    )
    resp = bbox_ocr.api_job_detections_tagged(
        job_id=5, refresh=False, current_user=_user(), db=_FakeDB(job),
    )
    assert resp == {"detections": [], "ocr_run": False, "ocr_status": "pending"}
    assert calls == [5]


def test_endpoint_empty_answers_inline_without_enqueue(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bbox_ocr, "_enqueue_detections_ocr", lambda jid: calls.append(jid))
    job = types.SimpleNamespace(
        id=5, user_id=1, gpu_detections=None,
        output_csv_path=str(tmp_path / "out.csv"),
    )
    resp = bbox_ocr.api_job_detections_tagged(
        job_id=5, refresh=False, current_user=_user(), db=_FakeDB(job),
    )
    assert resp["ocr_status"] == "empty"
    assert calls == []  # nothing to OCR → no background job


def test_endpoint_serves_cache_as_ready(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bbox_ocr, "_enqueue_detections_ocr", lambda jid: calls.append(jid))
    cache = tmp_path / "detections_ocr.json"
    cache.write_text(json.dumps({
        "detections": [{"label": "valve_bv", "entity_tag": "62-BV-1"}],
        "ocr_run": True, "valve_ocr_run": True,
    }))
    job = types.SimpleNamespace(
        id=5, user_id=1, gpu_detections=json.dumps([{"label": "x"}]),
        output_csv_path=str(tmp_path / "out.csv"),
    )
    resp = bbox_ocr.api_job_detections_tagged(
        job_id=5, refresh=False, current_user=_user(), db=_FakeDB(job),
    )
    assert resp["ocr_run"] is True
    assert resp["ocr_status"] == "ready"   # set via setdefault on legacy cache
    assert calls == []                      # cache hit → no enqueue


def test_endpoint_read_backfill_stays_1to1(tmp_path, monkeypatch):
    """The read-time tag->entity_id backfill must not re-bind an entity to more
    than one detection. Two same-tag detections (one already bound, one that
    enforce_one_to_one had left unmatched) must NOT both end up bound to the same
    canonical entity when served from cache."""
    monkeypatch.setattr(bbox_ocr, "_enqueue_detections_ocr", lambda jid: None)
    cache = tmp_path / "detections_ocr.json"
    cache.write_text(json.dumps({
        "detections": [
            {"label": "valve_bv", "entity_tag": "62-BV-1", "entity_id": "E1", "confidence": 0.9},
            # enforce_one_to_one left this one unmatched (entity_id None, tag kept):
            {"label": "valve_bv", "entity_tag": "62-BV-1", "entity_id": None, "confidence": 0.6},
        ],
        "ocr_run": True, "valve_ocr_run": True,
    }))
    job = types.SimpleNamespace(
        id=5, user_id=1, gpu_detections=json.dumps([{"label": "x"}]),
        output_csv_path=str(tmp_path / "out.csv"),
    )

    class _Ent:
        def __init__(self, tag, eid, cls):
            self.tag, self.entity_id, self.entity_class = tag, eid, cls

    class _Canon:
        entities = [_Ent("62-BV-1", "E1", "valve")]

    import webapp.deliverables.job_loader as jl
    monkeypatch.setattr(jl, "load_canonical_for_job", lambda _p: _Canon())

    resp = bbox_ocr.api_job_detections_tagged(
        job_id=5, refresh=False, current_user=_user(), db=_FakeDB(job),
    )
    bound = [d for d in resp["detections"] if d.get("entity_id") == "E1"]
    assert len(bound) == 1  # exactly one detection bound to the entity, not two


def test_endpoint_403_for_other_users_job():
    from fastapi import HTTPException
    job = types.SimpleNamespace(id=5, user_id=999, gpu_detections=None, output_csv_path=None)
    with pytest.raises(HTTPException) as ei:
        bbox_ocr.api_job_detections_tagged(
            job_id=5, refresh=False, current_user=_user(uid=1, role="user"), db=_FakeDB(job),
        )
    assert ei.value.status_code == 403


# ── enqueue dedup ──────────────────────────────────────────────────────────────

def test_enqueue_dedups_when_job_already_running(monkeypatch):
    rq = pytest.importorskip("rq")
    from rq.exceptions import NoSuchJobError  # noqa: F401

    class _FakeQ:
        def __init__(self):
            self.connection = object()
            self.enqueued = []

        def enqueue(self, *a, **k):
            self.enqueued.append((a, k))

    fake_q = _FakeQ()
    monkeypatch.setattr("webapp.queue.get_cpu_queue", lambda: fake_q)

    # Case 1: no existing job → fetch raises NoSuchJobError → enqueue happens.
    def _fetch_missing(rq_id, connection=None):
        raise NoSuchJobError("nope")

    monkeypatch.setattr("rq.job.Job.fetch", staticmethod(_fetch_missing))
    bbox_ocr._enqueue_detections_ocr(5)
    assert len(fake_q.enqueued) == 1
    assert fake_q.enqueued[0][1]["job_id"] == "detections-ocr-5"

    # Case 2: an in-flight job exists → no second enqueue.
    fake_q.enqueued.clear()
    running = types.SimpleNamespace(
        get_status=lambda refresh=False: "started",
        delete=lambda: pytest.fail("must not delete an in-flight job"),
    )
    monkeypatch.setattr("rq.job.Job.fetch", staticmethod(lambda rq_id, connection=None: running))
    bbox_ocr._enqueue_detections_ocr(5)
    assert fake_q.enqueued == []

    # Case 3: a FINISHED job holds the id → delete it, then re-enqueue (so an
    # explicit recompute isn't silently dropped within result_ttl).
    fake_q.enqueued.clear()
    deleted = []
    finished = types.SimpleNamespace(
        get_status=lambda refresh=False: "finished",
        delete=lambda: deleted.append(True),
    )
    monkeypatch.setattr("rq.job.Job.fetch", staticmethod(lambda rq_id, connection=None: finished))
    bbox_ocr._enqueue_detections_ocr(5)
    assert deleted == [True]
    assert len(fake_q.enqueued) == 1
