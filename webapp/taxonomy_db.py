"""Dual-write index of the symbol taxonomy into the `label_taxonomy` DB table.

Mirrors the `canonical_db_index` contract (FEATURES #34): the on-disk
`webapp/taxonomy.json` (read via `webapp/taxonomy.py`) is the **source of
truth**; this module upserts each class into `label_taxonomy` so cross-cutting
SQL/admin surfaces can query the class list without parsing JSON.

`sync_taxonomy_to_db(db)` is idempotent — keyed on `(entity_class, sub_class)`
for entity-bearing classes, and on `yolo_label` for the structural classes
(arrows / connectors) whose `(entity_class, sub_class)` is `(None, None)` and
would otherwise collide. Re-running updates existing rows in place instead of
duplicating, so it's safe to call N times (e.g. on every startup).

Called once from `webapp/database.py:run_migrations()` after
`Base.metadata.create_all`, wrapped non-fatally (like the billing-plan seed).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from webapp import models
from webapp.taxonomy import load_taxonomy


def _key(cls: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Stable identity for a taxonomy class.

    Entity-bearing classes are identified by (entity_class, sub_class). The
    structural classes (arrows/connectors) carry (None, None) — which the
    UNIQUE constraint treats as distinct rows — so fall back to yolo_label to
    keep the upsert from collapsing them all into one row.
    """
    ec = cls.get("entity_class")
    sub = cls.get("sub_class")
    if ec is None and sub is None:
        return (None, None, cls.get("yolo_label"))
    return (ec, sub, None)


def sync_taxonomy_to_db(db: Session) -> Tuple[int, int]:
    """Upsert every taxonomy.json class into `label_taxonomy`.

    Returns (inserted, updated). Idempotent — re-run yields the same row set.
    """
    classes = load_taxonomy()["classes"]

    existing_rows = db.query(models.LabelTaxonomy).all()
    existing: Dict[Tuple[Optional[str], Optional[str], Optional[str]], models.LabelTaxonomy] = {}
    for row in existing_rows:
        ec = row.entity_class or None
        sub = row.sub_class
        if ec is None and sub is None:
            existing[(None, None, row.yolo_label)] = row
        else:
            existing[(ec, sub, None)] = row

    inserted = updated = 0
    for cls in classes:
        payload = {
            "entity_class": cls.get("entity_class"),
            "sub_class": cls.get("sub_class"),
            "display_name": cls["display_name"],
            "yolo_label": cls.get("yolo_label"),
            "color": cls["color"],
            "glyph_kind": cls["glyph_kind"],
            "isa_code": cls.get("isa_code"),
            "order": cls.get("order", 0),
            "active": cls.get("active", True),
        }
        key = _key(cls)
        row = existing.get(key)
        if row is None:
            db.add(models.LabelTaxonomy(**payload))
            inserted += 1
        else:
            for k, v in payload.items():
                setattr(row, k, v)
            updated += 1

    db.commit()
    return inserted, updated
