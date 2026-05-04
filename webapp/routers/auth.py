"""Auth routes: /login, /register (public with approval), /logout."""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import create_access_token, get_current_user, hash_password, verify_password
from webapp.database import get_db
from webapp.jinja import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=400,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Your account is pending approval. Please contact the administrator."},
            status_code=403,
        )
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax")
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request, db)
    except Exception:
        current_user = None
    return templates.TemplateResponse("register.html", {"request": request, "user": current_user})


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        current_user = get_current_user(request, db)
    except Exception:
        current_user = None

    if db.query(models.User).filter(models.User.username == username).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already taken", "user": current_user},
            status_code=400,
        )

    is_first_user = db.query(models.User).count() == 0
    # First user → super_admin, active immediately.
    # Super_admin creating via this form → active immediately.
    # Public self-registration → pending approval (is_active=False).
    if is_first_user:
        role, is_active = "super_admin", True
    elif current_user and current_user.role == "super_admin":
        role, is_active = "user", True
    else:
        role, is_active = "user", False  # requires admin approval

    user = models.User(
        username=username,
        email=email or None,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()

    # Record signup trial credits in the ledger (column default already gives 10 credits;
    # this creates the audit row so ledger invariant holds from day 1)
    from webapp import credits as credits_module
    credits_module.grant(user, 10, reason="signup_grant", db=db)

    # Super_admin creating via /register form — stay logged in, go to dashboard
    if current_user and current_user.role == "super_admin":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    if is_first_user:
        new_token = create_access_token({"sub": user.username})
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="access_token", value=new_token, httponly=True, samesite="lax")
        return response

    # Self-registered: show pending approval message
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "user": None,
            "success": "Account created! Your account is pending approval by an administrator before you can log in.",
        },
    )


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
