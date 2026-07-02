"""Tests for webapp/taxonomy_db.py — taxonomy.json -> label_taxonomy DB sync.

Mirrors the canonical_db_index contract: file is source of truth, the DB table
is an idempotent read-index. We assert row count == number of taxonomy.json
classes, spot-check a couple of specific rows, and confirm a second sync is a
no-op (same count, no duplicates).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from webapp import models
from webapp.database import Base
from webapp.taxonomy import load_taxonomy
from webapp.taxonomy_db import sync_taxonomy_to_db


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_sync_populates_all_classes(db_session):
    n_classes = len(load_taxonomy()["classes"])

    inserted, updated = sync_taxonomy_to_db(db_session)

    assert inserted == n_classes
    assert updated == 0
    assert db_session.query(models.LabelTaxonomy).count() == n_classes


def test_sync_specific_rows(db_session):
    sync_taxonomy_to_db(db_session)

    bv = (
        db_session.query(models.LabelTaxonomy)
        .filter_by(entity_class="valve", sub_class="BV")
        .one()
    )
    assert bv.color == "#86D8C4"
    assert bv.display_name == "Ball Valve"
    assert bv.glyph_kind == "valve_bv"
    assert bv.yolo_label == "valve_bv"

    pt = (
        db_session.query(models.LabelTaxonomy)
        .filter_by(entity_class="instrument", sub_class="PT")
        .one()
    )
    assert pt.color == "#C5BCEC"
    assert pt.display_name == "Pressure Tx"
    assert pt.yolo_label is None  # OCR-only canonical class


def test_structural_classes_not_collapsed(db_session):
    """Arrow/connector classes must each get their own DB row.
    They are now classified as entity_class='annotation' with distinct sub_class,
    so each row is unique — no collapsing can occur."""
    sync_taxonomy_to_db(db_session)

    structural = (
        db_session.query(models.LabelTaxonomy)
        .filter_by(entity_class="annotation")
        .all()
    )
    labels = {r.yolo_label for r in structural}
    assert {"arrow_up", "arrow_down", "connector_in", "connector_out"} <= labels


def test_sync_is_idempotent(db_session):
    n_classes = len(load_taxonomy()["classes"])

    sync_taxonomy_to_db(db_session)
    inserted2, updated2 = sync_taxonomy_to_db(db_session)

    assert inserted2 == 0
    assert updated2 == n_classes
    assert db_session.query(models.LabelTaxonomy).count() == n_classes
