"""Auth routes: POST /login, GET /logout.

Public self-registration was removed 2026-06-02 — see FEATURES.md #19. New
users are created by a super_admin via `POST /api/v1/admin/users` (already
serving the React Admin UI's user-creation modal). First-user bootstrap on a
fresh DB is handled by a one-off SSM-direct script that inserts a super_admin
row directly via SQLAlchemy (template kept at `/tmp/qa_user_reset.sh` in the
2026-06-02 session memory; do NOT commit any password to this repo).

The Jinja `/login` GET page and `login.html` template were removed the same
day. The SPA's `/signin` route is now the sole login surface. POST /login
remains as the auth endpoint (cookie-set + 303 to /dashboard on success); on
failure it returns JSON `{"detail": ...}` for the SPA's AuthContext to parse.
Legacy unauth-middleware redirects in `webapp/auth.py` 303 to `/signin`.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import create_access_token, verify_password
from webapp.config import COOKIE_SECURE
from webapp.database import get_db

router = APIRouter()


def _set_auth_cookie(response, token):
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )


@router.get("/login")
async def login_redirect():
    # Legacy bookmark/redirect target. Forwards to the SPA's /signin route.
    return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Your account is pending approval. Please contact the administrator.",
        )
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    _set_auth_cookie(response, token)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
