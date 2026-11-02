"""Society administration: residents, vehicles, RFID/FASTag credentials, user
accounts, invites, the audit trail and the admin dashboard."""
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import logview, models, schemas, timeutil
from ..audit import audit
from ..auth import hash_password, require_roles
from ..database import get_db
from ..security import validate_password

router = APIRouter(tags=["Admin"])

_admin_only = require_roles(models.UserRole.ADMIN)

INVITE_DAYS = 7
_INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L lookalikes


def _new_invite_code(db: Session) -> str:
    for _ in range(20):
        raw = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))
        code = f"MD-{raw[:4]}-{raw[4:]}"
        if db.query(models.Invite).filter(models.Invite.code == code).first() is None:
            return code
    raise HTTPException(status_code=500, detail="Could not generate an invite code; please retry.")


def _temp_password() -> str:
    while True:
        candidate = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
        try:
            return validate_password(candidate)
        except ValueError:
            continue


def _resident_or_404(db: Session, resident_id: int) -> models.Resident:
    r = db.query(models.Resident).filter(models.Resident.id == resident_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Resident not found.")
    return r


# ---------------------------------------------------------------------------
# Residents
# ---------------------------------------------------------------------------

@router.post("/residents", response_model=schemas.ResidentOut)
def create_resident(
    payload: schemas.ResidentCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    resident = models.Resident(name=payload.name, apartment_no=payload.apartment_no, phone=payload.phone)
    db.add(resident)
    db.commit()
    db.refresh(resident)
    audit(db, admin, "resident.create", "resident", resident.id, f"{resident.name}, flat {resident.apartment_no}")
    return resident


@router.patch("/residents/{resident_id}", response_model=schemas.ResidentOut)
def update_resident(
    resident_id: int,
    payload: schemas.ResidentUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    resident = _resident_or_404(db, resident_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if value is not None or field == "phone":
            setattr(resident, field, value)
    db.commit()
    db.refresh(resident)
    audit(db, admin, "resident.update", "resident", resident.id, ", ".join(sorted(changes)))
    return resident


# ---------------------------------------------------------------------------
# Vehicles and credentials
# ---------------------------------------------------------------------------

@router.post("/vehicles", response_model=schemas.VehicleOut)
def create_vehicle(
    payload: schemas.VehicleCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    if payload.resident_id is not None:
        _resident_or_404(db, payload.resident_id)
    if db.query(models.Vehicle).filter(models.Vehicle.vehicle_number == payload.vehicle_number).first():
        raise HTTPException(status_code=400, detail="A vehicle with this number is already registered.")
    vehicle = models.Vehicle(
        resident_id=payload.resident_id, vehicle_number=payload.vehicle_number, vehicle_type=payload.vehicle_type,
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    audit(db, admin, "vehicle.create", "vehicle", vehicle.id, vehicle.vehicle_number)
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=schemas.VehicleOut)
def update_vehicle(
    vehicle_id: int,
    payload: schemas.VehicleUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == vehicle_id).first()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("resident_id") is not None:
        _resident_or_404(db, changes["resident_id"])
    if changes.get("vehicle_number") and changes["vehicle_number"] != vehicle.vehicle_number:
        if db.query(models.Vehicle).filter(models.Vehicle.vehicle_number == changes["vehicle_number"]).first():
            raise HTTPException(status_code=400, detail="A vehicle with this number is already registered.")
    for field, value in changes.items():
        if value is not None or field == "resident_id":
            setattr(vehicle, field, value)
    db.commit()
    db.refresh(vehicle)
    audit(db, admin, "vehicle.update", "vehicle", vehicle.id, ", ".join(sorted(changes)))
    return vehicle


@router.post("/credentials", response_model=schemas.CredentialOut)
def create_credential(
    payload: schemas.CredentialCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == payload.vehicle_id).first()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    if payload.expires_at is not None and payload.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="The expiry must be in the future.")

    value = payload.credential_value
    if value is None:
        prefix = "FASTAG" if payload.credential_type == models.CredentialType.FASTAG else "RFID"
        for _ in range(10):
            candidate = f"{prefix}-{secrets.token_hex(4).upper()}"
            if db.query(models.VehicleCredential).filter(models.VehicleCredential.credential_value == candidate).first() is None:
                value = candidate
                break
        else:
            raise HTTPException(status_code=500, detail="Could not generate a credential code; please retry.")
    elif db.query(models.VehicleCredential).filter(models.VehicleCredential.credential_value == value).first():
        raise HTTPException(status_code=400, detail="This credential code is already in use.")

    credential = models.VehicleCredential(
        vehicle_id=vehicle.id, credential_type=payload.credential_type, credential_value=value,
        status=models.CredentialStatus.ACTIVE, credential_scope=models.CredentialScope.RESIDENT,
        expires_at=payload.expires_at,
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    audit(db, admin, "credential.issue", "credential", credential.id, f"{value} for {vehicle.vehicle_number}")
    return credential


@router.patch("/credentials/{credential_id}", response_model=schemas.CredentialOut)
def update_credential(
    credential_id: int,
    payload: schemas.CredentialUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    credential = db.query(models.VehicleCredential).filter(models.VehicleCredential.id == credential_id).first()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    notes = []
    if payload.status is not None:
        credential.status = payload.status
        notes.append(f"status={payload.status.value}")
    if payload.clear_expiry:
        credential.expires_at = None
        notes.append("expiry cleared")
        # Clearing the expiry of a tag that lapsed brings it back into use.
        if credential.status == models.CredentialStatus.EXPIRED:
            credential.status = models.CredentialStatus.ACTIVE
    elif payload.expires_at is not None:
        credential.expires_at = payload.expires_at
        notes.append("expiry set")
        # Re-activating an expired tag with a future expiry should work.
        if credential.status == models.CredentialStatus.EXPIRED and payload.expires_at > datetime.utcnow():
            credential.status = models.CredentialStatus.ACTIVE
    db.commit()
    db.refresh(credential)
    audit(db, admin, "credential.update", "credential", credential.id, f"{credential.credential_value}: {', '.join(notes)}")
    return credential


# ---------------------------------------------------------------------------
# User accounts
# ---------------------------------------------------------------------------

@router.get("/admin/users", response_model=List[schemas.UserOut])
def list_users(
    role: Optional[models.UserRole] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    query = db.query(models.User)
    if role is not None:
        query = query.filter(models.User.role == role)
    return query.order_by(models.User.role, models.User.name).all()


@router.post("/admin/users", response_model=schemas.UserCreated)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    if db.query(models.User).filter(func.lower(models.User.email) == payload.email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    password = payload.password or _temp_password()
    user = models.User(
        name=payload.name, email=payload.email, password_hash=hash_password(password), role=payload.role,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, admin, "user.create", "user", user.id, f"{user.role.value} {user.email}")
    out = schemas.UserCreated.model_validate(user)
    if not payload.password:
        out.temporary_password = password   # shown to the admin once
    return out


@router.post("/admin/users/{user_id}/reset-password", response_model=schemas.UserCreated)
def reset_password(
    user_id: int,
    payload: schemas.PasswordReset = schemas.PasswordReset(),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    password = payload.password or _temp_password()
    user.password_hash = hash_password(password)
    user.token_version = (user.token_version or 0) + 1   # ends their current sessions
    user.must_change_password = True
    db.commit()
    db.refresh(user)
    audit(db, admin, "user.reset_password", "user", user.id, user.email)
    out = schemas.UserCreated.model_validate(user)
    if not payload.password:
        out.temporary_password = password
    return out


@router.post("/admin/users/{user_id}/active", response_model=schemas.UserOut)
def set_user_active(
    user_id: int,
    payload: schemas.ActiveUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == admin.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    user.is_active = payload.is_active
    if not payload.is_active:
        user.token_version = (user.token_version or 0) + 1
    db.commit()
    db.refresh(user)
    audit(db, admin, "user.activate" if payload.is_active else "user.deactivate", "user", user.id, user.email)
    return user


# ---------------------------------------------------------------------------
# Invites (how a resident gets a login)
# ---------------------------------------------------------------------------

def _invite_out(invite: models.Invite, now: datetime) -> schemas.InviteOut:
    status = "USED" if invite.used_at else ("EXPIRED" if invite.expires_at < now else "ACTIVE")
    r = invite.resident
    return schemas.InviteOut(
        id=invite.id, code=invite.code, resident_id=invite.resident_id,
        resident_label=f"{r.name} ({r.apartment_no})" if r else None,
        created_at=invite.created_at, expires_at=invite.expires_at, used_at=invite.used_at, status=status,
    )


@router.post("/admin/invites", response_model=schemas.InviteOut)
def create_invite(
    payload: schemas.InviteCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    _resident_or_404(db, payload.resident_id)
    now = datetime.utcnow()
    invite = models.Invite(
        code=_new_invite_code(db), resident_id=payload.resident_id, created_by_user_id=admin.id,
        expires_at=now + timedelta(days=INVITE_DAYS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    audit(db, admin, "invite.create", "resident", payload.resident_id, f"valid {INVITE_DAYS} days")
    return _invite_out(invite, now)


@router.get("/admin/invites", response_model=List[schemas.InviteOut])
def list_invites(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    now = datetime.utcnow()
    rows = db.query(models.Invite).order_by(models.Invite.created_at.desc()).limit(200).all()
    return [_invite_out(i, now) for i in rows]


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

@router.get("/audit-logs", response_model=List[schemas.AuditOut])
def list_audit(
    q: Optional[str] = Query(None, max_length=80),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    query = db.query(models.AuditLog)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(
            func.lower(models.AuditLog.action).like(like)
            | func.lower(func.coalesce(models.AuditLog.user_name, "")).like(like)
            | func.lower(func.coalesce(models.AuditLog.detail, "")).like(like)
        )
    return query.order_by(models.AuditLog.created_at.desc(), models.AuditLog.id.desc()).offset(offset).limit(limit).all()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/admin/dashboard")
def dashboard(db: Session = Depends(get_db), admin: models.User = Depends(_admin_only)):
    now = datetime.utcnow()
    start, end = timeutil.local_day_bounds_utc(timeutil.local_today())
    EL, AR = models.EntryLog, models.AccessResult

    today = {"granted": 0, "denied": 0, "by_method": {}}
    for method, access, count in (
        db.query(EL.entry_method, EL.access, func.count())
        .filter(EL.timestamp >= start, EL.timestamp < end).group_by(EL.entry_method, EL.access).all()
    ):
        key = "granted" if access == AR.GRANTED else "denied"
        today[key] += count
        bucket = today["by_method"].setdefault(method.value, {"granted": 0, "denied": 0})
        bucket[key] += count

    hourly = [0] * 24
    for ts, in db.query(EL.timestamp).filter(EL.timestamp >= start, EL.timestamp < end, EL.access == AR.GRANTED).all():
        hourly[timeutil.to_local(ts).hour] += 1

    V = models.Visitor
    live_passes = db.query(V).filter(V.cancelled_at.is_(None), V.valid_from <= now, V.valid_until >= now).count()
    scheduled = db.query(V).filter(V.cancelled_at.is_(None), V.valid_from > now).count()

    D, DS = models.Delivery, models.DeliveryStatus
    deliveries = {s.value: db.query(D).filter(D.status == s).count() for s in (DS.EXPECTED, DS.AWAITING_APPROVAL, DS.APPROVED)}

    C, CS = models.Complaint, models.ComplaintStatus
    open_c = db.query(C).filter(C.status == CS.OPEN).count()
    prog_c = db.query(C).filter(C.status == CS.IN_PROGRESS).count()
    oldest = db.query(func.min(C.raised_at)).filter(C.status != CS.RESOLVED).scalar()

    present_staff = {
        sid for sid, in db.query(EL.staff_id).filter(
            EL.timestamp >= start, EL.timestamp < end, EL.staff_id.isnot(None),
            EL.access == AR.GRANTED, EL.direction == models.Direction.IN).all()
    }
    sos_active = db.query(models.SosAlert).filter(models.SosAlert.status != models.SosStatus.RESOLVED).count()
    denied_24h = db.query(EL).filter(EL.access == AR.DENIED, EL.timestamp >= now - timedelta(hours=24)).count()

    recent = (
        db.query(EL).options(*logview.LOG_LOAD).order_by(EL.timestamp.desc(), EL.id.desc()).limit(10).all()
    )
    return {
        "today": today,
        "hourly_granted": hourly,
        "visitor_passes": {"live": live_passes, "scheduled": scheduled},
        "deliveries": deliveries,
        "complaints": {
            "open": open_c, "in_progress": prog_c,
            "oldest_open_days": (now - oldest).days if oldest else 0,
        },
        "staff_present_today": len(present_staff),
        "sos_active": sos_active,
        "denied_24h": denied_24h,
        "totals": {
            "residents": db.query(models.Resident).count(),
            "vehicles": db.query(models.Vehicle).count(),
            "credentials_active": db.query(models.VehicleCredential).filter(
                models.VehicleCredential.status == models.CredentialStatus.ACTIVE).count(),
            "guards": db.query(models.User).filter(models.User.role == models.UserRole.GUARD, models.User.is_active == True).count(),  # noqa: E712
            "resident_logins": db.query(models.User).filter(models.User.role == models.UserRole.RESIDENT, models.User.is_active == True).count(),  # noqa: E712
            "staff": db.query(models.Staff).count(),
        },
        "recent_activity": [logview.log_dict(l) for l in recent],
    }
