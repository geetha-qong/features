"""Super-admin routes (/admin/*) and annotator landing page (/annotate)."""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp import credits as credits_module
from webapp.auth import get_current_user, hash_password, require_super_admin
from webapp.database import get_db
from webapp.jinja import templates
from webapp import label_studio_client as ls
from webapp.config import JOB_OUTPUT_DIR, get_job_dir

router = APIRouter()


# ── Annotator landing page ────────────────────────────────────────────────────

@router.get("/annotate", response_class=HTMLResponse)
async def annotate_page(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("annotator", "super_admin"):
        raise HTTPException(status_code=403, detail="Annotator access required")
    synced_jobs = (
        db.query(models.Job)
        .filter(models.Job.ls_synced == True)
        .order_by(models.Job.created_at.desc())
        .all()
    )
    job_stats = []
    for job in synced_jobs:
        stats = ls.get_project_stats(job.ls_project_id) if job.ls_project_id else {}
        job_stats.append({"job": job, "stats": stats})

    return templates.TemplateResponse(
        "annotate.html",
        {
            "request": request,
            "user": current_user,
            "job_stats": job_stats,
            "ls_url": ls.LS_EXTERNAL_URL,
            "ls_configured": ls.is_configured(),
        },
    )


# ── User management ───────────────────────────────────────────────────────────

@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    users = db.query(models.User).order_by(models.User.created_at).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": current_user, "users": users},
    )


@router.post("/admin/users/create")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form("user"),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if db.query(models.User).filter(models.User.username == username).first():
        users = db.query(models.User).order_by(models.User.created_at).all()
        return templates.TemplateResponse(
            "admin/users.html",
            {"request": request, "user": current_user, "users": users,
             "error": f"Username '{username}' already taken"},
            status_code=400,
        )
    if role not in ("user", "annotator", "super_admin"):
        role = "user"
    new_user = models.User(
        username=username,
        email=email or None,
        password_hash=hash_password(password),
        role=role,
        is_active=True,  # admin-created users are always active
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/role")
async def admin_change_role(
    user_id: int,
    role: str = Form(...),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if role not in ("user", "annotator", "super_admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    target.role = role
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/activate")
async def admin_activate_user(
    user_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(
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
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/delete")
async def admin_delete_user(
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
    return RedirectResponse(url="/admin/users", status_code=303)


# ── Label Studio sync ─────────────────────────────────────────────────────────

@router.get("/admin/label-studio", response_class=HTMLResponse)
async def admin_label_studio(
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(models.Job)
        .filter(models.Job.status == "done")
        .order_by(models.Job.created_at.desc())
        .all()
    )
    job_stats = []
    for job in jobs:
        stats = ls.get_project_stats(job.ls_project_id) if job.ls_project_id else {}
        job_stats.append({"job": job, "stats": stats})

    return templates.TemplateResponse(
        "admin/label_studio.html",
        {
            "request": request,
            "user": current_user,
            "job_stats": job_stats,
            "ls_url": ls.LS_EXTERNAL_URL,
            "ls_configured": ls.is_configured(),
        },
    )


@router.post("/admin/label-studio/sync/{job_id}")
async def admin_sync_job(
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

    # Delete stale tasks first so re-sync replaces image URLs (not duplicates)
    ls.delete_all_tasks(project_id)
    pushed = ls.push_tiles(project_id, tile_urls)
    job.ls_project_id = project_id
    job.ls_synced = pushed > 0
    db.commit()

    return RedirectResponse(url="/admin/label-studio", status_code=303)


# ── Admin Dashboard ────────────────────────────────────────────────────────────

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    total_users = db.query(models.User).count()
    active_users = db.query(models.User).filter(models.User.is_active == True).count()
    pending_users = db.query(models.User).filter(models.User.is_active == False).count()
    total_jobs = db.query(models.Job).count()
    done_jobs = db.query(models.Job).filter(models.Job.status == "done").count()
    open_feedback = db.query(models.UserFeedback).filter(models.UserFeedback.status == "new").count()
    recent_txns = (
        db.query(models.CreditTransaction)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(10)
        .all()
    )
    mtd_consumed = db.query(func.sum(models.CreditTransaction.delta)).filter(
        models.CreditTransaction.delta < 0
    ).scalar() or 0
    mtd_granted = db.query(func.sum(models.CreditTransaction.delta)).filter(
        models.CreditTransaction.delta > 0
    ).scalar() or 0
    users_map = {u.id: u for u in db.query(models.User).all()}
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request, "user": current_user,
        "total_users": total_users, "active_users": active_users,
        "pending_users": pending_users, "total_jobs": total_jobs,
        "done_jobs": done_jobs, "open_feedback": open_feedback,
        "mtd_consumed": abs(mtd_consumed), "mtd_granted": mtd_granted,
        "recent_txns": recent_txns, "users_map": users_map,
    })


# ── Credits ledger ─────────────────────────────────────────────────────────────

@router.get("/admin/credits", response_class=HTMLResponse)
async def admin_credits(
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    txns = (
        db.query(models.CreditTransaction)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(200)
        .all()
    )
    users_map = {u.id: u for u in db.query(models.User).all()}
    return templates.TemplateResponse("admin/credits.html", {
        "request": request, "user": current_user,
        "txns": txns, "users_map": users_map,
    })


@router.post("/admin/users/{user_id}/grant-credits")
async def admin_grant_credits(
    user_id: int,
    amount: int = Form(...),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if amount <= 0 or amount > 10000:
        raise HTTPException(status_code=400, detail="Amount must be 1–10000")
    credits_module.grant(target, amount, reason="admin_grant", db=db, admin_id=current_user.id)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/change-tier")
async def admin_change_tier(
    user_id: int,
    tier: str = Form(...),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if tier not in ("trial", "starter", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Invalid tier")
    target.tier = tier
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


# ── Feedback inbox ─────────────────────────────────────────────────────────────

@router.get("/admin/feedback", response_class=HTMLResponse)
async def admin_feedback(
    request: Request,
    status_filter: str = "new",
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(models.UserFeedback).order_by(models.UserFeedback.created_at.desc())
    if status_filter and status_filter != "all":
        q = q.filter(models.UserFeedback.status == status_filter)
    items = q.limit(100).all()
    users_map = {u.id: u for u in db.query(models.User).all()}
    open_count = db.query(models.UserFeedback).filter(models.UserFeedback.status == "new").count()
    return templates.TemplateResponse("admin/feedback.html", {
        "request": request, "user": current_user,
        "items": items, "users_map": users_map,
        "status_filter": status_filter, "open_count": open_count,
    })


@router.post("/admin/feedback/{item_id}/update")
async def admin_update_feedback(
    item_id: int,
    status: str = Form(...),
    admin_notes: str = Form(""),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    item = db.query(models.UserFeedback).filter(models.UserFeedback.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if status in ("new", "in_progress", "resolved", "wontfix"):
        item.status = status
    item.admin_notes = admin_notes.strip() or None
    db.commit()
    return RedirectResponse(url="/admin/feedback", status_code=303)


# ── Billing plans ──────────────────────────────────────────────────────────────

@router.get("/admin/plans", response_class=HTMLResponse)
async def admin_plans(
    request: Request,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plans = db.query(models.BillingPlan).order_by(models.BillingPlan.price_usd_cents).all()
    return templates.TemplateResponse("admin/plans.html", {
        "request": request, "user": current_user, "plans": plans,
    })


@router.post("/admin/plans/create")
async def admin_create_plan(
    name: str = Form(...),
    credits: int = Form(...),
    price_usd_cents: int = Form(...),
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plan = models.BillingPlan(name=name, credits=credits, price_usd_cents=price_usd_cents)
    db.add(plan)
    db.commit()
    return RedirectResponse(url="/admin/plans", status_code=303)


@router.post("/admin/plans/{plan_id}/toggle")
async def admin_toggle_plan(
    plan_id: int,
    current_user: models.User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    plan = db.query(models.BillingPlan).filter(models.BillingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.is_active = not plan.is_active
    db.commit()
    return RedirectResponse(url="/admin/plans", status_code=303)
