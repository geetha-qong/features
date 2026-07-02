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
        # get_cpu_queue is a function-local import inside _enqueue_detections_ocr,
        # so we patch at the module level: webapp.queue.get_cpu_queue
        monkeypatch.setattr("webapp.queue.get_cpu_queue", lambda: fake_q)

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
