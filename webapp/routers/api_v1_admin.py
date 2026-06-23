"""Admin JSON API — /api/v1/admin/*

Cookie-auth only, super_admin role required (uses webapp.auth.require_super_admin).
Mirrors the legacy Jinja /admin/* form-POST routes 1:1, but returns JSON.

Phase 3 — Admin UI ported to React. Both the legacy Jinja and these JSON
endpoints coexist until Phase 3.11 deletes the Jinja templates + routes.
Until that point, the React UI uses these endpoints and the legacy Jinja
routes continue to serve as fallback (data continuity for any bookmarked URL).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from webapp.datetime_utils import utc_iso
from webapp.model_version import current_model_trained_at, current_version
from webapp.taxonomy import yolo_to_canonical

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from webapp import credits as credits_module
from webapp import label_studio_client as ls
from webapp import models
from webapp.auth import hash_password, require_super_admin
from webapp.config import JOB_OUTPUT_DIR, MIN_PASSWORD_LENGTH, get_job_dir
from webapp.database import get_db
from webapp.deliverables.template_loader import (
    TemplateLoader,
    TemplateNotFound,
    merged_template_dict,
)

router = APIRouter(prefix="/api/v1/admin", tags=["api_v1_admin"])

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
_VALID_ROLES = {"user", "annotator", "super_admin"}
_VALID_TIERS = {"trial", "starter", "pro", "enterprise"}
_VALID_FEEDBACK_STATUS = {"new", "in_progress", "resolved", "wontfix"}


# ── Serializers ────────────────────────────────────────────────────────────────


def _serialize_user(u: models.User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
        "is_active": bool(u.is_active),
        "credits_remaining": u.credits_remaining or 0,
        "tier": u.tier or "trial",
        "organization": u.organization,
        "created_at": utc_iso(u.created_at),
    }


def _serialize_txn(t: models.CreditTransaction, username: Optional[str]) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "username": username,
        "delta": t.delta,
        "balance_after": t.balance_after,
        "reason": t.reason,
        "job_id": t.job_id,
        "created_at": utc_iso(t.created_at),
    }


def _serialize_feedback(f: models.UserFeedback, username: Optional[str]) -> dict:
    return {
        "id": f.id,
        "user_id": f.user_id,
        "username": username,
        "category": f.category,
        "subject": f.subject,
        "message": f.message,
        "page_url": f.page_url,
        "status": f.status,
        "admin_notes": f.admin_notes,
        "created_at": utc_iso(f.created_at),
    }


def _serialize_plan(p: models.BillingPlan) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "credits": p.credits,
        "price_usd_cents": p.price_usd_cents,
        "is_active": bool(p.is_active),
        "stripe_price_id": p.stripe_price_id,
        "created_at": utc_iso(p.created_at),
    }


def _serialize_job_with_ls(job: models.Job, stats: dict) -> dict:
    return {
        "id": job.id,
        "pid_no": job.pid_no,
        "original_filename": job.original_filename,
        "status": job.status,
        "ls_project_id": job.ls_project_id,
        "ls_synced": bool(job.ls_synced),
        "valve_count": job.valve_count or 0,
        "created_at": utc_iso(job.created_at),
        "ls_stats": stats or {},
    }


# ── Users ──────────────────────────────────────────────────────────────────────


@router.get("/users")
def list_users(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    users = db.query(models.User).order_by(models.User.created_at).all()
    return {"users": [_serialize_user(u) for u in users]}


class CreateUserBody(BaseModel):
    username: str
    email: str = ""
    password: str
    role: str = "user"


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    username = body.username.strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="Username must be 3-32 chars, letters/digits/._- only.")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=400, detail=f"Username '{username}' already taken")

    role = body.role if body.role in _VALID_ROLES else "user"
    new_user = models.User(
        username=username,
        email=body.email or None,
        password_hash=hash_password(body.password),
        role=role,
        is_active=True,  # admin-created users are always active
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return _serialize_user(new_user)


class RoleBody(BaseModel):
    role: str


@router.post("/users/{user_id}/role")
def change_role(
    user_id: int,
    body: RoleBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role not in _VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    target.role = body.role
    db.commit()
    return _serialize_user(target)


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return _serialize_user(target)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    return _serialize_user(target)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(target)
    db.commit()


class GrantCreditsBody(BaseModel):
    amount: int = Field(..., gt=0, le=10000)


@router.post("/users/{user_id}/grant-credits")
def grant_credits(
    user_id: int,
    body: GrantCreditsBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    credits_module.grant(target, body.amount, reason="admin_grant", db=db, admin_id=current_user.id)
    db.refresh(target)
    return _serialize_user(target)


class TierBody(BaseModel):
    tier: str


@router.post("/users/{user_id}/change-tier")
def change_tier(
    user_id: int,
    body: TierBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if body.tier not in _VALID_TIERS:
        raise HTTPException(status_code=400, detail="Invalid tier")
    target.tier = body.tier
    db.commit()
    return _serialize_user(target)


# ── Dashboard ──────────────────────────────────────────────────────────────────


@router.get("/dashboard")
def dashboard_kpis(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    total_users = db.query(models.User).count()
    active_users = db.query(models.User).filter(models.User.is_active == True).count()  # noqa: E712
    pending_users = db.query(models.User).filter(models.User.is_active == False).count()  # noqa: E712
    total_jobs = db.query(models.Job).count()
    done_jobs = db.query(models.Job).filter(models.Job.status == "done").count()
    open_feedback = (
        db.query(models.UserFeedback).filter(models.UserFeedback.status == "new").count()
    )
    mtd_consumed = (
        db.query(func.sum(models.CreditTransaction.delta))
        .filter(models.CreditTransaction.delta < 0)
        .scalar()
        or 0
    )
    mtd_granted = (
        db.query(func.sum(models.CreditTransaction.delta))
        .filter(models.CreditTransaction.delta > 0)
        .scalar()
        or 0
    )
    recent = (
        db.query(models.CreditTransaction)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(10)
        .all()
    )
    users_map = {u.id: u.username for u in db.query(models.User).all()}
    return {
        "total_users": total_users,
        "active_users": active_users,
        "pending_users": pending_users,
        "total_jobs": total_jobs,
        "done_jobs": done_jobs,
        "open_feedback": open_feedback,
        "mtd_consumed": abs(mtd_consumed),
        "mtd_granted": mtd_granted,
        "recent_txns": [_serialize_txn(t, users_map.get(t.user_id)) for t in recent],
    }


# ── Credits ledger ─────────────────────────────────────────────────────────────


@router.get("/credits")
def list_credits(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
    limit: int = 200,
):
    txns = (
        db.query(models.CreditTransaction)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(min(limit, 1000))
        .all()
    )
    users_map = {u.id: u.username for u in db.query(models.User).all()}
    return {"transactions": [_serialize_txn(t, users_map.get(t.user_id)) for t in txns]}


# ── Feedback ───────────────────────────────────────────────────────────────────


@router.get("/feedback")
def list_feedback(
    status_filter: str = "new",
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.UserFeedback).order_by(models.UserFeedback.created_at.desc())
    if status_filter and status_filter != "all":
        if status_filter not in _VALID_FEEDBACK_STATUS:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        q = q.filter(models.UserFeedback.status == status_filter)
    items = q.limit(100).all()
    users_map = {u.id: u.username for u in db.query(models.User).all()}
    open_count = (
        db.query(models.UserFeedback).filter(models.UserFeedback.status == "new").count()
    )
    return {
        "items": [_serialize_feedback(f, users_map.get(f.user_id)) for f in items],
        "status_filter": status_filter,
        "open_count": open_count,
    }


class FeedbackUpdateBody(BaseModel):
    status: str
    admin_notes: str = ""


@router.post("/feedback/{item_id}/update")
def update_feedback(
    item_id: int,
    body: FeedbackUpdateBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    item = db.query(models.UserFeedback).filter(models.UserFeedback.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if body.status in _VALID_FEEDBACK_STATUS:
        item.status = body.status
    item.admin_notes = (body.admin_notes or "").strip() or None
    db.commit()
    return _serialize_feedback(item, None)


# ── Billing plans ──────────────────────────────────────────────────────────────


@router.get("/plans")
def list_plans(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plans = db.query(models.BillingPlan).order_by(models.BillingPlan.price_usd_cents).all()
    return {"plans": [_serialize_plan(p) for p in plans]}


class CreatePlanBody(BaseModel):
    name: str
    credits: int = Field(..., gt=0)
    price_usd_cents: int = Field(..., ge=0)


@router.post("/plans", status_code=201)
def create_plan(
    body: CreatePlanBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plan = models.BillingPlan(
        name=body.name.strip(),
        credits=body.credits,
        price_usd_cents=body.price_usd_cents,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.post("/plans/{plan_id}/toggle")
def toggle_plan(
    plan_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plan = db.query(models.BillingPlan).filter(models.BillingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.is_active = not plan.is_active
    db.commit()
    return _serialize_plan(plan)


# ── Label Studio ───────────────────────────────────────────────────────────────


@router.get("/label-studio")
def list_label_studio_jobs(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(models.Job)
        .filter(models.Job.status == "done")
        .order_by(models.Job.created_at.desc())
        .all()
    )
    items = []
    for job in jobs:
        stats = ls.get_project_stats(job.ls_project_id) if job.ls_project_id else {}
        items.append(_serialize_job_with_ls(job, stats))
    return {
        "jobs": items,
        "ls_url": ls.LS_EXTERNAL_URL,
        "ls_configured": ls.is_configured(),
    }


@router.post("/label-studio/sync-labels")
def sync_label_configs(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if not ls.is_configured():
        raise HTTPException(status_code=400, detail="LS_API_KEY not configured")
    result = ls.sync_all_label_configs(source_project_id=1)
    return {"updated": result.get("updated", []), "count": len(result.get("updated", []))}


# ── Customer templates (D5: custom column labels) ─────────────────────────────


_VALID_DELIVERABLE_TYPES = {"valve_list", "instrument_index", "datasheet", "equipment_list"}
_template_loader = TemplateLoader()


def _build_template_response(slug: str, db: Session) -> dict:
    """Shared GET/PUT/DELETE serializer.

    Returns the merged template for `slug` plus the list of available slugs
    (filesystem-scan of `customer_templates/*.json`) so the UI can build its
    picker without a second round-trip.
    """
    try:
        merged = merged_template_dict(slug, db=db, loader=_template_loader, fallback=slug)
    except TemplateNotFound:
        raise HTTPException(status_code=404, detail=f"Customer template '{slug}' not found")

    # Re-shape per-deliverable columns to the API contract documented in the
    # spec: list of {key, label, hidden, order_in_template, is_overridden}.
    deliverables_out: dict = {}
    for d_type, d_cfg in (merged.get("deliverables") or {}).items():
        rows = []
        for col in d_cfg.get("columns", []):
            rows.append({
                "key": col.get("field"),
                "label": col.get("header"),
                "hidden": False,  # hidden cols were already dropped from the merge
                "order_in_template": col.get("order"),
                "is_overridden": bool(col.get("is_overridden", False)),
            })
        deliverables_out[d_type] = rows

    # Surface hidden columns separately so the UI can show + un-hide them.
    # We requery the override table for hidden rows since they're filtered
    # out of the merged dict above.
    hidden_by_dtype: dict = {}
    overrides = (
        db.query(models.CustomerTemplateOverride)
        .filter(models.CustomerTemplateOverride.customer_template_slug == slug)
        .filter(models.CustomerTemplateOverride.hidden == True)  # noqa: E712
        .all()
    )
    if overrides:
        # Need the original JSON to recover header/order for hidden columns.
        try:
            raw = _template_loader._load_raw(slug)
        except TemplateNotFound:
            raw = {}
        for d_type, d_cfg in (raw.get("deliverables") or {}).items():
            by_field = {c["field"]: c for c in d_cfg.get("columns", [])}
            for o in overrides:
                if o.deliverable_type != d_type:
                    continue
                col = by_field.get(o.column_key)
                if not col:
                    continue
                hidden_by_dtype.setdefault(d_type, []).append({
                    "key": col["field"],
                    "label": o.label_override or col["header"],
                    "hidden": True,
                    "order_in_template": o.column_order if o.column_order is not None else col.get("order"),
                    "is_overridden": True,
                })
    # Merge hidden cols back in at their stored position (sorted by order).
    for d_type, hidden_cols in hidden_by_dtype.items():
        merged_cols = deliverables_out.get(d_type, []) + hidden_cols
        merged_cols.sort(key=lambda c: c.get("order_in_template") or 1_000_000)
        deliverables_out[d_type] = merged_cols

    last_updated = (
        db.query(func.max(models.CustomerTemplateOverride.updated_at))
        .filter(models.CustomerTemplateOverride.customer_template_slug == slug)
        .scalar()
    )

    return {
        "slug": slug,
        "customer_name": merged.get("customer_name"),
        "available_slugs": _template_loader.available_slugs(),
        "deliverables": deliverables_out,
        "last_updated_at": utc_iso(last_updated) if last_updated else None,
    }


@router.get("/customer-templates/{slug}")
def get_customer_template(
    slug: str,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    return _build_template_response(slug, db)


class OverrideItem(BaseModel):
    deliverable_type: str
    column_key: str
    label_override: Optional[str] = None
    column_order: Optional[int] = None
    hidden: bool = False


class PutOverridesBody(BaseModel):
    overrides: list[OverrideItem]


@router.put("/customer-templates/{slug}")
def put_customer_template_overrides(
    slug: str,
    body: PutOverridesBody,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    # Validate slug exists on disk before touching the DB.
    try:
        _template_loader._load_raw(slug)
    except TemplateNotFound:
        raise HTTPException(status_code=404, detail=f"Customer template '{slug}' not found")

    for ov in body.overrides:
        if ov.deliverable_type not in _VALID_DELIVERABLE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid deliverable_type '{ov.deliverable_type}'",
            )

    # Delete-then-insert: simplest correct behavior across SQLite + Postgres
    # (avoid dialect-specific UPSERT). Scoped to this slug so other slugs are
    # untouched; per (deliverable_type, column_key) tuples in the payload.
    payload_keys = {(ov.deliverable_type, ov.column_key) for ov in body.overrides}
    if payload_keys:
        existing = (
            db.query(models.CustomerTemplateOverride)
            .filter(models.CustomerTemplateOverride.customer_template_slug == slug)
            .all()
        )
        for row in existing:
            if (row.deliverable_type, row.column_key) in payload_keys:
                db.delete(row)
        db.flush()

    for ov in body.overrides:
        # Skip no-op rows (no override anywhere) — keeps the table tidy.
        if ov.label_override is None and ov.column_order is None and not ov.hidden:
            continue
        db.add(models.CustomerTemplateOverride(
            customer_template_slug=slug,
            deliverable_type=ov.deliverable_type,
            column_key=ov.column_key,
            label_override=ov.label_override,
            column_order=ov.column_order,
            hidden=ov.hidden,
            updated_by=current_user.id,
        ))
    db.commit()

    return _build_template_response(slug, db)


@router.delete("/customer-templates/{slug}/overrides")
def reset_customer_template_overrides(
    slug: str,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        _template_loader._load_raw(slug)
    except TemplateNotFound:
        raise HTTPException(status_code=404, detail=f"Customer template '{slug}' not found")

    db.query(models.CustomerTemplateOverride).filter(
        models.CustomerTemplateOverride.customer_template_slug == slug
    ).delete()
    db.commit()
    return _build_template_response(slug, db)


@router.post("/label-studio/sync/{job_id}")
def sync_job_to_label_studio(
    job_id: int,
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not ls.is_configured():
        raise HTTPException(status_code=400, detail="LS_API_KEY not configured")

    job_dir = get_job_dir(job)
    tile_files = sorted((job_dir / "tmp").glob("tile_p*_r*_c*.png"))
    if not tile_files:
        raise HTTPException(status_code=400, detail="No tiles found for this job")

    base_url = str(request.base_url).rstrip("/")
    tile_urls = [f"{base_url}/jobs/{job_id}/tiles/{f.name}" for f in tile_files]

    project_id = job.ls_project_id or ls.get_or_create_project(job.pid_no or f"job-{job_id}")
    if not project_id:
        raise HTTPException(status_code=500, detail="Could not create Label Studio project")

    ls.delete_all_tasks(project_id)
    pushed = ls.push_tiles(project_id, tile_urls)
    job.ls_project_id = project_id
    job.ls_synced = pushed > 0
    db.commit()

    return {"job_id": job.id, "ls_project_id": project_id, "tiles_pushed": pushed}


# ─────────────────────────────────────────────────────────────────────────────
# Canonical entity index — cross-job query surface (FEATURES #34).
# Reads from the `canonical_entities` table populated by the dual-write in
# `pipeline_runner.py` + `webapp/scripts/index_canonical_to_db.py` backfill.
# Note: this is the *pipeline-emitted* state, NOT user-edited state.
# Apply entity_overrides via the deliverables API if you need "what the user
# sees right now".
# ─────────────────────────────────────────────────────────────────────────────


class CanonicalEntityRowResp(BaseModel):
    job_id: int
    entity_id: str
    entity_class: str
    sub_class: Optional[str] = None
    tag: Optional[str] = None
    pid_number: str
    sheet_number: int
    fields: dict = Field(default_factory=dict)
    updated_at: Optional[str] = None


class EntitySearchResp(BaseModel):
    total: int           # total rows matching the filter (pre-pagination)
    returned: int        # rows in this response
    offset: int
    limit: int
    rows: list[CanonicalEntityRowResp]


@router.get("/entities", response_model=EntitySearchResp)
def admin_search_canonical_entities(
    entity_class: Optional[str] = None,
    sub_class: Optional[str] = None,
    tag_contains: Optional[str] = None,
    job_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Search the cross-job canonical entity index.

    All filters AND together. Common queries:
      - `?entity_class=valve&sub_class=BV` → every ball valve across jobs
      - `?tag_contains=32047` → duplicate-tag audit
      - `?job_id=38` → single-job dump (mirrors what canonical.json holds)

    Hard limit cap = 500 rows per response to keep payloads bounded.
    """
    limit = max(1, min(500, limit))
    offset = max(0, offset)

    q = db.query(models.CanonicalEntityRow)
    if entity_class:
        q = q.filter(models.CanonicalEntityRow.entity_class == entity_class)
    if sub_class:
        q = q.filter(models.CanonicalEntityRow.sub_class == sub_class)
    if tag_contains:
        # Cheap LIKE — index covers prefix but a substring scan is the
        # right ergonomics for the "find tags containing 32047" use case.
        q = q.filter(models.CanonicalEntityRow.tag.ilike(f"%{tag_contains}%"))
    if job_id is not None:
        q = q.filter(models.CanonicalEntityRow.job_id == job_id)

    total = q.count()
    rows = (
        q.order_by(models.CanonicalEntityRow.job_id, models.CanonicalEntityRow.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return EntitySearchResp(
        total=total,
        returned=len(rows),
        offset=offset,
        limit=limit,
        rows=[
            CanonicalEntityRowResp(
                job_id=r.job_id,
                entity_id=r.entity_id,
                entity_class=r.entity_class,
                sub_class=r.sub_class,
                tag=r.tag,
                pid_number=r.pid_number,
                sheet_number=r.sheet_number,
                fields=r.fields or {},
                updated_at=utc_iso(r.updated_at) if r.updated_at else None,
            )
            for r in rows
        ],
    )


@router.get("/entities/aggregates")
def admin_canonical_entity_aggregates(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Quick top-level breakdowns for dashboards: total rows, per-class
    counts, top-10 sub_classes by count, top-10 jobs by valve count.
    Single round-trip — cheaper than four `?entity_class=X&count` calls.
    """
    Row = models.CanonicalEntityRow
    total = db.query(func.count(Row.id)).scalar() or 0

    by_class = dict(
        db.query(Row.entity_class, func.count(Row.id))
        .group_by(Row.entity_class)
        .all()
    )

    top_sub = (
        db.query(Row.sub_class, func.count(Row.id).label("n"))
        .filter(Row.entity_class == "valve", Row.sub_class.isnot(None))
        .group_by(Row.sub_class)
        .order_by(func.count(Row.id).desc())
        .limit(10)
        .all()
    )

    top_jobs = (
        db.query(Row.job_id, func.count(Row.id).label("n"))
        .filter(Row.entity_class == "valve")
        .group_by(Row.job_id)
        .order_by(func.count(Row.id).desc())
        .limit(10)
        .all()
    )

    # Cross-job duplicate-tag audit: any tag appearing in ≥2 distinct jobs is
    # an audit signal — either re-extraction (same drawing, two runs) or a
    # legitimate same-tag-on-two-drawings case. Top-15 by job count. Capped
    # to keep payload bounded; full search via /entities?tag_contains=<tag>.
    from sqlalchemy import distinct
    dup_tags = (
        db.query(
            Row.tag,
            func.count(distinct(Row.job_id)).label("job_count"),
            func.count(Row.id).label("row_count"),
        )
        .filter(Row.tag.isnot(None), Row.tag != "")
        .group_by(Row.tag)
        .having(func.count(distinct(Row.job_id)) >= 2)
        .order_by(func.count(distinct(Row.job_id)).desc(), func.count(Row.id).desc())
        .limit(15)
        .all()
    )

    return {
        "total_rows": total,
        "by_class": by_class,
        "top_valve_sub_classes": [{"sub_class": s, "count": n} for s, n in top_sub],
        "top_jobs_by_valve_count": [{"job_id": j, "count": n} for j, n in top_jobs],
        "duplicate_tags_across_jobs": [
            {"tag": t, "job_count": jc, "row_count": rc}
            for t, jc, rc in dup_tags
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Annotation metrics — model-vs-user volume + last-30-days breakdown.
# Reads `user_annotations.status` for the user side and `Job.gpu_detections`
# (JSON list per job) for the model side. Cheap aggregations; super-admin only.
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/annotations/metrics")
def admin_annotations_metrics(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Training-feedback dashboard data.

    Returns:
      - `total_model_detections`  — sum of len(Job.gpu_detections) across
        `done` jobs that have a non-null detections JSON.
      - `total_user_annotations` — total rows in `user_annotations`.
      - `by_status`              — counts per status bucket
        (`user_added`, `user_confirmed`, `user_rejected`, `model_found`).
      - `per_day_last_30`        — last 30 days of (date, model, user)
        with the model count derived from Job.completed_at falling in the
        day window and the user count from UserAnnotation.created_at.
    """
    import json as _json
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    # User annotations — by status.
    rows = (
        db.query(models.UserAnnotation.status, func.count(models.UserAnnotation.id))
        .group_by(models.UserAnnotation.status)
        .all()
    )
    by_status = {s: int(n) for s, n in rows}
    for bucket in ("user_added", "user_confirmed", "user_rejected", "model_found"):
        by_status.setdefault(bucket, 0)
    total_user_annotations = (
        db.query(func.count(models.UserAnnotation.id)).scalar() or 0
    )

    # Model detections — total = sum(len(json_list)) across done jobs.
    total_model_detections = 0
    done_jobs = (
        db.query(models.Job.id, models.Job.gpu_detections, models.Job.completed_at)
        .filter(models.Job.status == "done")
        .all()
    )
    # Build a per-day model count alongside the total so we only parse JSON once.
    model_per_day: dict = {}
    for _id, gd_raw, completed_at in done_jobs:
        if not gd_raw:
            continue
        try:
            parsed = _json.loads(gd_raw) if isinstance(gd_raw, str) else gd_raw
        except Exception:
            continue
        if not isinstance(parsed, list):
            continue
        n = len(parsed)
        total_model_detections += n
        if completed_at is not None:
            day = completed_at.date().isoformat()
            model_per_day[day] = model_per_day.get(day, 0) + n

    # User annotations per-day (created_at).
    user_rows = (
        db.query(
            func.date(models.UserAnnotation.created_at).label("d"),
            func.count(models.UserAnnotation.id),
        )
        .group_by(func.date(models.UserAnnotation.created_at))
        .all()
    )
    user_per_day: dict = {}
    for d, n in user_rows:
        if d is None:
            continue
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        user_per_day[key] = int(n)

    # Stitch last 30 days inclusive of today.
    today = _dt.now(_tz.utc).date()
    per_day_last_30 = []
    for offset in range(29, -1, -1):
        day = (today - _td(days=offset)).isoformat()
        per_day_last_30.append({
            "date": day,
            "model": int(model_per_day.get(day, 0)),
            "user": int(user_per_day.get(day, 0)),
        })

    return {
        "total_model_detections": total_model_detections,
        "total_user_annotations": int(total_user_annotations),
        "by_status": by_status,
        "per_day_last_30": per_day_last_30,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-learning summary — retrain-readiness + per-class weakness dashboard.
# Single round-trip snapshot for the self-learning loop (FEATURES self-learning
# Phase 1). Anchors "corrections since the current model" on
# `webapp.model_version.current_model_trained_at()`. Reads correction signal
# from `model_corrections`, `user_annotations`, `entity_overrides` (tag edits),
# and `graph_corrections`. Per-class `deleted` bucketing needs the deleted
# detection's class, recovered from `Job.gpu_detections[detection_index]`.
# ─────────────────────────────────────────────────────────────────────────────

# Tunable Phase-1 retrain trigger: once this many *labeled* corrections have
# accumulated since the current model was trained, the loop is "ready" to
# retrain. Bumped deliberately (not auto) when we recalibrate the cadence.
RETRAIN_READINESS_THRESHOLD = 200


def _det_label(det: object) -> Optional[str]:
    """Best-effort YOLO label from one gpu_detections item.

    Accepts both stored shapes — in-process inference (`label`) and the legacy
    Windows worker (`yolo_class`). Returns None when the shape is unexpected.
    """
    if not isinstance(det, dict):
        return None
    return det.get("label") or det.get("yolo_class")


def _canonical_pair(label: Optional[str]) -> tuple:
    """(entity_class, sub_class) for a correction label, robust to two formats.

    `ModelCorrection.new_label` and detection labels come in canonical
    `<entity_class>_<sub_class>` form (e.g. "valve_bv", "instrument_lt").
    `yolo_to_canonical` resolves the ones that are real YOLO labels (valves,
    inst_field), but instrument SUB-classes (LT/TT/PT/…) have `yolo_label: null`
    in the taxonomy, so it returns (None, None) for "instrument_lt" — which would
    otherwise bucket separately from the annotation side's "instrument/LT".
    Fall back to splitting the canonical form so both collapse to one class.
    """
    if not label:
        return (None, None)
    ec, sc = yolo_to_canonical(label)
    if sc:
        return (ec, sc)
    if "_" in label:
        head, tail = label.split("_", 1)
        if head in ("valve", "instrument", "equipment") and tail:
            return (head, tail.upper())
    return (ec, sc)


def _class_display_key(entity_class: Optional[str], sub_class: Optional[str], raw_label: Optional[str]) -> str:
    """Display bucket key: `entity_class/sub_class` when known, else the raw
    YOLO label, else "unknown"."""
    if entity_class and sub_class:
        return f"{entity_class}/{sub_class}"
    if entity_class:
        return entity_class
    if raw_label:
        return raw_label
    return "unknown"


class LearningTotals(BaseModel):
    model_corrections: int
    model_corrections_since_model: int
    user_annotations: int
    user_annotations_labeled: int
    user_annotations_since_model: int
    tag_edits: int
    tag_edits_since_model: int
    entity_overrides: int
    graph_corrections: int
    graph_corrections_since_model: int


class RetrainReadiness(BaseModel):
    labeled_corrections_since_model: int
    threshold: int
    ready: bool
    current_model: str


class ClassStat(BaseModel):
    cls: str
    entity_class: Optional[str] = None
    sub_class: Optional[str] = None
    added: int
    reclassified: int
    deleted: int
    confirmed: int
    rejected: int
    total_corrections: int


class JobStat(BaseModel):
    job_id: int
    pid_no: Optional[str] = None
    corrections: int
    annotations: int
    tag_edits: int


class LearningSummaryResponse(BaseModel):
    model_version: str
    model_trained_at: Optional[str] = None
    generated_at: str
    totals: LearningTotals
    retrain_readiness: RetrainReadiness
    by_action: Dict[str, int]
    by_class: List[ClassStat]
    by_job: List[JobStat]


class _ClassBucket:
    """Mutable per-class accumulator with the canonical (entity_class, sub_class)
    captured once so the display key stays stable."""

    __slots__ = ("entity_class", "sub_class", "raw_label", "added",
                 "reclassified", "deleted", "confirmed", "rejected")

    def __init__(self, entity_class=None, sub_class=None, raw_label=None):
        self.entity_class = entity_class
        self.sub_class = sub_class
        self.raw_label = raw_label
        self.added = 0
        self.reclassified = 0
        self.deleted = 0
        self.confirmed = 0
        self.rejected = 0


@router.get("/learning/summary", response_model=LearningSummaryResponse)
def admin_learning_summary(
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Self-learning dashboard snapshot — retrain-readiness counter, all-time
    correction volumes, per-class "weakness" breakdown, and per-job correction
    counts. One round-trip; super-admin only.

    `*_since_model` counters anchor on `current_model_trained_at()`; when that's
    unknown (version not in the trained-at table) they're all 0 and `ready` is
    False rather than crashing.
    """
    import json as _json

    MC = models.ModelCorrection
    UA = models.UserAnnotation
    EO = models.EntityOverride
    GC = models.GraphCorrection

    trained_at = current_model_trained_at()
    version = current_version()

    # ── by_action (all-time ModelCorrection) ────────────────────────────────
    by_action = {"add": 0, "delete": 0, "reclassify": 0}
    for action, n in (
        db.query(MC.action, func.count(MC.id)).group_by(MC.action).all()
    ):
        if action in by_action:
            by_action[action] = int(n)

    # ── Totals ───────────────────────────────────────────────────────────────
    model_corrections_total = db.query(func.count(MC.id)).scalar() or 0
    user_annotations_total = db.query(func.count(UA.id)).scalar() or 0
    user_annotations_labeled = (
        db.query(func.count(UA.id))
        .filter(UA.status.in_(("user_added", "user_confirmed")))
        .scalar()
        or 0
    )
    tag_edits_total = (
        db.query(func.count(EO.id)).filter(EO.field_name == "tag").scalar() or 0
    )
    entity_overrides_total = db.query(func.count(EO.id)).scalar() or 0
    graph_corrections_total = db.query(func.count(GC.id)).scalar() or 0

    if trained_at is not None:
        model_corrections_since = (
            db.query(func.count(MC.id)).filter(MC.created_at >= trained_at).scalar() or 0
        )
        user_annotations_since = (
            db.query(func.count(UA.id)).filter(UA.created_at >= trained_at).scalar() or 0
        )
        tag_edits_since = (
            db.query(func.count(EO.id))
            .filter(EO.field_name == "tag", EO.edited_at >= trained_at)
            .scalar()
            or 0
        )
        graph_corrections_since = (
            db.query(func.count(GC.id)).filter(GC.created_at >= trained_at).scalar() or 0
        )
        # Labeled corrections since model = UA(user_added|user_confirmed)
        # + MC(add|reclassify), both with created_at >= trained_at.
        ua_labeled_since = (
            db.query(func.count(UA.id))
            .filter(
                UA.status.in_(("user_added", "user_confirmed")),
                UA.created_at >= trained_at,
            )
            .scalar()
            or 0
        )
        mc_labeled_since = (
            db.query(func.count(MC.id))
            .filter(MC.action.in_(("add", "reclassify")), MC.created_at >= trained_at)
            .scalar()
            or 0
        )
        labeled_since = int(ua_labeled_since) + int(mc_labeled_since)
    else:
        model_corrections_since = 0
        user_annotations_since = 0
        tag_edits_since = 0
        graph_corrections_since = 0
        labeled_since = 0

    totals = LearningTotals(
        model_corrections=int(model_corrections_total),
        model_corrections_since_model=int(model_corrections_since),
        user_annotations=int(user_annotations_total),
        user_annotations_labeled=int(user_annotations_labeled),
        user_annotations_since_model=int(user_annotations_since),
        tag_edits=int(tag_edits_total),
        tag_edits_since_model=int(tag_edits_since),
        entity_overrides=int(entity_overrides_total),
        graph_corrections=int(graph_corrections_total),
        graph_corrections_since_model=int(graph_corrections_since),
    )

    readiness = RetrainReadiness(
        labeled_corrections_since_model=labeled_since,
        threshold=RETRAIN_READINESS_THRESHOLD,
        ready=labeled_since >= RETRAIN_READINESS_THRESHOLD,
        current_model=version,
    )

    # ── by_class ──────────────────────────────────────────────────────────────
    buckets: Dict[str, _ClassBucket] = {}

    def _bucket(entity_class, sub_class, raw_label) -> _ClassBucket:
        key = _class_display_key(entity_class, sub_class, raw_label)
        b = buckets.get(key)
        if b is None:
            b = _ClassBucket(entity_class, sub_class, raw_label)
            buckets[key] = b
        return b

    # MC action=add / reclassify — bucket by new_label (the target class).
    for action, new_label, n in (
        db.query(MC.action, MC.new_label, func.count(MC.id))
        .filter(MC.action.in_(("add", "reclassify")))
        .group_by(MC.action, MC.new_label)
        .all()
    ):
        ec, sc = _canonical_pair(new_label)
        b = _bucket(ec, sc, new_label)
        if action == "add":
            b.added += int(n)
        else:
            b.reclassified += int(n)

    # MC action=delete — bucket by the deleted detection's class via
    # Job.gpu_detections[detection_index]. Load only the affected jobs once.
    delete_rows = (
        db.query(MC.job_id, MC.detection_index, func.count(MC.id))
        .filter(MC.action == "delete")
        .group_by(MC.job_id, MC.detection_index)
        .all()
    )
    if delete_rows:
        affected_job_ids = {jid for jid, _, _ in delete_rows}
        gpu_by_job: Dict[int, list] = {}
        for jid, gd_raw in (
            db.query(models.Job.id, models.Job.gpu_detections)
            .filter(models.Job.id.in_(affected_job_ids))
            .all()
        ):
            parsed = None
            if gd_raw:
                try:
                    parsed = _json.loads(gd_raw) if isinstance(gd_raw, str) else gd_raw
                except (ValueError, TypeError):
                    parsed = None
            gpu_by_job[jid] = parsed if isinstance(parsed, list) else []

        for jid, det_idx, n in delete_rows:
            dets = gpu_by_job.get(jid, [])
            raw_label = None
            if det_idx is not None and 0 <= det_idx < len(dets):
                raw_label = _det_label(dets[det_idx])
            ec, sc = _canonical_pair(raw_label)
            b = _bucket(ec, sc, raw_label)
            b.deleted += int(n)

    # UA status=user_added — bucket by (entity_class, sub_class).
    for ec, sc, n in (
        db.query(UA.entity_class, UA.sub_class, func.count(UA.id))
        .filter(UA.status == "user_added")
        .group_by(UA.entity_class, UA.sub_class)
        .all()
    ):
        b = _bucket(ec, sc, None)
        b.added += int(n)

    # UA status=user_confirmed / user_rejected — bucket by (entity_class, sub_class).
    for status, ec, sc, n in (
        db.query(UA.status, UA.entity_class, UA.sub_class, func.count(UA.id))
        .filter(UA.status.in_(("user_confirmed", "user_rejected")))
        .group_by(UA.status, UA.entity_class, UA.sub_class)
        .all()
    ):
        b = _bucket(ec, sc, None)
        if status == "user_confirmed":
            b.confirmed += int(n)
        else:
            b.rejected += int(n)

    class_stats: List[ClassStat] = []
    for key, b in buckets.items():
        total_corr = b.added + b.reclassified + b.deleted + b.rejected
        class_stats.append(ClassStat(
            cls=key,
            entity_class=b.entity_class,
            sub_class=b.sub_class,
            added=b.added,
            reclassified=b.reclassified,
            deleted=b.deleted,
            confirmed=b.confirmed,
            rejected=b.rejected,
            total_corrections=total_corr,
        ))
    class_stats.sort(key=lambda c: c.total_corrections, reverse=True)
    class_stats = class_stats[:50]

    # ── by_job ─────────────────────────────────────────────────────────────────
    mc_by_job = dict(
        db.query(MC.job_id, func.count(MC.id)).group_by(MC.job_id).all()
    )
    ua_by_job = dict(
        db.query(UA.job_id, func.count(UA.id)).group_by(UA.job_id).all()
    )
    tag_edits_by_job = dict(
        db.query(EO.job_id, func.count(EO.id))
        .filter(EO.field_name == "tag")
        .group_by(EO.job_id)
        .all()
    )

    all_job_ids = set(mc_by_job) | set(ua_by_job) | set(tag_edits_by_job)
    pid_by_job: Dict[int, Optional[str]] = {}
    if all_job_ids:
        for jid, pid in (
            db.query(models.Job.id, models.Job.pid_no)
            .filter(models.Job.id.in_(all_job_ids))
            .all()
        ):
            pid_by_job[jid] = pid

    job_stats: List[JobStat] = []
    for jid in all_job_ids:
        job_stats.append(JobStat(
            job_id=jid,
            pid_no=pid_by_job.get(jid),
            corrections=int(mc_by_job.get(jid, 0)),
            annotations=int(ua_by_job.get(jid, 0)),
            tag_edits=int(tag_edits_by_job.get(jid, 0)),
        ))
    job_stats.sort(key=lambda j: j.corrections, reverse=True)
    job_stats = job_stats[:25]

    return LearningSummaryResponse(
        model_version=version,
        model_trained_at=utc_iso(trained_at) if trained_at else None,
        generated_at=utc_iso(datetime.now(timezone.utc)),
        totals=totals,
        retrain_readiness=readiness,
        by_action=by_action,
        by_class=class_stats,
        by_job=job_stats,
    )
