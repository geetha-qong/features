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
from datetime import datetime
from typing import Optional

from webapp.datetime_utils import utc_iso

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
