import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, notify, schemas
from ..auth import get_current_user, hash_password, issue_token, verify_password
from ..database import get_db
from ..security import (
    client_ip, invite_by_ip, login_by_email, login_by_ip, raise_if_locked,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

MAX_LOGINS_PER_RESIDENT = 5
# A real bcrypt hash, checked when the email is unknown so the response time
# does not reveal which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password-1")


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.UserRegister, request: Request, db: Session = Depends(get_db)):
    """Create a resident login from an admin-issued invite code."""
    ip = client_ip(request)
    raise_if_locked(invite_by_ip, ip, "sign-up attempts")

    now = datetime.utcnow()
    code = payload.invite_code.strip().upper()
    invite = db.query(models.Invite).filter(models.Invite.code == code).first()
    if invite is None or invite.used_at is not None or invite.expires_at < now:
        invite_by_ip.fail(ip)
        raise HTTPException(status_code=400, detail="That invite code is not valid or has expired. Ask your society admin for a new one.")

    if db.query(models.User).filter(func.lower(models.User.email) == payload.email).first() is not None:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    resident = db.query(models.Resident).filter(models.Resident.id == invite.resident_id).first()
    if resident is None:
        raise HTTPException(status_code=404, detail="The resident record for this invite no longer exists.")

    existing = db.query(models.User).filter(models.User.resident_id == resident.id).count()
    if existing >= MAX_LOGINS_PER_RESIDENT:
        raise HTTPException(status_code=400, detail="This flat already has the maximum number of logins.")

    user = models.User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=models.UserRole.RESIDENT,
        resident_id=resident.id,
    )
    db.add(user)
    db.flush()
    invite.used_at = now
    invite.used_by_user_id = user.id
    db.commit()
    db.refresh(user)
    notify.notify_admins(db, "ACCOUNT", "New resident account", f"{user.name} joined for flat {resident.apartment_no}.")
    return user


@router.post("/login", response_model=schemas.Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = (form_data.username or "").strip().lower()[:120]
    ip = client_ip(request)
    raise_if_locked(login_by_ip, ip, "sign-in attempts")
    raise_if_locked(login_by_email, email, "sign-in attempts")

    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if user is None:
        verify_password(form_data.password or "", _DUMMY_HASH)
        ok = False
    else:
        ok = verify_password(form_data.password or "", user.password_hash) and user.is_active

    if not ok:
        login_by_email.fail(email)
        login_by_ip.fail(ip)
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_by_email.reset(email)
    user.last_login_at = datetime.utcnow()
    db.commit()
    return schemas.Token(access_token=issue_token(user), token_type="bearer")


@router.post("/refresh", response_model=schemas.Token)
def refresh(current_user: models.User = Depends(get_current_user)):
    """A fresh token for a still-valid session (the page calls this while it is open)."""
    return schemas.Token(access_token=issue_token(current_user), token_type="bearer")


@router.post("/change-password", response_model=schemas.Token)
def change_password(
    payload: schemas.ChangePassword,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is not correct.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="Choose a new password that is different from the current one.")
    current_user.password_hash = hash_password(payload.new_password)
    current_user.token_version = (current_user.token_version or 0) + 1   # signs out every other device
    current_user.must_change_password = False
    db.commit()
    db.refresh(current_user)
    return schemas.Token(access_token=issue_token(current_user), token_type="bearer")


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user
