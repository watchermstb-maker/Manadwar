from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..database import get_db

router = APIRouter(tags=["RFID / Vehicle Access"])


@router.post("/verify-rfid", response_model=schemas.VerifyRFIDResponse)
def verify_rfid(payload: schemas.VerifyRFIDRequest, db: Session = Depends(get_db)):
    credential = (
        db.query(models.VehicleCredential)
        .filter(models.VehicleCredential.credential_value == payload.credential_value)
        .first()
    )

    if credential is None:
        utils.log_attempt(
            db,
            entry_method=models.EntryMethod.RFID,
            credential_value=payload.credential_value,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyRFIDResponse(
            access=models.AccessResult.DENIED,
            message="Access denied: credential not registered.",
        )

    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == credential.vehicle_id).first()
    resident = None
    if vehicle is not None and vehicle.resident_id is not None:
        resident = db.query(models.Resident).filter(models.Resident.id == vehicle.resident_id).first()

    if credential.status != models.CredentialStatus.ACTIVE:
        utils.log_attempt(
            db,
            vehicle_id=vehicle.id if vehicle else None,
            credential_id=credential.id,
            entry_method=models.EntryMethod.RFID,
            credential_value=payload.credential_value,
            gate_name=payload.gate_name,
            direction=payload.direction,
            access=models.AccessResult.DENIED,
        )
        return schemas.VerifyRFIDResponse(
            access=models.AccessResult.DENIED,
            message=f"Access denied: credential is {credential.status.value.lower()}.",
            vehicle_number=vehicle.vehicle_number if vehicle else None,
        )

    utils.log_attempt(
        db,
        vehicle_id=vehicle.id if vehicle else None,
        credential_id=credential.id,
        entry_method=models.EntryMethod.RFID,
        credential_value=payload.credential_value,
        gate_name=payload.gate_name,
        direction=payload.direction,
        access=models.AccessResult.GRANTED,
    )
    return schemas.VerifyRFIDResponse(
        access=models.AccessResult.GRANTED,
        message="Access granted.",
        vehicle_number=vehicle.vehicle_number if vehicle else None,
        resident_name=resident.name if resident else None,
    )


@router.get("/entry-logs", response_model=List[schemas.EntryLogOut])
def list_entry_logs(db: Session = Depends(get_db)):
    return db.query(models.EntryLog).order_by(models.EntryLog.timestamp.desc()).all()


@router.get("/vehicles", response_model=List[schemas.VehicleOut])
def list_vehicles(db: Session = Depends(get_db)):
    return db.query(models.Vehicle).all()


@router.get("/credentials", response_model=List[schemas.CredentialOut])
def list_credentials(db: Session = Depends(get_db)):
    return db.query(models.VehicleCredential).all()


@router.get("/residents", response_model=List[schemas.ResidentOut])
def list_residents(db: Session = Depends(get_db)):
    return db.query(models.Resident).all()
