import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..database import get_db

router = APIRouter(tags=["General Staff"])


def _generate_credential_value(db: Session) -> str:
    """Generate a unique staff ID-card code, e.g. 'STAFF-A1B2C3D4'."""
    for _ in range(10):
        candidate = "STAFF-" + secrets.token_hex(4).upper()
        exists = db.query(models.Staff).filter(models.Staff.credential_value == candidate).first()
        if exists is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not generate a unique staff credential; please retry.")


@router.post("/staff", response_model=schemas.StaffOut)
def register_staff(payload: schemas.StaffCreate, db: Session = Depends(get_db)):
    if payload.employed_by_resident_id is not None:
        resident = (
            db.query(models.Resident)
            .filter(models.Resident.id == payload.employed_by_resident_id)
            .first()
        )
        if resident is None:
            raise HTTPException(status_code=404, detail="Employing resident not found.")

    digits = "".join(ch for ch in payload.aadhaar_number if ch.isdigit())
    if len(digits) != 12:
        raise HTTPException(status_code=400, detail="aadhaar_number must be exactly 12 digits.")

    aadhaar_hash, aadhaar_last4 = utils.hash_aadhaar(digits)

    existing = db.query(models.Staff).filter(models.Staff.aadhaar_hash == aadhaar_hash).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="This Aadhaar number is already registered as staff.")

    staff = models.Staff(
        name=payload.name,
        phone=payload.phone,
        role=payload.role,
        employed_by_resident_id=payload.employed_by_resident_id,
        aadhaar_hash=aadhaar_hash,
        aadhaar_last4=aadhaar_last4,
        credential_value=_generate_credential_value(db),
        status=models.StaffStatus.ACTIVE,
        expires_at=payload.expires_at,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


@router.post("/verify-staff", response_model=schemas.VerifyStaffResponse)
def verify_staff(payload: schemas.VerifyStaffRequest, db: Session = Depends(get_db)):
    staff = (
        db.query(models.Staff)
        .filter(models.Staff.credential_value == payload.credential_value)
        .first()
    )

    if staff is None:
        utils.log_attempt(
            db,
            entry_method=models.EntryMethod.STAFF,
            credential_value=payload.credential_value,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyStaffResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: staff credential not registered.",
        )

    # Opportunistic expiry: same lazy pattern used for vehicle credentials
    # (rfid.py) and maintenance bills (maintenance.py) -- no scheduler job
    # exists in this prototype, so status is corrected at the moment it's
    # actually checked.
    if (
        staff.status == models.StaffStatus.ACTIVE
        and staff.expires_at is not None
        and staff.expires_at < datetime.utcnow()
    ):
        staff.status = models.StaffStatus.EXPIRED
        db.commit()

    employer = None
    if staff.employed_by_resident_id is not None:
        employer = (
            db.query(models.Resident)
            .filter(models.Resident.id == staff.employed_by_resident_id)
            .first()
        )

    if staff.status == models.StaffStatus.BLOCKED:
        utils.log_attempt(
            db,
            staff_id=staff.id,
            entry_method=models.EntryMethod.STAFF,
            credential_value=payload.credential_value,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyStaffResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: staff credential is blocked.",
            staff_name=staff.name,
            role=staff.role,
        )

    if staff.status == models.StaffStatus.EXPIRED:
        utils.log_attempt(
            db,
            staff_id=staff.id,
            entry_method=models.EntryMethod.STAFF,
            credential_value=payload.credential_value,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyStaffResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: staff credential has expired.",
            staff_name=staff.name,
            role=staff.role,
        )

    # ACTIVE -> grant.
    utils.log_attempt(
        db,
        staff_id=staff.id,
        entry_method=models.EntryMethod.STAFF,
        credential_value=payload.credential_value,
        gate_name=payload.gate_name,
        direction=payload.direction,
        access=models.AccessResult.GRANTED,
    )
    return schemas.VerifyStaffResponse(
        access=models.AccessResult.GRANTED,
        message="Access granted.",
        staff_name=staff.name,
        role=staff.role,
        employer_name=employer.name if employer else None,
    )


@router.post("/staff/{staff_id}/status", response_model=schemas.StaffOut)
def update_staff_status(
    staff_id: int, payload: schemas.StaffStatusUpdate, db: Session = Depends(get_db)
):
    staff = db.query(models.Staff).filter(models.Staff.id == staff_id).first()
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found.")

    staff.status = payload.status
    db.commit()
    db.refresh(staff)
    return staff


@router.get("/staff", response_model=List[schemas.StaffOut])
def list_staff(
    role: Optional[models.StaffRole] = None,
    employed_by_resident_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Staff)
    if role is not None:
        query = query.filter(models.Staff.role == role)
    if employed_by_resident_id is not None:
        query = query.filter(models.Staff.employed_by_resident_id == employed_by_resident_id)
    return query.order_by(models.Staff.created_at.desc()).all()
