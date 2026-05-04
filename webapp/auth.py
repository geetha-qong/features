"""JWT + bcrypt auth utilities."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from webapp.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from webapp.database import get_db
from webapp import models

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    except JWTError:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_super_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> models.User:
    user = get_current_user(request, db)
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super-admin access required")
    return user


async def get_user_from_api_key(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """Extract and verify a Bearer API key from the Authorization header."""
    from webapp.models import ApiKey
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer qk_"):
        return None
    full_key = auth_header[7:]  # strip "Bearer "
    prefix = full_key[:8]
    candidates = db.query(ApiKey).filter(
        ApiKey.key_prefix == prefix,
        ApiKey.revoked_at.is_(None),
    ).all()
    for api_key in candidates:
        if pwd_context.verify(full_key, api_key.key_hash):
            # Update last_used_at
            api_key.last_used_at = datetime.utcnow()
            db.commit()
            user = db.query(models.User).filter(models.User.id == api_key.user_id).first()
            return user
    return None
