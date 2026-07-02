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
