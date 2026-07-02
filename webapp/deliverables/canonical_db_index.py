"""Dual-write index of canonical entities into the `canonical_entities` DB
table (FEATURES #34 — DB-backed cross-job queries).

`pipeline_emitter.write_canonical_for_job()` stays a pure function (no DB,
no network — see its docstring). The dual-write composes the two:

    canonical = write_canonical_for_job(job_dir=..., job_id=...)
    sync_canonical_to_db(canonical, db)  # idempotent upsert

The DB row mirrors `CanonicalEntity` 1-for-1 (entity_class, sub_class, tag,
pid_number, sheet_number, bbox, fields, vendor_match), plus the canonical
schema version so cross-job queries can filter incompatible shapes.

**Source of truth remains the on-disk canonical.json.** This index is a
read-cache for queries — never the edit target. User edits live in
`entity_overrides` and are merged at read time by the deliverables API.

Idempotency: unique on (job_id, entity_id). Re-emit overwrites the matching
row instead of duplicating, so the function is safe to call N times.
"""
from __future__ import annotations

from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from webapp import models
from webapp.deliverables.canonical import JobCanonical


def sync_canonical_to_db(canonical: JobCanonical, db: Session) -> Tuple[int, int]:
    """Upsert every entity from `canonical` into `canonical_entities`.

    Returns (inserted, updated). Stale rows (entities that existed in a
    prior emit but not in this one) are deleted — re-emit truth wins.
    """
    job_id = canonical.job_id
    existing = {
        row.entity_id: row
        for row in db.query(models.CanonicalEntityRow).filter(
            models.CanonicalEntityRow.job_id == job_id
        )
    }
    inserted = updated = 0
    seen: set[str] = set()
    for ent in canonical.entities:
        eid = str(ent.entity_id)
        seen.add(eid)
        payload = {
            "entity_class": ent.entity_class,
            "sub_class": ent.sub_class,
            "tag": ent.tag,
            "pid_number": ent.pid_number,
            "sheet_number": ent.sheet_number,
            "bbox": list(ent.bbox),
            "fields": ent.fields,
            "vendor_match": ent.vendor_match.model_dump(mode="json") if ent.vendor_match else None,
            "canonical_schema_version": canonical.canonical_schema_version,
        }
        existing_row = existing.get(eid)
        if existing_row is None:
            db.add(
                models.CanonicalEntityRow(
                    job_id=job_id,
                    entity_id=eid,
                    **payload,
                )
            )
            inserted += 1
        else:
            for k, v in payload.items():
                setattr(existing_row, k, v)
            updated += 1

    # Drop entities that no longer exist in the latest canonical.
    stale = [eid for eid in existing if eid not in seen]
    if stale:
        db.query(models.CanonicalEntityRow).filter(
            models.CanonicalEntityRow.job_id == job_id,
            models.CanonicalEntityRow.entity_id.in_(stale),
        ).delete(synchronize_session=False)

    db.commit()
    return inserted, updated
