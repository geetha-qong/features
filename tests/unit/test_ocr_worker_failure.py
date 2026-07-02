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

    monkeypatch.setattr("webapp.queue.get_cpu_queue", lambda: _FakeQueue())
    monkeypatch.setattr("rq.job.Job.fetch",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(NoSuchJobError("none"))))
    # Avoid touching a real DB in the pending-set block.
    monkeypatch.setattr(bbox_ocr, "SessionLocal", lambda: (_ for _ in ()).throw(Exception("skip")))

    bbox_ocr._enqueue_detections_ocr(123)

    retry = captured["kwargs"].get("retry")
    assert isinstance(retry, Retry)
    assert retry.max == 1
