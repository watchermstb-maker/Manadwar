from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..database import get_db

router = APIRouter(tags=["Visitors / OTP Entry"])


@router.post("/visitors", response_model=schemas.VisitorOut)
def create_visitor(payload: schemas.VisitorCreate, db: Session = Depends(get_db)):
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

    otp_code = utils.generate_otp()
    otp_expires_at = now + timedelta(minutes=15)

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
def verify_otp(payload: schemas.VerifyOTPRequest, db: Session = Depends(get_db)):
    visitor = (
        db.query(models.Visitor)
        .filter(models.Visitor.otp_code == payload.otp_code)
        .first()
    )

    if visitor is None:
        utils.log_attempt(
            db,
            entry_method=models.EntryMethod.OTP,
            credential_value=payload.otp_code,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: OTP not recognized.",
        )

    now = datetime.utcnow()

    if visitor.otp_verified:
        utils.log_attempt(
            db,
            visitor_id=visitor.id,
            entry_method=models.EntryMethod.OTP,
            credential_value=payload.otp_code,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: OTP already used.",
            visitor_name=visitor.name,
        )

    if visitor.otp_expires_at < now or visitor.valid_until < now:
        utils.log_attempt(
            db,
            visitor_id=visitor.id,
            entry_method=models.EntryMethod.OTP,
            credential_value=payload.otp_code,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyOTPResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: OTP or visit window has expired.",
            visitor_name=visitor.name,
        )

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
        direction=payload.direction,
        access=models.AccessResult.GRANTED,
    )
    return schemas.VerifyOTPResponse(
        access=models.AccessResult.GRANTED,
        message="Access granted.",
        visitor_name=visitor.name,
        host_resident_name=host.name if host else None,
    )


@router.get("/visitors", response_model=List[schemas.VisitorOut])
def list_visitors(db: Session = Depends(get_db)):
    return db.query(models.Visitor).order_by(models.Visitor.created_at.desc()).all()
