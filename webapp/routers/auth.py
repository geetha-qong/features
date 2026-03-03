"""Auth routes: /login, /register, /logout."""
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import create_access_token, hash_password, verify_password
from webapp.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


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


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(models.User).filter(models.User.username == username).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Username already taken"},
            status_code=400,
        )
    user = models.User(
        username=username,
        email=email or None,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=token, httponly=True, samesite="lax")
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
