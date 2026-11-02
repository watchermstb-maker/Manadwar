"""Password hashing, JWT issuing/verification, and role-check dependencies.

HS256 JWT + bcrypt passwords + one shared secret: appropriate for a
single-community pilot. The secret comes from config.py, which refuses to start
in production without a real JWT_SECRET_KEY.
"""
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from . import models
from .config import ACCESS_TOKEN_EXPIRE_MINUTES, GUARD_TOKEN_EXPIRE_MINUTES, SECRET_KEY
from .database import get_db

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _to_bytes(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes; newer bcrypt releases raise an
    # error instead of silently truncating, so truncate explicitly.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain_password), password_hash.encode("utf-8"))
    except ValueError:
        return False


def token_lifetime(role: models.UserRole) -> timedelta:
    minutes = GUARD_TOKEN_EXPIRE_MINUTES if role == models.UserRole.GUARD else ACCESS_TOKEN_EXPIRE_MINUTES
    return timedelta(minutes=minutes)


def issue_token(user: models.User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "tv": user.token_version or 0,
        "exp": datetime.utcnow() + token_lifetime(user.role),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Kept for compatibility; prefer issue_token(user)."""
    to_encode = data.copy()
    to_encode["exp"] = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_tv = int(payload.get("tv", 0))
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active or (user.token_version or 0) != token_tv:
        raise credentials_exception
    return user


def require_roles(*roles: models.UserRole):
    """Dependency factory: only lets the listed roles through."""

    def dependency(current_user: models.User = Depends(get_current_user)) -> models.User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to do this.",
            )
        return current_user

    return dependency
