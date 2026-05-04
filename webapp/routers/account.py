"""User-facing account pages: /account, /account/api-keys, /account/billing, /feedback."""
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp import credits as credits_module
from webapp.auth import get_current_user, pwd_context
from webapp.database import get_db
from webapp.jinja import templates

router = APIRouter()


# ── Account home ───────────────────────────────────────────────────────────────

@router.get("/account", response_class=HTMLResponse)
async def account_home(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recent_txns = (
        db.query(models.CreditTransaction)
        .filter(models.CreditTransaction.user_id == current_user.id)
        .order_by(models.CreditTransaction.created_at.desc())
        .limit(10)
        .all()
    )
    recent_jobs = (
        db.query(models.Job)
        .filter(models.Job.user_id == current_user.id)
        .order_by(models.Job.created_at.desc())
        .limit(5)
        .all()
    )
    return templates.TemplateResponse("account/index.html", {
        "request": request,
        "user": current_user,
        "recent_txns": recent_txns,
        "recent_jobs": recent_jobs,
        "balance": credits_module.get_balance(current_user),
    })


# ── API Keys ───────────────────────────────────────────────────────────────────

@router.get("/account/api-keys", response_class=HTMLResponse)
async def account_api_keys(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    keys = (
        db.query(models.ApiKey)
        .filter(
            models.ApiKey.user_id == current_user.id,
            models.ApiKey.revoked_at.is_(None),
        )
        .order_by(models.ApiKey.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("account/api_keys.html", {
        "request": request,
        "user": current_user,
        "keys": keys,
    })


@router.post("/account/api-keys/create")
async def account_create_api_key(
    name: str = Form(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    random_part = secrets.token_hex(16)   # 32 hex chars
    full_key = f"qk_{random_part}"
    prefix = full_key[:8]                 # "qk_" + first 5 hex chars
    key_hash = pwd_context.hash(full_key)

    api_key = models.ApiKey(
        user_id=current_user.id,
        name=name.strip() or "Default",
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    db.commit()

    # Full key passed once via URL param — never stored in plaintext again
    return RedirectResponse(
        url=f"/account/api-keys?new_key={full_key}",
        status_code=303,
    )


@router.post("/account/api-keys/{key_id}/revoke")
async def account_revoke_api_key(
    key_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = db.query(models.ApiKey).filter(
        models.ApiKey.id == key_id,
        models.ApiKey.user_id == current_user.id,
    ).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="Key not found")
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/account/api-keys", status_code=303)


# ── Billing ────────────────────────────────────────────────────────────────────

@router.get("/account/billing", response_class=HTMLResponse)
async def account_billing(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plans = (
        db.query(models.BillingPlan)
        .filter(models.BillingPlan.is_active == True)
        .order_by(models.BillingPlan.price_usd_cents)
        .all()
    )
    return templates.TemplateResponse("account/billing.html", {
        "request": request,
        "user": current_user,
        "plans": plans,
        "balance": credits_module.get_balance(current_user),
    })


# ── User Feedback form ─────────────────────────────────────────────────────────

@router.get("/feedback", response_class=HTMLResponse)
async def feedback_form(request: Request, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request, db)
    except Exception:
        current_user = None
    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "user": current_user,
        "page_url": request.headers.get("referer", ""),
    })


@router.post("/feedback")
async def feedback_submit(
    request: Request,
    category: str = Form(...),
    subject: str = Form(...),
    message: str = Form(...),
    page_url: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        current_user = get_current_user(request, db)
        user_id: Optional[int] = current_user.id
    except Exception:
        user_id = None

    if category not in ("bug", "feature", "pricing", "other"):
        category = "other"
    if not subject.strip() or not message.strip():
        raise HTTPException(status_code=400, detail="Subject and message are required")

    item = models.UserFeedback(
        user_id=user_id,
        category=category,
        subject=subject.strip()[:255],
        message=message.strip(),
        page_url=page_url.strip()[:500] or None,
    )
    db.add(item)
    db.commit()

    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "user": None,
        "page_url": "",
        "success": "Thanks for your feedback! We'll review it soon.",
    })
