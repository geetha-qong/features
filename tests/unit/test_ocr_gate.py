"""Unit tests for the OCR-completion gate (webapp/ocr_gate.py).

Pure-function tests — no DB, no app import beyond the module under test.
"""
import types
from datetime import datetime, timedelta, timezone

from webapp import ocr_gate


NOW = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def _ago(minutes):
    return NOW - timedelta(minutes=minutes)


# ── OCR_STALE_AFTER ────────────────────────────────────────────────────────────

def test_stale_after_is_20_minutes():
    assert ocr_gate.OCR_STALE_AFTER == timedelta(minutes=20)


# ── is_ocr_overdue ─────────────────────────────────────────────────────────────

def test_overdue_true_past_threshold():
    assert ocr_gate.is_ocr_overdue(_ago(21), now=NOW) is True


def test_overdue_false_within_threshold():
    assert ocr_gate.is_ocr_overdue(_ago(5), now=NOW) is False


def test_overdue_false_exactly_at_threshold():
    # Strictly greater-than: exactly 20 min is NOT yet overdue.
    assert ocr_gate.is_ocr_overdue(_ago(20), now=NOW) is False


def test_overdue_none_timestamp_is_not_overdue():
    assert ocr_gate.is_ocr_overdue(None, now=NOW) is False


def test_overdue_treats_naive_timestamp_as_utc():
    naive = (NOW - timedelta(minutes=21)).replace(tzinfo=None)
    assert ocr_gate.is_ocr_overdue(naive, now=NOW) is True


# ── effective_status ───────────────────────────────────────────────────────────

def test_status_done_pending_recent_is_processing():
    assert ocr_gate.effective_status("done", "pending", _ago(5), now=NOW) == "processing"


def test_status_done_pending_overdue_is_done():
    assert ocr_gate.effective_status("done", "pending", _ago(21), now=NOW) == "done"


def test_status_done_pending_null_ts_is_processing():
    assert ocr_gate.effective_status("done", "pending", None, now=NOW) == "processing"


def test_status_done_ocr_done_is_done():
    assert ocr_gate.effective_status("done", "done", None, now=NOW) == "done"


def test_status_done_ocr_null_is_done():
    # Legacy job: OCR never enqueued (#134) — must read "done".
    assert ocr_gate.effective_status("done", None, None, now=NOW) == "done"


def test_status_processing_passthrough():
    assert ocr_gate.effective_status("processing", None, None, now=NOW) == "processing"


def test_status_failed_passthrough():
    assert ocr_gate.effective_status("failed", "pending", _ago(99), now=NOW) == "failed"


# ── mark_ocr_pending ───────────────────────────────────────────────────────────

def test_mark_pending_sets_status_and_timestamp():
    job = types.SimpleNamespace(ocr_status=None, ocr_enqueued_at=None)
    ocr_gate.mark_ocr_pending(job, now=NOW)
    assert job.ocr_status == "pending"
    assert job.ocr_enqueued_at == NOW


def test_mark_pending_defaults_now_to_utc():
    job = types.SimpleNamespace(ocr_status=None, ocr_enqueued_at=None)
    ocr_gate.mark_ocr_pending(job)
    assert job.ocr_status == "pending"
    assert job.ocr_enqueued_at is not None
    assert job.ocr_enqueued_at.tzinfo is not None
