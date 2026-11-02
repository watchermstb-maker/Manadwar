"""Visitors: one-time/long-term OTP passes (plannable and cancellable), regular
pre-approved visitors, the gate's "expected today" list and gate photos."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, notify, schemas, timeutil, uploads, utils
from ..auth import get_current_user, require_roles
from ..database import get_db
from ..security import otp_by_user, raise_if_locked

router = APIRouter(tags=["Visitors / OTP Entry"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)

MAX_PLAN_AHEAD = timedelta(days=30)
MAX_SHORT_VISIT = timedelta(hours=24)
MAX_LONG_VISIT = timedelta(days=90)
MASKED_OTP = "••••••"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _unique_otp(db: Session, now: datetime) -> str:
    """A code no other live visitor pass or regular visitor currently holds."""
    for _ in range(50):
        candidate = utils.generate_otp()
        clash_v = (
            db.query(models.Visitor)
            .filter(models.Visitor.otp_code == candidate, models.Visitor.valid_until >= now,
                    models.Visitor.cancelled_at.is_(None))
            .first()
        )
        clash_r = (
            db.query(models.RecurringVisitor)
            .filter(models.RecurringVisitor.otp_code == candidate, models.RecurringVisitor.is_active == True)  # noqa: E712
            .first()
        )
        if clash_v is None and clash_r is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not generate a unique OTP; please retry.")


def visitor_status(v: models.Visitor, now: datetime) -> str:
    if v.cancelled_at is not None:
        return "CANCELLED"
    if v.valid_until < now:
        return "EXPIRED"
    if v.valid_from > now:
        return "SCHEDULED"
    return "ACTIVE"


def visitor_out(v: models.Visitor, viewer: models.User, now: datetime) -> schemas.VisitorOut:
    out = schemas.VisitorOut.model_validate(v)
    out.status = visitor_status(v, now)
    out.has_photo = bool(v.photo_path)
    host = v.host_resident
    if host is not None:
        out.host_name, out.host_apartment = host.name, host.apartment_no
    if viewer.role == models.UserRole.GUARD:
        out.otp_code = MASKED_OTP     # guards verify codes; they do not read them off a list
    return out


def _visitor_for_user(db: Session, visitor_id: int, user: models.User, gate_ok: bool = True) -> models.Visitor:
    v = db.query(models.Visitor).filter(models.Visitor.id == visitor_id).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Visitor not found.")
    if user.role == models.UserRole.RESIDENT:
        if v.host_resident_id != user.resident_id:
            raise HTTPException(status_code=403, detail="You can only access your own visitors.")
    elif user.role == models.UserRole.GUARD and not gate_ok:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return v


# ---------------------------------------------------------------------------
# create / list / cancel
# ---------------------------------------------------------------------------

@router.post("/visitors", response_model=schemas.VisitorOut)
def create_visitor(
    payload: schemas.VisitorCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        if current_user.resident_id != payload.host_resident_id:
            raise HTTPException(status_code=403, detail="Residents can only register visitors for themselves.")
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

    host = db.query(models.Resident).filter(models.Resident.id == payload.host_resident_id).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host resident not found.")

    now = datetime.utcnow()

    valid_from = payload.valid_from or now
    if valid_from < now - timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="The start time has already passed. Leave it empty to start now.")
    valid_from = max(valid_from, now)
    if valid_from > now + MAX_PLAN_AHEAD:
        raise HTTPException(status_code=400, detail="Visits can be planned at most 30 days ahead.")

    if payload.visit_type == models.VisitType.SHORT_TERM:
        valid_until = payload.valid_until or (valid_from + MAX_SHORT_VISIT)
        if valid_until <= valid_from:
            raise HTTPException(status_code=400, detail="The visit must end after it starts.")
        if valid_until - valid_from > MAX_SHORT_VISIT:
            raise HTTPException(status_code=400, detail="A short-term visit can last at most 24 hours. Use a long-term visit for longer.")
    else:  # LONG_TERM
        if payload.valid_until is None or payload.valid_until <= now:
            raise HTTPException(
                status_code=400,
                detail="LONG_TERM visits require a valid_until date/time in the future.",
            )
        valid_until = payload.valid_until
        if valid_until <= valid_from:
            raise HTTPException(status_code=400, detail="The visit must end after it starts.")
        if valid_until - valid_from > MAX_LONG_VISIT:
            raise HTTPException(status_code=400, detail="A visit can last at most 90 days. Ask the admin about a longer arrangement.")

    # The OTP is valid for the whole visit window and can be used for any
    # number of entries (a visitor may step out and come back the same day),
    # so it expires with the visit itself.
    otp_code = _unique_otp(db, now)

    visitor = models.Visitor(
        name=payload.name,
        phone=payload.phone,
        host_resident_id=payload.host_resident_id,
        visit_type=payload.visit_type,
        purpose=payload.purpose,
        valid_from=valid_from,
        valid_until=valid_until,
        # A short-term visitor's vehicle number is information for the guard
        # (compare it at the gate); only long-term visits get a gate credential.
        vehicle_number=payload.vehicle_number,
        otp_code=otp_code,
        otp_expires_at=valid_until,
        otp_verified=False,
        created_by_user_id=current_user.id,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    if payload.visit_type == models.VisitType.LONG_TERM and payload.vehicle_number:
        vehicle = (
            db.query(models.Vehicle)
            .filter(models.Vehicle.vehicle_number == payload.vehicle_number)
            .first()
        )
        if vehicle is None:
            vehicle = models.Vehicle(
                resident_id=None,
                vehicle_number=payload.vehicle_number,
                vehicle_type=payload.vehicle_type or models.VehicleType.CAR,
            )
            db.add(vehicle)
            db.commit()
            db.refresh(vehicle)

        credential = models.VehicleCredential(
            vehicle_id=vehicle.id,
            credential_type=models.CredentialType.RFID,
            credential_value=f"VISITOR-{visitor.id}-{payload.vehicle_number}",
            status=models.CredentialStatus.ACTIVE,
            credential_scope=models.CredentialScope.VISITOR,
            expires_at=valid_until,
            visitor_id=visitor.id,
        )
        db.add(credential)
        db.commit()

    # A guard or admin registering a walk-in for a resident: tell the resident.
    if current_user.role != models.UserRole.RESIDENT:
        notify.notify_resident(
            db, host.id, "VISITOR", f"Visitor registered: {visitor.name}",
            "The gate registered a visitor for you.", "visitor", visitor.id,
        )

    return visitor_out(visitor, current_user, now)


@router.get("/visitors", response_model=List[schemas.VisitorOut])
def list_visitors(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Visitor)
    if current_user.role == models.UserRole.RESIDENT:
        query = query.filter(models.Visitor.host_resident_id == current_user.resident_id)
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    now = datetime.utcnow()
    rows = query.order_by(models.Visitor.created_at.desc(), models.Visitor.id.desc()).limit(500).all()
    return [visitor_out(v, current_user, now) for v in rows]


@router.post("/visitors/{visitor_id}/cancel", response_model=schemas.VisitorOut)
def cancel_visitor(
    visitor_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """The host (or admin) revokes a pass; the OTP stops working immediately."""
    if current_user.role == models.UserRole.GUARD:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    v = _visitor_for_user(db, visitor_id, current_user)
    now = datetime.utcnow()
    if v.cancelled_at is not None:
        raise HTTPException(status_code=400, detail="This visit is already cancelled.")
    if v.valid_until < now:
        raise HTTPException(status_code=400, detail="This visit has already ended.")
    v.cancelled_at = now
    if v.vehicle_credential is not None and v.vehicle_credential.status == models.CredentialStatus.ACTIVE:
        v.vehicle_credential.status = models.CredentialStatus.BLOCKED
    db.commit()
    db.refresh(v)
    return visitor_out(v, current_user, now)


# ---------------------------------------------------------------------------
# gate check: OTP (one-off passes and regular visitors)
# ---------------------------------------------------------------------------

def _recurring_window_message(rec: models.RecurringVisitor, now: datetime) -> Optional[str]:
    """None when the regular visitor may enter right now, else why not."""
    if rec.valid_until is not None and rec.valid_until < now:
        return "Access denied: this regular-visitor pass has ended."
    local = timeutil.to_local(now)
    days = [int(d) for d in rec.days.split(",") if d != ""]
    if local.weekday() not in days:
        return "Access denied: not one of this visitor's usual days."
    minute = timeutil.minutes_of_day(local)
    if minute < rec.start_minute or minute > rec.end_minute:
        return "Access denied: outside this visitor's usual hours."
    return None


@router.post("/verify-otp", response_model=schemas.VerifyOTPResponse)
def verify_otp(
    payload: schemas.VerifyOTPRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    # The OTP is an ENTRY credential only. Leaving the community needs no
    # OTP, and exits are not tracked, so an OUT request is rejected rather
    # than silently logged as an entry.
    if payload.direction == models.Direction.OUT:
        raise HTTPException(
            status_code=400,
            detail="Exit doesn't need an OTP. Visitors can leave freely; only entry is checked.",
        )

    raise_if_locked(otp_by_user, str(current_user.id), "code attempts")

    now = datetime.utcnow()
    code = payload.otp_code
    matches = (
        db.query(models.Visitor)
        .filter(models.Visitor.otp_code == code)
        .order_by(models.Visitor.valid_until.desc())
        .all()
    )

    def deny(message, *, visitor=None, recurring=None):
        utils.log_attempt(
            db, actor=current_user,
            visitor_id=visitor.id if visitor else None,
            recurring_visitor_id=recurring.id if recurring else None,
            entry_method=models.EntryMethod.OTP, credential_value=code,
            gate_name=payload.gate_name, direction=models.Direction.IN, access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED, message=message,
            visitor_name=(visitor.name if visitor else (recurring.name if recurring else None)),
            recurring=recurring is not None,
        )

    # Prefer the holder whose window is open right now; otherwise explain why not.
    live = next((v for v in matches if v.cancelled_at is None and v.valid_from <= now <= v.valid_until), None)
    if live is None and matches:
        upcoming = next((v for v in matches if v.cancelled_at is None and v.valid_from > now), None)
        if upcoming is not None:
            return deny(
                f"Access denied: this visit starts at {timeutil.to_local(upcoming.valid_from).strftime('%d %b %H:%M')}.",
                visitor=upcoming,
            )
        cancelled = next((v for v in matches if v.cancelled_at is not None), None)
        if cancelled is not None and all(v.cancelled_at is not None for v in matches):
            return deny("Access denied: this visit was cancelled by the host.", visitor=cancelled)
        return deny("Access denied: visit window has expired.", visitor=matches[0])

    if live is None:
        rec = (
            db.query(models.RecurringVisitor)
            .filter(models.RecurringVisitor.otp_code == code, models.RecurringVisitor.is_active == True)  # noqa: E712
            .first()
        )
        if rec is None:
            _count, newly_locked = otp_by_user.fail(str(current_user.id))
            if newly_locked:
                notify.notify_admins(
                    db, "SECURITY", "Repeated wrong OTP codes",
                    f"{current_user.name} entered many unrecognised codes and was paused for 2 minutes.",
                )
            return deny("Access denied: OTP not recognized.")
        why = _recurring_window_message(rec, now)
        if why is not None:
            return deny(why, recurring=rec)
        rec.last_entry_at = now
        db.commit()
        host = rec.host_resident
        utils.log_attempt(
            db, actor=current_user, recurring_visitor_id=rec.id,
            entry_method=models.EntryMethod.OTP, credential_value=code,
            gate_name=payload.gate_name, direction=models.Direction.IN, access=models.AccessResult.GRANTED,
        )
        if host is not None:
            notify.notify_resident(db, host.id, "VISITOR", f"{rec.name} arrived", "Your regular visitor entered.", "recurring", rec.id)
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.GRANTED, message="Access granted.",
            visitor_name=rec.name, host_resident_name=host.name if host else None,
            host_apartment=host.apartment_no if host else None, recurring=True,
        )

    visitor = live
    # Granted. otp_verified / otp_verified_at record "has entered" and the
    # most recent entry; the OTP itself stays valid for further entries.
    visitor.otp_verified = True
    visitor.otp_verified_at = now
    db.commit()

    host = visitor.host_resident
    utils.log_attempt(
        db, actor=current_user, visitor_id=visitor.id,
        entry_method=models.EntryMethod.OTP, credential_value=code,
        gate_name=payload.gate_name, direction=models.Direction.IN, access=models.AccessResult.GRANTED,
    )
    if host is not None:
        notify.notify_resident(
            db, host.id, "VISITOR", f"{visitor.name} arrived",
            "Your visitor has entered the society.", "visitor", visitor.id,
        )
    return schemas.VerifyOTPResponse(
        access=models.AccessResult.GRANTED,
        message="Access granted.",
        visitor_name=visitor.name,
        host_resident_name=host.name if host else None,
        host_apartment=host.apartment_no if host else None,
        visitor_id=visitor.id,
        vehicle_number=visitor.vehicle_number,
    )


# ---------------------------------------------------------------------------
# gate photo of a visitor
# ---------------------------------------------------------------------------

@router.post("/visitors/{visitor_id}/photo", response_model=schemas.VisitorOut)
def upload_visitor_photo(
    visitor_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    v = db.query(models.Visitor).filter(models.Visitor.id == visitor_id).first()
    if v is None:
        raise HTTPException(status_code=404, detail="Visitor not found.")
    name = uploads.save_image("visitors", file)
    previous = v.photo_path
    v.photo_path = name
    v.photo_at = datetime.utcnow()
    db.commit()
    db.refresh(v)
    uploads.remove_image("visitors", previous)
    notify.notify_resident(
        db, v.host_resident_id, "VISITOR", f"Photo of {v.name} taken at the gate",
        "You can view it under Visitors.", "visitor", v.id,
    )
    return visitor_out(v, current_user, datetime.utcnow())


@router.get("/visitors/{visitor_id}/photo")
def get_visitor_photo(
    visitor_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    v = _visitor_for_user(db, visitor_id, current_user)
    path = uploads.image_path("visitors", v.photo_path)
    return FileResponse(
        path, media_type=uploads.MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


# ---------------------------------------------------------------------------
# regular (recurring) visitors
# ---------------------------------------------------------------------------

def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _rec_out(rec: models.RecurringVisitor, viewer: models.User) -> schemas.RecurringOut:
    return schemas.RecurringOut(
        id=rec.id, host_resident_id=rec.host_resident_id,
        host_name=rec.host_resident.name if rec.host_resident else None,
        name=rec.name, phone=rec.phone, purpose=rec.purpose,
        days=[int(d) for d in rec.days.split(",") if d != ""],
        start_time=_hhmm(rec.start_minute), end_time=_hhmm(rec.end_minute),
        valid_until=rec.valid_until,
        otp_code=MASKED_OTP if viewer.role == models.UserRole.GUARD else rec.otp_code,
        is_active=rec.is_active, created_at=rec.created_at, last_entry_at=rec.last_entry_at,
    )


MAX_RECURRING_PER_FLAT = 10


@router.post("/recurring-visitors", response_model=schemas.RecurringOut)
def create_recurring(
    payload: schemas.RecurringCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        host_id = current_user.resident_id
    elif current_user.role == models.UserRole.ADMIN:
        host_id = payload.host_resident_id
        if host_id is None:
            raise HTTPException(status_code=400, detail="Choose the host resident.")
    else:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    if db.query(models.Resident).filter(models.Resident.id == host_id).first() is None:
        raise HTTPException(status_code=404, detail="Host resident not found.")

    now = datetime.utcnow()
    if payload.valid_until is not None and payload.valid_until <= now:
        raise HTTPException(status_code=400, detail="The end date must be in the future.")
    active = db.query(models.RecurringVisitor).filter(
        models.RecurringVisitor.host_resident_id == host_id, models.RecurringVisitor.is_active == True).count()  # noqa: E712
    if active >= MAX_RECURRING_PER_FLAT:
        raise HTTPException(status_code=400, detail="This flat already has the maximum number of regular visitors.")

    rec = models.RecurringVisitor(
        host_resident_id=host_id, name=payload.name, phone=payload.phone, purpose=payload.purpose,
        days=",".join(str(d) for d in payload.days),
        start_minute=int(payload.start_time[:2]) * 60 + int(payload.start_time[3:]),
        end_minute=int(payload.end_time[:2]) * 60 + int(payload.end_time[3:]),
        valid_until=payload.valid_until, otp_code=_unique_otp(db, now),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _rec_out(rec, current_user)


@router.get("/recurring-visitors", response_model=List[schemas.RecurringOut])
def list_recurring(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.RecurringVisitor)
    if current_user.role == models.UserRole.RESIDENT:
        query = query.filter(models.RecurringVisitor.host_resident_id == current_user.resident_id)
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    rows = query.order_by(models.RecurringVisitor.is_active.desc(), models.RecurringVisitor.created_at.desc()).all()
    return [_rec_out(r, current_user) for r in rows]


@router.post("/recurring-visitors/{rec_id}/active", response_model=schemas.RecurringOut)
def set_recurring_active(
    rec_id: int,
    payload: schemas.ActiveUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Pause, resume or end a regular visitor (host or admin)."""
    if current_user.role == models.UserRole.GUARD:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    rec = db.query(models.RecurringVisitor).filter(models.RecurringVisitor.id == rec_id).first()
    if rec is None:
        raise HTTPException(status_code=404, detail="Regular visitor not found.")
    if current_user.role == models.UserRole.RESIDENT and rec.host_resident_id != current_user.resident_id:
        raise HTTPException(status_code=403, detail="You can only manage your own regular visitors.")
    if payload.is_active and not rec.is_active:
        # Re-using the code is only safe if nobody else holds it meanwhile.
        clash = db.query(models.Visitor).filter(
            models.Visitor.otp_code == rec.otp_code, models.Visitor.valid_until >= datetime.utcnow(),
            models.Visitor.cancelled_at.is_(None)).first()
        if clash is not None:
            rec.otp_code = _unique_otp(db, datetime.utcnow())
    rec.is_active = payload.is_active
    db.commit()
    db.refresh(rec)
    return _rec_out(rec, current_user)


# ---------------------------------------------------------------------------
# the gate's "expected today" list
# ---------------------------------------------------------------------------

@router.get("/gate/expected")
def expected_today(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    """Who the gate should expect for the rest of today (society-local day)."""
    now = datetime.utcnow()
    start, end = timeutil.local_day_bounds_utc(timeutil.local_today())
    local = timeutil.to_local(now)
    minute = timeutil.minutes_of_day(local)

    visitors = (
        db.query(models.Visitor)
        .filter(models.Visitor.cancelled_at.is_(None), models.Visitor.valid_from < end,
                models.Visitor.valid_until >= now)
        .order_by(models.Visitor.valid_from).limit(300).all()
    )
    rec_rows = (
        db.query(models.RecurringVisitor)
        .filter(models.RecurringVisitor.is_active == True)  # noqa: E712
        .all()
    )
    from .deliveries import _expire_stale   # local import: deliveries.py does not import this module
    _expire_stale(db, now)
    deliveries = (
        db.query(models.Delivery)
        .filter(models.Delivery.status.in_([models.DeliveryStatus.EXPECTED, models.DeliveryStatus.APPROVED]),
                models.Delivery.host_resident_id.isnot(None))
        .order_by(models.Delivery.requested_at).limit(100).all()
    )

    def host_of(r):
        return {"host_name": r.name, "host_apartment": r.apartment_no} if r is not None else {}

    out_visitors = []
    for v in visitors:
        item = {
            "id": v.id, "name": v.name, "purpose": v.purpose, "vehicle_number": v.vehicle_number,
            "valid_from": v.valid_from, "valid_until": v.valid_until,
            "visit_type": v.visit_type.value, "status": visitor_status(v, now),
            "entered_today": bool(v.otp_verified_at and v.otp_verified_at >= start),
            "has_photo": bool(v.photo_path),
        }
        item.update(host_of(v.host_resident))
        out_visitors.append(item)

    out_regular = []
    for r in rec_rows:
        days = [int(d) for d in r.days.split(",") if d != ""]
        if local.weekday() not in days or (r.valid_until is not None and r.valid_until < now):
            continue
        if r.end_minute < minute:
            continue   # today's window is over
        item = {
            "id": r.id, "name": r.name, "purpose": r.purpose,
            "start_time": _hhmm(r.start_minute), "end_time": _hhmm(r.end_minute),
            "entered_today": bool(r.last_entry_at and r.last_entry_at >= start),
        }
        item.update(host_of(r.host_resident))
        out_regular.append(item)

    out_deliveries = []
    for d in deliveries:
        item = {
            "id": d.id, "platform": d.platform, "status": d.status.value,
            "expected_from": d.expected_from, "expected_until": d.expected_until,
            "leave_at_gate": d.leave_at_gate,
        }
        item.update(host_of(d.host_resident))
        out_deliveries.append(item)

    return {"visitors": out_visitors, "regular_visitors": out_regular, "deliveries": out_deliveries}
