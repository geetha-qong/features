"""Admin JSON API — taxonomy + label-triage  (/api/v1/admin/*)

Phase 4b of the unified-taxonomy track. Cookie-auth only, super_admin role
required (uses ``webapp.auth.require_super_admin``, same dependency as
``api_v1_admin.py``).

Mounted under the same ``/api/v1/admin`` prefix as ``api_v1_admin.py`` but on a
separate router (distinct path segments — no shadow risk; see the
duplicate-route-shadow note in CLAUDE.md). Routes here: ``GET /taxonomy``,
``GET /label-triage``, ``POST /label-triage/{id}/classify``.

Contract (mirrors FEATURES #34 file-first design):
  - **Source of truth is on-disk ``webapp/taxonomy.json``.** On approve we
    append the new class to that file (load → append → write back with stable
    2-space JSON), invalidate the in-process cache, then upsert the DB
    read-index via ``webapp.taxonomy_db.sync_taxonomy_to_db``.
  - ``label_triage`` is the staging/audit surface; classify decisions set
    ``status`` + ``decided_by_user_id`` + ``decided_at``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp import models
from webapp import taxonomy as taxonomy_module
from webapp.auth import require_super_admin
from webapp.database import get_db
from webapp.taxonomy import load_taxonomy
from webapp.taxonomy_db import sync_taxonomy_to_db

router = APIRouter(prefix="/api/v1/admin", tags=["taxonomy_admin"])

_VALID_ENTITY_CLASSES = {"valve", "instrument", "equipment"}
_VALID_TRIAGE_STATUS = {"pending", "approved", "ignored", "rejected"}
_VALID_ACTIONS = {"approve", "ignore", "reject"}


def _serialize_triage(t: models.LabelTriage) -> dict:
    from webapp.datetime_utils import utc_iso

    return {
        "id": t.id,
        "label_value": t.label_value,
        "source": t.source,
        "discovered_at": utc_iso(t.discovered_at) if t.discovered_at else None,
        "status": t.status,
        "assigned_entity_class": t.assigned_entity_class,
        "assigned_sub_class": t.assigned_sub_class,
        "assigned_display_name": t.assigned_display_name,
        "assigned_color": t.assigned_color,
        "assigned_glyph_kind": t.assigned_glyph_kind,
        "decided_by_user_id": t.decided_by_user_id,
        "decided_at": utc_iso(t.decided_at) if t.decided_at else None,
        "notes": t.notes,
    }


# ── Taxonomy (read-only) ─────────────────────────────────────────────────────


@router.get("/taxonomy")
def get_taxonomy(
    current_user: models.User = Depends(require_super_admin),
):
    """Full taxonomy dict (classes + yolo_routing) from the on-disk source of
    truth. Read-only — edits flow through the triage classify path."""
    return load_taxonomy()


# ── Label triage ─────────────────────────────────────────────────────────────


@router.get("/label-triage")
def list_label_triage(
    status: str = "pending",
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """List triage rows, optionally filtered by status. ``status=all`` returns
    every row."""
    q = db.query(models.LabelTriage).order_by(models.LabelTriage.discovered_at.desc())
    if status and status != "all":
        if status not in _VALID_TRIAGE_STATUS:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        q = q.filter(models.LabelTriage.status == status)
    items = q.all()
    return {"items": [_serialize_triage(t) for t in items], "status": status}


class ClassifyBody(BaseModel):
    action: str
    entity_class: Optional[str] = None
    sub_class: Optional[str] = None
    display_name: Optional[str] = None
    color: Optional[str] = None
    glyph_kind: Optional[str] = None


def _append_class_to_taxonomy(new_class: dict) -> None:
    """Append `new_class` to taxonomy.json on disk, then invalidate the cache.

    Reads the current file (not the cache — we want the on-disk truth), appends
    with a stable next ``order``, writes back with 2-space indentation, then
    clears ``webapp.taxonomy`` cache so subsequent ``load_taxonomy()`` reflects
    the change.
    """
    path = taxonomy_module._TAXONOMY_PATH
    with path.open() as fh:
        data = json.load(fh)
    classes = data.setdefault("classes", [])
    max_order = max((c.get("order", 0) for c in classes), default=-1)
    new_class.setdefault("order", max_order + 1)
    classes.append(new_class)
    with path.open("w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    # Invalidate the in-process cache so the next load_taxonomy() re-reads.
    with taxonomy_module._lock:
        taxonomy_module._cache = None


@router.post("/label-triage/{triage_id}/classify")
def classify_label_triage(
    triage_id: int,
    body: ClassifyBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Triage decision for a label.

    ``action=approve`` → validate entity_class, append the class to
    taxonomy.json (source of truth), upsert the DB read-index, record the
    assignment + status=approved on the triage row.

    ``action=ignore`` / ``action=reject`` → just set status + decided_* fields.
    """
    if body.action not in _VALID_ACTIONS:
        raise HTTPException(status_code=400, detail="Invalid action")

    row = db.query(models.LabelTriage).filter(models.LabelTriage.id == triage_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Triage row not found")

    now = datetime.now(timezone.utc)

    if body.action == "approve":
        if body.entity_class not in _VALID_ENTITY_CLASSES:
            raise HTTPException(
                status_code=400,
                detail="entity_class must be one of valve, instrument, equipment",
            )
        display_name = body.display_name or row.label_value
        color = body.color or "#9498AE"
        glyph_kind = body.glyph_kind or "valve_gen"

        new_class = {
            "yolo_label": None,  # triage-approved classes are OCR-only (no ONNX channel)
            "entity_class": body.entity_class,
            "sub_class": body.sub_class,
            "display_name": display_name,
            "color": color,
            "glyph_kind": glyph_kind,
        }
        _append_class_to_taxonomy(new_class)
        # Refresh the DB read-index from the now-updated taxonomy.json.
        sync_taxonomy_to_db(db)

        row.status = "approved"
        row.assigned_entity_class = body.entity_class
        row.assigned_sub_class = body.sub_class
        row.assigned_display_name = display_name
        row.assigned_color = color
        row.assigned_glyph_kind = glyph_kind
    else:
        row.status = "ignored" if body.action == "ignore" else "rejected"

    row.decided_by_user_id = current_user.id
    row.decided_at = now
    db.commit()
    db.refresh(row)
    return _serialize_triage(row)
