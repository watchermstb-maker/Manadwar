from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Visitors / OTP Entry"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)


def _unique_otp(db: Session, now: datetime) -> str:
    for _ in range(50):
        candidate = utils.generate_otp()
        clash = (
            db.query(models.Visitor)
            .filter(models.Visitor.otp_code == candidate, models.Visitor.valid_until >= now)
            .first()
        )
        if clash is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not generate a unique OTP; please retry.")


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

    if payload.visit_type == models.VisitType.SHORT_TERM:
        if payload.vehicle_number:
            raise HTTPException(
                status_code=400,
                detail="SHORT_TERM visits are walk-in only and cannot register a vehicle.",
            )
        valid_until = now + timedelta(hours=24)
    else:  # LONG_TERM
        if payload.valid_until is None or payload.valid_until <= now:
            raise HTTPException(
                status_code=400,
                detail="LONG_TERM visits require a valid_until date/time in the future.",
            )
        valid_until = payload.valid_until

    # The OTP is valid for the whole visit window and can be used for any
    # number of entries (a visitor may step out and come back the same
    # day), so it expires with the visit itself. Because codes now live up
    # to 24h+, make sure no other still-valid visitor already holds this one.
    otp_code = _unique_otp(db, now)
    otp_expires_at = valid_until

    visitor = models.Visitor(
        name=payload.name,
        phone=payload.phone,
        host_resident_id=payload.host_resident_id,
        visit_type=payload.visit_type,
        purpose=payload.purpose,
        valid_from=now,
        valid_until=valid_until,
        vehicle_number=payload.vehicle_number if payload.visit_type == models.VisitType.LONG_TERM else None,
        otp_code=otp_code,
        otp_expires_at=otp_expires_at,
        otp_verified=False,
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

    return visitor


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

    now = datetime.utcnow()
    matches = (
        db.query(models.Visitor)
        .filter(models.Visitor.otp_code == payload.otp_code)
        .order_by(models.Visitor.valid_until.desc())
        .all()
    )
    # Prefer a still-valid holder of this code; fall back to an expired one
    # only to give a more helpful message than "not recognized".
    visitor = next((v for v in matches if v.valid_until >= now), matches[0] if matches else None)

    if visitor is None:
        utils.log_attempt(
            db,
            entry_method=models.EntryMethod.OTP,
            credential_value=payload.otp_code,
            gate_name=payload.gate_name,
            direction=models.Direction.IN,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: OTP not recognized.",
        )

    if visitor.valid_until < now:
        utils.log_attempt(
            db,
            visitor_id=visitor.id,
            entry_method=models.EntryMethod.OTP,
            credential_value=payload.otp_code,
            gate_name=payload.gate_name,
            direction=models.Direction.IN,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: visit window has expired.",
            visitor_name=visitor.name,
        )

    # Granted. otp_verified / otp_verified_at record "has entered" and the
    # most recent entry; the OTP itself stays valid for further entries.
    visitor.otp_verified = True
    visitor.otp_verified_at = now
    db.commit()

    host = db.query(models.Resident).filter(models.Resident.id == visitor.host_resident_id).first()

    utils.log_attempt(
        db,
        visitor_id=visitor.id,
        entry_method=models.EntryMethod.OTP,
        credential_value=payload.otp_code,
        gate_name=payload.gate_name,
        direction=models.Direction.IN,
        access=models.AccessResult.GRANTED,
    )
    return schemas.VerifyOTPResponse(
        access=models.AccessResult.GRANTED,
        message="Access granted.",
        visitor_name=visitor.name,
        host_resident_name=host.name if host else None,
    )


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
    return query.order_by(models.Visitor.created_at.desc()).all()
