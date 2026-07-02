# tests/unit/test_graph_orphan_dedup_merge.py
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from webapp.database import Base
from webapp import models
from webapp.routers.graph import get_job_graph


@pytest.fixture()
def db_session(tmp_path):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close(); eng.dispose()


def _super_admin(db):
    u = models.User(username="sa", password_hash="x", credits_remaining=9, is_active=True, role="super_admin")
    db.add(u); db.commit(); db.refresh(u); return u


def test_adopted_orphan_is_deduped_in_merge(db_session, tmp_path):
    user = _super_admin(db_session)
    jobdir = tmp_path / "job"; jobdir.mkdir()
    (jobdir / "output.csv").write_text("x")
    # canonical_graph.json with one orphan auto node (no entity_id) + an edge to it
    (jobdir / "canonical_graph.json").write_text(json.dumps({
        "nodes": [{"id": "n_1", "entity_id": None, "bbox": [0, 0, 10, 10], "class": "valve_bv"}],
        "edges": [{"id": "e1", "source": "n_1", "target": "n_1"}],
        "page_width": 100, "page_height": 100,
    }))
    job = models.Job(user_id=user.id, status="done", original_filename="p.pdf",
                     stored_filename="p.pdf", output_csv_path=str(jobdir / "output.csv"))
    db_session.add(job); db_session.commit()
    # adopted annotation overlapping the orphan
    ann = models.UserAnnotation(job_id=job.id, entity_id="e-x", user_id=user.id, source="user",
                                status="user_confirmed", entity_class="valve", sub_class="BV",
                                bbox=[1, 1, 11, 11], sheet_number=1, tag="62-BV-1")
    db_session.add(ann); db_session.commit()

    g = get_job_graph(job.id, db=db_session, current_user=user)
    ids = [n["id"] for n in g["nodes"]]
    assert "n_1" not in ids                      # orphan superseded → dropped
    assert any(n.get("entity_id") == "e-x" for n in g["nodes"])
    assert all(e.get("source") != "n_1" and e.get("target") != "n_1" for e in g["edges"])
