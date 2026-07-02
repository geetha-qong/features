# Resilient OCR-Completion Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A job's dashboard card must never trap at "Preparing" when the background OCR step stalls or dies — keep the hard gate, make it self-heal.

**Architecture:** Three layers share one gate module (`webapp/ocr_gate.py`): (1) a *pure* read-time backstop in the async list/status endpoints displays an overdue-pending job as "done" without any DB write; (2) the cpu-worker OCR runner gets an automatic RQ retry plus a try/except that persists a terminal `done` on failure; (3) a startup leader-gated sweep persists `done` for jobs stuck pending past the timeout. A new nullable `Job.ocr_enqueued_at` timestamp anchors the timeout.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy, RQ (Redis Queue) for the cpu-worker, pytest. No Alembic (migrations live in `webapp/database.py:run_migrations()`).

## Global Constraints

- **Branch base is `dev`.** This plan is being executed on `feat/resilient-ocr-gate` (already created off `origin/dev`). The `Job.ocr_status` column, `_effective_status`, and `run_detections_ocr_rq` only exist on `dev` — never `feat/graph-gt-freeze`.
- **Never put a blocking synchronous call (DB I/O) inside an `async def` endpoint** — it freezes the worker event loop. The read-path helpers MUST be pure (no DB, no network). `api_list_jobs` and `job_status` are `async def`.
- **Timeout = exactly 20 minutes**, expressed once as `OCR_STALE_AFTER = timedelta(minutes=20)` in `webapp/ocr_gate.py`. Every layer imports this constant — no duplicated literals.
- **Released state is the string `"done"`** — no new `"ocr_failed"` status, no badge.
- **UTC on the wire.** Use timezone-aware UTC datetimes (`datetime.now(timezone.utc)`), never naive `datetime.now()`. The new column is `DateTime(timezone=True)` / `TIMESTAMPTZ`.
- **A NULL `ocr_enqueued_at` is NOT overdue in the read path** (held at "processing"); it IS swept on startup. This is the migration-transition behavior.
- **Use `Optional[X]`, not `X | None`. Use `python3`, not `python`.**
- Host pytest needs `SECRET_KEY` ≥32 chars or `webapp/config.py` exits. Run tests with: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest <path> -v`. Inside the container: `docker compose exec -T web python3 -m pytest <path> -v` (no SECRET_KEY needed there).

---

### Task 1: `ocr_gate` module — constant + pure read-path logic + pending mutator

**Files:**
- Create: `webapp/ocr_gate.py`
- Test: `tests/unit/test_ocr_gate.py`

**Interfaces:**
- Consumes: nothing (pure stdlib at module load).
- Produces (consumed by Tasks 3, 4, 6):
  - `OCR_STALE_AFTER: timedelta` (20 minutes)
  - `is_ocr_overdue(ocr_enqueued_at: Optional[datetime], now: Optional[datetime] = None) -> bool`
  - `effective_status(status: Optional[str], ocr_status: Optional[str], ocr_enqueued_at: Optional[datetime], now: Optional[datetime] = None) -> str`
  - `mark_ocr_pending(job, now: Optional[datetime] = None) -> None` (sets `job.ocr_status = "pending"` and `job.ocr_enqueued_at`)
  - `sweep_stale_ocr(db, now=None) -> int` is added in **Task 6** (it needs the model + column), not here.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ocr_gate.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.ocr_gate'`.

- [ ] **Step 3: Write the module**

Create `webapp/ocr_gate.py`:

```python
"""OCR-completion gate — shared logic so a job's card never traps at "Preparing".

A job is held at "processing" (UI: "Preparing") while extraction is done but the
background OCR tag-resolution step is still pending. This module centralizes that
rule and its timeout so the read path (dashboard list, job status), the
pending-set sites, and the startup reconcile sweep all agree.

The read-path helpers (`is_ocr_overdue`, `effective_status`) are PURE — no DB, no
network — so they are safe to call inside the `async def` endpoints. CLAUDE.md:
never block an async event loop with a synchronous DB call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# A job whose OCR has been pending longer than this is auto-released to "done"
# (graceful degradation — detections simply lack OCR-resolved tag enrichment).
# Above a normal multi-minute run AND above a single 15-min RQ attempt, so a
# still-working job is never falsely released.
OCR_STALE_AFTER = timedelta(minutes=20)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a (possibly naive / non-UTC) datetime to aware-UTC. Naive is
    assumed UTC to match the codebase write convention."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_ocr_overdue(
    ocr_enqueued_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """True iff OCR was enqueued strictly more than OCR_STALE_AFTER ago.

    A NULL enqueue time is NOT overdue (legacy jobs, or pendings set before this
    change) — the startup sweep clears those, the read path does not.
    """
    enq = _as_utc(ocr_enqueued_at)
    if enq is None:
        return False
    return (_as_utc(now) or _utcnow()) - enq > OCR_STALE_AFTER


def effective_status(
    status: Optional[str],
    ocr_status: Optional[str],
    ocr_enqueued_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """Dashboard-facing status.

    Hold at "processing" only while extraction is done AND OCR is actively
    pending AND it has not been pending past the stale timeout. Otherwise return
    the raw status (a done job with done / NULL / overdue OCR reads "done").
    """
    if (
        status == "done"
        and ocr_status == "pending"
        and not is_ocr_overdue(ocr_enqueued_at, now)
    ):
        return "processing"
    return status


def mark_ocr_pending(job, now: Optional[datetime] = None) -> None:
    """Set a job's OCR stage to pending and stamp the enqueue time.

    Called at every site that enqueues background OCR so the stale timeout has a
    reference point. Mutates `job` in place; the caller commits.
    """
    job.ocr_status = "pending"
    job.ocr_enqueued_at = now or _utcnow()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_gate.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add webapp/ocr_gate.py tests/unit/test_ocr_gate.py
git commit -m "feat(ocr-gate): shared gate module — OCR_STALE_AFTER, effective_status, mark_ocr_pending"
```

---

### Task 2: `Job.ocr_enqueued_at` column (model + migration)

**Files:**
- Modify: `webapp/models.py:45` (add column after `ocr_status`)
- Modify: `webapp/database.py` (append to `new_columns` list)
- Test: `tests/unit/test_ocr_enqueued_at_column.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Job.ocr_enqueued_at` (nullable `DateTime(timezone=True)`), consumed by Tasks 3, 4, 6.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ocr_enqueued_at_column.py`:

```python
"""The Job model must carry a nullable, timezone-aware ocr_enqueued_at column,
and it must round-trip a UTC datetime through the ORM."""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp.database import Base
from webapp import models


def test_model_has_ocr_enqueued_at_column():
    assert "ocr_enqueued_at" in models.Job.__table__.columns


def test_ocr_enqueued_at_roundtrips_utc():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        ts = datetime(2026, 6, 30, 9, 30, tzinfo=timezone.utc)
        job = models.Job(
            user_id=1, original_filename="x.pdf", stored_filename="x.pdf",
            status="done", ocr_status="pending", ocr_enqueued_at=ts,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.ocr_enqueued_at is not None
        # SQLite returns naive; treat as UTC and compare the instant.
        got = job.ocr_enqueued_at
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        assert got == ts
    finally:
        session.close()
        engine.dispose()


def test_ocr_enqueued_at_defaults_null():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        job = models.Job(
            user_id=1, original_filename="x.pdf", stored_filename="x.pdf",
            status="done",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.ocr_enqueued_at is None
    finally:
        session.close()
        engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_enqueued_at_column.py -v`
Expected: FAIL — `test_model_has_ocr_enqueued_at_column` asserts the column is absent; the round-trip test errors with an unknown kwarg `ocr_enqueued_at`.

- [ ] **Step 3: Add the column to the model**

In `webapp/models.py`, immediately after line 45 (`ocr_status = Column(...)`), add:

```python
    ocr_enqueued_at = Column(DateTime(timezone=True), nullable=True)  # when bbox OCR was last enqueued — anchors the stale-gate timeout (resilient-ocr-gate)
```

(`DateTime` and `Column` are already imported in `models.py`.)

- [ ] **Step 4: Add the migration entry**

In `webapp/database.py`, append to the `new_columns` list (right after the `("jobs", "ocr_status", "TEXT"),` entry):

```python
        # Stale-gate anchor (resilient-ocr-gate): when bbox OCR was last enqueued.
        # TIMESTAMPTZ on Postgres; SQLite gives it NUMERIC affinity and stores ISO.
        ("jobs", "ocr_enqueued_at", "TIMESTAMPTZ"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_enqueued_at_column.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/models.py webapp/database.py tests/unit/test_ocr_enqueued_at_column.py
git commit -m "feat(ocr-gate): add nullable Job.ocr_enqueued_at column + migration"
```

---

### Task 3: Stamp `ocr_enqueued_at` at every pending-set site

**Files:**
- Modify: `webapp/routers/bbox_ocr.py` (the pending-set block inside `_enqueue_detections_ocr`)
- Modify: `webapp/pipeline_runner.py:~466` (the `job.ocr_status = "pending"` line)
- Test: `tests/unit/test_ocr_enqueue_stamps_timestamp.py`

**Interfaces:**
- Consumes: `webapp.ocr_gate.mark_ocr_pending` (Task 1), `Job.ocr_enqueued_at` (Task 2).
- Produces: both pending-set sites now stamp the timestamp.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ocr_enqueue_stamps_timestamp.py`:

```python
"""_enqueue_detections_ocr must stamp ocr_enqueued_at when it marks a job pending
(so the stale-gate timeout has a reference point)."""
from datetime import timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rq.exceptions import NoSuchJobError

from webapp.database import Base
from webapp import models
from webapp.routers import bbox_ocr


class _FakeQueue:
    def __init__(self):
        self.connection = object()
        self.enqueued = []

    def enqueue(self, *args, **kwargs):
        self.enqueued.append((args, kwargs))


def _mem_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_enqueue_stamps_ocr_enqueued_at(monkeypatch):
    session, engine = _mem_session()
    try:
        job = models.Job(user_id=1, original_filename="x.pdf",
                         stored_filename="x.pdf", status="done", ocr_status=None)
        session.add(job)
        session.commit()
        job_id = job.id

        # No existing RQ job; capture the enqueue; route the function's
        # SessionLocal() at our in-memory session.
        fake_q = _FakeQueue()
        monkeypatch.setattr(bbox_ocr, "get_cpu_queue", lambda: fake_q, raising=False)

        def _raise_fetch(*a, **k):
            raise NoSuchJobError("none")
        monkeypatch.setattr("rq.job.Job.fetch", staticmethod(_raise_fetch))
        monkeypatch.setattr(bbox_ocr, "SessionLocal", lambda: session)

        bbox_ocr._enqueue_detections_ocr(job_id)

        session.expire_all()
        refreshed = session.query(models.Job).get(job_id)
        assert refreshed.ocr_status == "pending"
        assert refreshed.ocr_enqueued_at is not None
    finally:
        session.close()
        engine.dispose()
```

> Note: `get_cpu_queue` and `SessionLocal` are imported names used inside `_enqueue_detections_ocr`. `get_cpu_queue` is imported *inside* the function (`from webapp.queue import get_cpu_queue`), so `monkeypatch.setattr(bbox_ocr, "get_cpu_queue", ...)` only works if the implementation in Step 3 also exposes/uses a module-level reference. The implementer must verify the monkeypatch target resolves; if `get_cpu_queue` stays a function-local import, patch `webapp.queue.get_cpu_queue` instead. Pick whichever the running code actually calls and make the test target match.

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_enqueue_stamps_timestamp.py -v`
Expected: FAIL — `ocr_enqueued_at` is `None` after enqueue (the code sets only `ocr_status`).

- [ ] **Step 3: Wire `mark_ocr_pending` into `bbox_ocr._enqueue_detections_ocr`**

In `webapp/routers/bbox_ocr.py`, find the pending-set block at the end of `_enqueue_detections_ocr`:

```python
        # Mark pending so dashboard holds "Done" until OCR finishes
        try:
            db = SessionLocal()
            job = db.query(models.Job).filter(models.Job.id == job_id).first()
            if job and job.ocr_status != "done":
                job.ocr_status = "pending"
                db.commit()
            db.close()
        except Exception:
            pass
```

Replace the inner set with `mark_ocr_pending` (add `from webapp.ocr_gate import mark_ocr_pending` to the module's imports near the top):

```python
        # Mark pending + stamp enqueue time so the dashboard holds "Done" until
        # OCR finishes and the stale-gate timeout has a reference point.
        try:
            db = SessionLocal()
            job = db.query(models.Job).filter(models.Job.id == job_id).first()
            if job and job.ocr_status != "done":
                mark_ocr_pending(job)
                db.commit()
            db.close()
        except Exception:
            pass
```

- [ ] **Step 4: Wire `mark_ocr_pending` into `pipeline_runner.py`**

In `webapp/pipeline_runner.py`, find (≈ line 463-466):

```python
            from webapp.routers.bbox_ocr import _enqueue_detections_ocr
            job.ocr_status = "pending"
            db.commit()
            _enqueue_detections_ocr(job_id)
```

Replace the `job.ocr_status = "pending"` line:

```python
            from webapp.routers.bbox_ocr import _enqueue_detections_ocr
            from webapp.ocr_gate import mark_ocr_pending
            mark_ocr_pending(job)
            db.commit()
            _enqueue_detections_ocr(job_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_enqueue_stamps_timestamp.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/routers/bbox_ocr.py webapp/pipeline_runner.py tests/unit/test_ocr_enqueue_stamps_timestamp.py
git commit -m "feat(ocr-gate): stamp ocr_enqueued_at at both pending-set sites"
```

---

### Task 4: Read-time backstop in the list + status endpoints

**Files:**
- Modify: `webapp/routers/api_v1.py` (`_effective_status` nested in `api_list_jobs`, ≈ line 202)
- Modify: `webapp/routers/jobs.py` (`job_status`, ≈ line 161-163)
- Test: `tests/unit/test_api_v1.py` (extend the existing "OCR Done-gate" section)

**Interfaces:**
- Consumes: `webapp.ocr_gate.effective_status` (Task 1), `Job.ocr_enqueued_at` (Task 2).
- Produces: both endpoints display an overdue-pending job as "done" with **no DB write**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_api_v1.py`, in the "GET /api/v1/jobs (list / dashboard) — OCR Done-gate" section (after `test_list_done_job_with_ocr_done_reads_done`):

```python
def test_list_done_pending_overdue_reads_done(client, db_session, user, api_key_pair):
    """A job stuck pending past OCR_STALE_AFTER must auto-release to 'done' in the
    read path — never trap at 'Preparing' — without persisting anything."""
    from datetime import timezone
    from webapp.ocr_gate import OCR_STALE_AFTER
    from webapp.datetime_utils import utcnow
    overdue = utcnow() - OCR_STALE_AFTER - __import__("datetime").timedelta(minutes=1)
    job = models.Job(user_id=user.id, pid_no="T-103", status="done",
                     original_filename="stuck.pdf", stored_filename="stuck.pdf",
                     ocr_status="pending", ocr_enqueued_at=overdue)
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    full_key, _ = api_key_pair
    assert _list_status_for(client, full_key, job_id) == "done"

    # Read path must NOT persist — DB still says pending.
    db_session.expire_all()
    assert db_session.query(models.Job).get(job_id).ocr_status == "pending"


def test_list_done_pending_recent_reads_processing(client, db_session, user, api_key_pair):
    """A job pending only a few minutes is still legitimately working — hold it."""
    from webapp.datetime_utils import utcnow
    recent = utcnow() - __import__("datetime").timedelta(minutes=3)
    job = models.Job(user_id=user.id, pid_no="T-104", status="done",
                     original_filename="working.pdf", stored_filename="working.pdf",
                     ocr_status="pending", ocr_enqueued_at=recent)
    db_session.add(job)
    db_session.commit()

    full_key, _ = api_key_pair
    assert _list_status_for(client, full_key, job.id) == "processing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_api_v1.py -k "overdue or recent" -v`
Expected: `test_list_done_pending_overdue_reads_done` FAILS (returns "processing" — the current gate ignores the timestamp). `test_list_done_pending_recent_reads_processing` passes (current behavior already holds pending).

- [ ] **Step 3: Wire `effective_status` into `api_v1.py`**

In `webapp/routers/api_v1.py`, add the import near the top (with the other `from webapp...` imports):

```python
from webapp.ocr_gate import effective_status
```

Replace the nested `_effective_status` helper inside `api_list_jobs` (≈ lines 202-213) and its call. Current:

```python
    def _effective_status(job) -> str:
        # Hold a job at "processing" only while OCR is ACTIVELY pending, so the
        # card stays "Preparing" until OCR-resolved tags are ready (#132). A NULL
        # ocr_status means OCR was never enqueued (legacy jobs predating the
        # column, or pipelines that didn't dispatch OCR) — those are genuinely
        # done and must not be masked as processing.
        if job.status == "done" and job.ocr_status == "pending":
            return "processing"
        return job.status
```

Replace with a thin delegation to the shared gate (which now also releases overdue pendings):

```python
    def _effective_status(job) -> str:
        # Hold at "processing" while OCR is actively pending, EXCEPT once it has
        # been pending past the stale timeout — then release to "done" so a stuck
        # OCR can never trap the card at "Preparing" (resilient-ocr-gate).
        # Pure computation — no DB write (this is an async endpoint).
        return effective_status(job.status, job.ocr_status, job.ocr_enqueued_at)
```

- [ ] **Step 4: Wire `effective_status` into `jobs.py`**

In `webapp/routers/jobs.py`, add the import near the top with the other imports:

```python
from webapp.ocr_gate import effective_status as _ocr_effective_status
```

Replace the inline block (≈ lines 158-163):

```python
    # Effective status: hold at "processing" only while OCR is ACTIVELY pending,
    # so the dashboard shows "Done" once extraction is finished and OCR is either
    # complete or was never enqueued (NULL — legacy jobs / non-OCR pipelines).
    # Gating on `!= "done"` masked every pre-OCR-column job as processing.
    effective_status = job.status
    if job.status == "done" and job.ocr_status == "pending":
        effective_status = "processing"
```

With:

```python
    # Effective status: hold at "processing" while OCR is actively pending,
    # except once it has been pending past the stale timeout — then release to
    # "done" so a stuck OCR can never trap the card (resilient-ocr-gate). Pure
    # computation; no DB write (async endpoint).
    effective_status = _ocr_effective_status(
        job.status, job.ocr_status, job.ocr_enqueued_at
    )
```

> Note: the local variable is still named `effective_status` and is used on the next lines (`"status": effective_status`). The import is aliased to `_ocr_effective_status` precisely to avoid shadowing that local. Verify the `JSONResponse` below still reads the local `effective_status`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_api_v1.py -k "ocr or overdue or recent or done_job or null_ocr" -v`
Expected: PASS — including the three pre-existing #134 gate tests (no regression) and the two new overdue/recent tests.

- [ ] **Step 6: Commit**

```bash
git add webapp/routers/api_v1.py webapp/routers/jobs.py tests/unit/test_api_v1.py
git commit -m "feat(ocr-gate): read-time backstop releases overdue-pending jobs (no DB write)"
```

---

### Task 5: Worker failure reflection + one automatic RQ retry

**Files:**
- Modify: `webapp/routers/bbox_ocr.py` (`run_detections_ocr_rq` try/except; `_enqueue_detections_ocr` `q.enqueue(... retry=Retry(max=1))`)
- Test: `tests/unit/test_ocr_worker_failure.py`

**Interfaces:**
- Consumes: nothing new (uses `rq.Retry`).
- Produces: the OCR runner persists `ocr_status="done"` on failure (then re-raises); the enqueue requests one retry.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_ocr_worker_failure.py`:

```python
"""run_detections_ocr_rq must release the gate even when OCR computation fails,
and the enqueue must request one automatic retry to absorb transient
worker-kill (deploy) failures."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from rq.exceptions import NoSuchJobError

from webapp.database import Base
from webapp import models
from webapp.routers import bbox_ocr


def _mem_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_worker_persists_done_and_reraises_on_failure(monkeypatch):
    session, engine = _mem_session()
    try:
        job = models.Job(user_id=1, original_filename="x.pdf",
                         stored_filename="x.pdf", status="done", ocr_status="pending")
        session.add(job)
        session.commit()
        job_id = job.id

        monkeypatch.setattr(bbox_ocr, "SessionLocal", lambda: session)

        def _boom(_job):
            raise RuntimeError("OCR exploded")
        monkeypatch.setattr(bbox_ocr, "compute_tagged_detections", _boom)

        with pytest.raises(RuntimeError, match="OCR exploded"):
            bbox_ocr.run_detections_ocr_rq(job_id)

        session.expire_all()
        # Gate released despite the failure (graceful degradation).
        assert session.query(models.Job).get(job_id).ocr_status == "done"
    finally:
        session.close()
        engine.dispose()


def test_worker_success_marks_done(monkeypatch):
    session, engine = _mem_session()
    try:
        job = models.Job(user_id=1, original_filename="x.pdf",
                         stored_filename="x.pdf", status="done", ocr_status="pending")
        session.add(job)
        session.commit()
        job_id = job.id

        monkeypatch.setattr(bbox_ocr, "SessionLocal", lambda: session)
        monkeypatch.setattr(bbox_ocr, "compute_tagged_detections",
                            lambda _job: {"detections": [], "ocr_status": "ready"})

        result = bbox_ocr.run_detections_ocr_rq(job_id)
        assert result["ocr_status"] == "ready"
        session.expire_all()
        assert session.query(models.Job).get(job_id).ocr_status == "done"
    finally:
        session.close()
        engine.dispose()


def test_enqueue_requests_one_retry(monkeypatch):
    from rq import Retry

    captured = {}

    class _FakeQueue:
        def __init__(self):
            self.connection = object()

        def enqueue(self, *args, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(bbox_ocr, "get_cpu_queue", lambda: _FakeQueue(), raising=False)
    monkeypatch.setattr("rq.job.Job.fetch",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(NoSuchJobError("none"))))
    # Avoid touching a real DB in the pending-set block.
    monkeypatch.setattr(bbox_ocr, "SessionLocal", lambda: (_ for _ in ()).throw(Exception("skip")))

    bbox_ocr._enqueue_detections_ocr(123)

    retry = captured["kwargs"].get("retry")
    assert isinstance(retry, Retry)
    assert retry.max == 1
```

> Note on monkeypatch targets: `compute_tagged_detections`, `get_cpu_queue`, and `SessionLocal` must be patched on the object the running code actually resolves. If `get_cpu_queue` is a function-local import inside `_enqueue_detections_ocr`, patch `webapp.queue.get_cpu_queue` instead of `bbox_ocr.get_cpu_queue` and drop `raising=False`. The implementer verifies which resolves and aligns the test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_worker_failure.py -v`
Expected: FAIL — the failure path currently lets the exception propagate WITHOUT setting `ocr_status="done"` (so the overdue gate would be the only recovery), and `enqueue` is called with no `retry` kwarg.

- [ ] **Step 3: Add failure reflection to `run_detections_ocr_rq`**

In `webapp/routers/bbox_ocr.py`, replace `run_detections_ocr_rq`:

```python
def run_detections_ocr_rq(job_id: int) -> dict:
    """RQ entry-point (runs on cpu-worker). Loads the job, computes tags, caches.

    On failure, persist ocr_status="done" before re-raising so the dashboard gate
    releases immediately (graceful degradation — detections just lack OCR tags)
    rather than trapping the card at "Preparing". Re-raising preserves RQ failure
    observability (the RQ job still records as failed, and RQ retries once).
    """
    db = SessionLocal()
    try:
        job = db.query(models.Job).filter(models.Job.id == job_id).first()
        if not job:
            logger.warning("OCR job %s no longer exists — skipping", job_id)
            return {"detections": [], "ocr_run": False, "ocr_status": "empty"}
        try:
            result = compute_tagged_detections(job)
        except Exception as e:
            logger.warning("OCR job %s failed (%s) — releasing gate to done", job_id, e)
            job.ocr_status = "done"
            db.commit()
            raise
        # Mark OCR done so the dashboard can show "Done" status
        job.ocr_status = "done"
        db.commit()
        return result
    finally:
        db.close()
```

> Subtlety: RQ retries re-invoke this function for the retry attempt. On the FINAL failing attempt RQ has exhausted retries, but our handler runs on *every* attempt's exception — that is fine: it idempotently sets `ocr_status="done"` and re-raises, so an intermediate retry that later succeeds simply overwrites `done`→`done` (the success path also sets `done`). No special "is this the last attempt?" logic needed.

- [ ] **Step 4: Add `Retry(max=1)` to the enqueue**

In `webapp/routers/bbox_ocr.py`, in `_enqueue_detections_ocr`, update the local rq imports and the `q.enqueue(...)` call. Current import line:

```python
        from rq.job import Job as RQJob
        from rq.exceptions import NoSuchJobError
```

Add `Retry`:

```python
        from rq.job import Job as RQJob
        from rq.exceptions import NoSuchJobError
        from rq import Retry
```

Current enqueue:

```python
        q.enqueue(
            "webapp.routers.bbox_ocr.run_detections_ocr_rq",
            job_id,
            job_id=rq_id,
            job_timeout=900,
            result_ttl=300,
        )
```

Replace with:

```python
        q.enqueue(
            "webapp.routers.bbox_ocr.run_detections_ocr_rq",
            job_id,
            job_id=rq_id,
            job_timeout=900,
            result_ttl=300,
            retry=Retry(max=1),  # absorb a transient worker-kill (deploy) mid-run
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_worker_failure.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/routers/bbox_ocr.py tests/unit/test_ocr_worker_failure.py
git commit -m "feat(ocr-gate): worker releases gate on failure + one RQ retry"
```

---

### Task 6: Startup reconcile sweep persists the released state

**Files:**
- Modify: `webapp/ocr_gate.py` (add `sweep_stale_ocr(db, now=None) -> int`)
- Modify: `webapp/main.py` (add `_reconcile_stale_ocr()`, call under `_IS_STARTUP_LEADER`)
- Test: `tests/unit/test_sweep_stale_ocr.py`

**Interfaces:**
- Consumes: `OCR_STALE_AFTER` (Task 1), `Job.ocr_enqueued_at` (Task 2).
- Produces: `sweep_stale_ocr(db, now=None) -> int` (count flipped); `main._reconcile_stale_ocr()`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sweep_stale_ocr.py`:

```python
"""sweep_stale_ocr persists ocr_status done for jobs stuck pending past the
timeout (or with no enqueue timestamp), and leaves everything else alone."""
from datetime import timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp.database import Base
from webapp import models
from webapp.ocr_gate import sweep_stale_ocr, OCR_STALE_AFTER
from webapp.datetime_utils import utcnow


def _mem_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _job(session, **kw):
    base = dict(user_id=1, original_filename="x.pdf", stored_filename="x.pdf")
    base.update(kw)
    j = models.Job(**base)
    session.add(j)
    session.commit()
    return j.id


def test_sweep_flips_overdue_and_null_only():
    session, engine = _mem_session()
    try:
        now = utcnow()
        overdue = _job(session, status="done", ocr_status="pending",
                       ocr_enqueued_at=now - OCR_STALE_AFTER - timedelta(minutes=5))
        null_ts = _job(session, status="done", ocr_status="pending",
                       ocr_enqueued_at=None)
        recent = _job(session, status="done", ocr_status="pending",
                      ocr_enqueued_at=now - timedelta(minutes=3))
        already = _job(session, status="done", ocr_status="done")
        processing = _job(session, status="processing", ocr_status="pending",
                          ocr_enqueued_at=now - timedelta(hours=2))

        count = sweep_stale_ocr(session, now=now)
        assert count == 2  # overdue + null_ts

        session.expire_all()
        g = lambda i: session.query(models.Job).get(i).ocr_status
        assert g(overdue) == "done"
        assert g(null_ts) == "done"
        assert g(recent) == "pending"      # still legitimately working
        assert g(already) == "done"
        assert g(processing) == "pending"  # extraction not even done — untouched
    finally:
        session.close()
        engine.dispose()


def test_sweep_returns_zero_when_nothing_stale():
    session, engine = _mem_session()
    try:
        _job(session, status="done", ocr_status="done")
        _job(session, status="done", ocr_status="pending",
             ocr_enqueued_at=utcnow() - timedelta(minutes=1))
        assert sweep_stale_ocr(session) == 0
    finally:
        session.close()
        engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_sweep_stale_ocr.py -v`
Expected: FAIL — `ImportError: cannot import name 'sweep_stale_ocr'`.

- [ ] **Step 3: Add `sweep_stale_ocr` to `webapp/ocr_gate.py`**

Append to `webapp/ocr_gate.py`:

```python
def sweep_stale_ocr(db, now: Optional[datetime] = None) -> int:
    """Persist the released state for jobs stuck pending past the timeout.

    Flips ocr_status pending → done for every job whose extraction is done but
    whose OCR has been pending past OCR_STALE_AFTER (or has no enqueue timestamp —
    legacy / pre-change pendings). Runs OUTSIDE any request path (startup leader),
    so the DB write here is safe. Returns the number flipped.
    """
    from webapp import models  # local import — avoid an import cycle at load time

    cutoff = (_as_utc(now) or _utcnow()) - OCR_STALE_AFTER
    candidates = (
        db.query(models.Job)
        .filter(models.Job.status == "done", models.Job.ocr_status == "pending")
        .all()
    )
    swept = 0
    for job in candidates:
        enq = _as_utc(job.ocr_enqueued_at)
        if enq is None or enq < cutoff:
            job.ocr_status = "done"
            swept += 1
    if swept:
        db.commit()
    return swept
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_sweep_stale_ocr.py -v`
Expected: PASS.

- [ ] **Step 5: Wire the sweep into startup**

In `webapp/main.py`, add a function next to the other one-shot startup helpers (e.g. after `_reconcile_ls_webhooks`):

```python
def _reconcile_stale_ocr() -> None:
    """Heal jobs trapped at "Preparing": flip OCR pending → done for any job
    stuck past the stale timeout (resilient-ocr-gate). Idempotent; failures are
    swallowed so a DB blip can't block boot."""
    try:
        from webapp.ocr_gate import sweep_stale_ocr
        db = SessionLocal()
        try:
            n = sweep_stale_ocr(db)
            if n:
                print(f"[startup] Released {n} stale-OCR job(s) to done")
        finally:
            db.close()
    except Exception as e:
        print(f"[startup] stale-OCR reconcile skipped: {e!r}")
```

Then add the call inside the existing `if _IS_STARTUP_LEADER:` block (after `_reconcile_ls_webhooks()`):

```python
if _IS_STARTUP_LEADER:
    _reset_stale_jobs()
    _ensure_super_admin()
    _reconcile_ls_webhooks()
    _reconcile_stale_ocr()
    # Initialize Neo4j agent memory schema (idempotent — creates index +
    # constraint if they don't yet exist; no-op when Neo4j is disabled).
    _init_agent_memory()
```

- [ ] **Step 6: Verify the full suite is green (no regressions)**

Run: `SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_hex(32))") python3 -m pytest tests/unit/test_ocr_gate.py tests/unit/test_ocr_enqueued_at_column.py tests/unit/test_ocr_enqueue_stamps_timestamp.py tests/unit/test_api_v1.py tests/unit/test_ocr_worker_failure.py tests/unit/test_sweep_stale_ocr.py tests/unit/test_detections_tagged_bg.py -v`
Expected: PASS (the OCR-gate suite + the existing detections-tagged + api_v1 suites all green).

- [ ] **Step 7: Commit**

```bash
git add webapp/ocr_gate.py webapp/main.py tests/unit/test_sweep_stale_ocr.py
git commit -m "feat(ocr-gate): startup sweep persists released state for stuck-pending jobs"
```

---

## Post-implementation (handled outside these tasks)

- FEATURES.md entry (new number) describing the three-layer resilient gate + the `ocr_enqueued_at` column + the 20-min `OCR_STALE_AFTER`.
- Deploy to dev (branch off `dev` → PR → 2-approval); the additive nullable-column migration is deploy-safe. First startup after deploy sweeps any pre-existing NULL/overdue pendings.
- Dev verification: confirm no `status=done AND ocr_status=pending AND (ocr_enqueued_at IS NULL OR ocr_enqueued_at < now-20m)` rows remain, and that a freshly-stuck case (e.g. simulate by setting a pending with an old timestamp) shows "Done" on the dashboard.
