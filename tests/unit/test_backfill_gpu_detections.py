"""Unit tests for the gpu_detections backfill selection logic.

The inference itself (run_yolo_inference) needs the ONNX model + tiles and is
exercised on a real env; here we lock the *selection* predicate — which jobs are
considered to need a backfill — since that's the part that decides what gets
touched.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

backfill = pytest.importorskip("webapp.scripts.backfill_gpu_detections")

from webapp import models  # noqa: E402
from webapp.database import Base  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def user(db_session):
    u = models.User(username="bf_tester", password_hash="x", is_active=True)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def test_is_empty_detections():
    f = backfill._is_empty_detections
    assert f(None) is True
    assert f("") is True
    assert f("[]") is True
    assert f([]) is True
    assert f("not json") is True          # unparsable → treat as empty
    assert f('[{"bbox": [1, 2, 3, 4]}]') is False
    assert f([{"bbox": [1, 2, 3, 4]}]) is False


def test_jobs_needing_backfill_selects_only_empty(db_session, user):
    from webapp import models

    def mk(gpu, status="done", path="/x/valve_list.csv"):
        j = models.Job(
            user_id=user.id, pid_no="P", status=status,
            original_filename="x.pdf", stored_filename="y.pdf",
            output_csv_path=path, gpu_detections=gpu,
        )
        db_session.add(j)
        db_session.commit()
        return j

    empty1 = mk(None)
    empty2 = mk("[]")
    populated = mk('[{"bbox": [1, 2, 3, 4], "label": "valve_bv"}]')
    not_done = mk(None, status="processing")
    no_path = mk(None, path=None)

    ids = [j.id for j in backfill.jobs_needing_backfill(db_session)]
    assert empty1.id in ids
    assert empty2.id in ids
    assert populated.id not in ids      # already has detections
    assert not_done.id not in ids       # only 'done' jobs
    assert no_path.id not in ids        # needs an output path to find tiles


def test_jobs_needing_backfill_single_job_filter(db_session, user):
    from webapp import models

    j = models.Job(
        user_id=user.id, pid_no="P", status="done",
        original_filename="x.pdf", stored_filename="y.pdf",
        output_csv_path="/x/valve_list.csv", gpu_detections=None,
    )
    db_session.add(j)
    db_session.commit()
    ids = [x.id for x in backfill.jobs_needing_backfill(db_session, job_id=j.id)]
    assert ids == [j.id]
