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
