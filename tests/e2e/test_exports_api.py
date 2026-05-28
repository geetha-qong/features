"""E2E tests for POST /api/v1/jobs/{id}/export/{deliverable}/{format}.

Uses FastAPI TestClient with an in-memory SQLite DB (dependency override pattern)
so no running Postgres is needed.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp.main import app
from webapp.database import Base, get_db
from webapp.models import Job


@pytest.fixture(scope="function")
def test_db():
    """In-memory SQLite DB, schema created fresh per test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(test_db):
    """TestClient with get_db overridden to use the in-memory test DB."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def job_with_canonical(tmp_path, test_db, client):
    """Create a Job row + write canonical.json into its output dir."""
    job_dir = tmp_path / "9999"
    job_dir.mkdir()
    csv_path = job_dir / "valve_list.csv"
    csv_path.write_text("")

    canonical = {
        "job_id": 9999,
        "canonical_schema_version": "1.0.0",
        "customer_template_slug": "default",
        "entities": [
            {
                "entity_id": "11111111-1111-1111-1111-111111111111",
                "entity_class": "valve",
                "sub_class": "gate_valve",
                "tag": "GV-001",
                "pid_number": "P-001",
                "sheet_number": 1,
                "bbox": [0, 0, 10, 10],
                "fields": {
                    "size": "4in",
                    "service": "Process Water",
                    "material": "CS",
                },
            }
        ],
    }
    (job_dir / "canonical.json").write_text(json.dumps(canonical))

    job = Job(
        id=9999,
        user_id=1,
        original_filename="test.pdf",
        stored_filename="test.pdf",
        output_csv_path=str(csv_path),
    )
    test_db.add(job)
    test_db.commit()
    yield job


def test_export_valve_list_csv(client, job_with_canonical):
    response = client.post(
        f"/api/v1/jobs/{job_with_canonical.id}/export/valve_list/csv"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content.decode("utf-8")
    # Default template maps pid_number -> "P&ID No" and fields.size -> "Size"
    assert "P-001" in body   # pid_number maps to "P&ID No" column
    assert "4in" in body     # fields.size maps to "Size" column


def test_export_valve_list_xlsx(client, job_with_canonical):
    response = client.post(
        f"/api/v1/jobs/{job_with_canonical.id}/export/valve_list/xlsx"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert response.content[:2] == b"PK"  # ZIP magic — xlsx is a ZIP


def test_export_unknown_deliverable_returns_400(client, job_with_canonical):
    response = client.post(
        f"/api/v1/jobs/{job_with_canonical.id}/export/unknown/csv"
    )
    assert response.status_code == 400


def test_export_unknown_job_returns_404(client):
    response = client.post("/api/v1/jobs/999999/export/valve_list/csv")
    assert response.status_code == 404


def test_export_job_without_canonical_returns_404(client, test_db, tmp_path):
    """Job exists and has output_csv_path but canonical.json is absent."""
    job_dir = tmp_path / "no_canonical"
    job_dir.mkdir()
    csv_path = job_dir / "valve_list.csv"
    csv_path.write_text("")

    job = Job(
        id=9998,
        user_id=1,
        original_filename="test.pdf",
        stored_filename="test.pdf",
        output_csv_path=str(csv_path),
    )
    test_db.add(job)
    test_db.commit()

    response = client.post(f"/api/v1/jobs/{job.id}/export/valve_list/csv")
    assert response.status_code == 404
