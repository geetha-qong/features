"""Auth routes: /login, /register (auth-only), /logout."""
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
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax")
    return response


def _can_register(db: Session, request: Request) -> bool:
    """Allow registration only if: (a) no users exist yet, or (b) caller is logged in."""
    token = request.cookies.get("access_token")
    if token:
        return True  # logged-in user can always create new accounts
    return db.query(models.User).count() == 0  # first-time setup only


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    if not _can_register(db, request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    # Pass current user to template if logged in (for navbar)
    try:
        from webapp.auth import get_current_user as _gcu
        current_user = _gcu(request, db)
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
    if not _can_register(db, request):
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if db.query(models.User).filter(models.User.username == username).first():
        try:
            from webapp.auth import get_current_user as _gcu
            current_user = _gcu(request, db)
        except Exception:
            current_user = None
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already taken", "user": current_user},
            status_code=400,
        )

    user = models.User(
        username=username,
        email=email or None,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()

    # If a user was already logged in (creating another account), stay logged in as them
    token = request.cookies.get("access_token")
    if token:
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return response

    # First-time setup: log in as the new user
    new_token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=new_token, httponly=True, samesite="lax")
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
