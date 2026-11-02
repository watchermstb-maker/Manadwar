import csv
import io
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import logview, models, schemas, timeutil, utils
from ..audit import audit
from ..auth import require_roles
from ..database import get_db

router = APIRouter(tags=["RFID / Vehicle Access"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)


@router.post("/verify-rfid", response_model=schemas.VerifyRFIDResponse)
def verify_rfid(
    payload: schemas.VerifyRFIDRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    credential = (
        db.query(models.VehicleCredential)
        .filter(models.VehicleCredential.credential_value == payload.credential_value)
        .first()
    )

    if credential is None:
        utils.log_attempt(
            db,
            actor=current_user,
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

    # Opportunistic expiry: if this credential has a non-null expires_at
    # that has passed, flip it to EXPIRED right now (no separate scheduler
    # job exists in this prototype -- status is corrected lazily, at the
    # moment it's actually checked).
    if (
        credential.status == models.CredentialStatus.ACTIVE
        and credential.expires_at is not None
        and credential.expires_at < datetime.utcnow()
    ):
        credential.status = models.CredentialStatus.EXPIRED
        db.commit()

    vehicle = db.query(models.Vehicle).filter(models.Vehicle.id == credential.vehicle_id).first()
    resident = None
    if vehicle is not None and vehicle.resident_id is not None:
        resident = db.query(models.Resident).filter(models.Resident.id == vehicle.resident_id).first()

    if credential.status == models.CredentialStatus.BLOCKED:
        utils.log_attempt(
            db,
            actor=current_user,
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
            message="Access denied: credential is blocked.",
            vehicle_number=vehicle.vehicle_number if vehicle else None,
        )

    if credential.status == models.CredentialStatus.EXPIRED:
        utils.log_attempt(
            db,
            actor=current_user,
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
            message="Access denied: credential has expired.",
            vehicle_number=vehicle.vehicle_number if vehicle else None,
        )

    # ACTIVE -> grant.
    utils.log_attempt(
        db,
        actor=current_user,
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


def _log_query(db, q, method, access, direction, date_from, date_to):
    EL = models.EntryLog
    query = (
        db.query(EL)
        .outerjoin(models.Vehicle, EL.vehicle_id == models.Vehicle.id)
        .outerjoin(models.Visitor, EL.visitor_id == models.Visitor.id)
        .outerjoin(models.Staff, EL.staff_id == models.Staff.id)
        .outerjoin(models.Delivery, EL.delivery_id == models.Delivery.id)
        .outerjoin(models.RecurringVisitor, EL.recurring_visitor_id == models.RecurringVisitor.id)
    )
    if method is not None:
        query = query.filter(EL.entry_method == method)
    if access is not None:
        query = query.filter(EL.access == access)
    if direction is not None:
        query = query.filter(EL.direction == direction)
    if date_from is not None:
        query = query.filter(EL.timestamp >= timeutil.local_day_bounds_utc(date_from)[0])
    if date_to is not None:
        query = query.filter(EL.timestamp < timeutil.local_day_bounds_utc(date_to)[1])
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(
            func.lower(EL.credential_value).like(like),
            func.lower(func.coalesce(models.Vehicle.vehicle_number, "")).like(like),
            func.lower(func.coalesce(models.Visitor.name, "")).like(like),
            func.lower(func.coalesce(models.Staff.name, "")).like(like),
            func.lower(func.coalesce(models.Delivery.platform, "")).like(like),
            func.lower(func.coalesce(models.Delivery.courier_name, "")).like(like),
            func.lower(func.coalesce(models.RecurringVisitor.name, "")).like(like),
        ))
    return query


@router.get("/entry-logs", response_model=List[schemas.EntryLogOut])
def list_entry_logs(
    response: Response,
    q: Optional[str] = Query(None, max_length=80),
    method: Optional[models.EntryMethod] = None,
    access: Optional[models.AccessResult] = None,
    direction: Optional[models.Direction] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    """Newest first. The total number of matching rows is in the X-Total-Count header."""
    query = _log_query(db, q, method, access, direction, date_from, date_to)
    response.headers["X-Total-Count"] = str(query.count())
    rows = (
        query.options(*logview.LOG_LOAD)
        .order_by(models.EntryLog.timestamp.desc(), models.EntryLog.id.desc())
        .offset(offset).limit(limit).all()
    )
    return [logview.log_dict(r) for r in rows]


@router.get("/entry-logs/export.csv")
def export_entry_logs(
    q: Optional[str] = Query(None, max_length=80),
    method: Optional[models.EntryMethod] = None,
    access: Optional[models.AccessResult] = None,
    direction: Optional[models.Direction] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_roles(models.UserRole.ADMIN)),
):
    rows = (
        _log_query(db, q, method, access, direction, date_from, date_to)
        .options(*logview.LOG_LOAD)
        .order_by(models.EntryLog.timestamp.desc(), models.EntryLog.id.desc())
        .limit(20000).all()
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["time (society local)", "method", "direction", "result", "who/what", "resident / flat",
                     "credential", "gate", "done by"])
    for r in rows:
        d = logview.log_dict(r)
        writer.writerow([
            _csv_safe(logview.local_str(r.timestamp)), r.entry_method.value, r.direction.value, r.access.value,
            _csv_safe(d["subject"] or ""), _csv_safe(d["resident_label"] or ""), _csv_safe(r.credential_value),
            _csv_safe(r.gate_name), _csv_safe(d["actor_name"] or ""),
        ])
    audit(db, admin, "entry_logs.export", "entry_log", None, f"{len(rows)} rows")
    return Response(
        content=out.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="manadwar-entry-log.csv"'},
    )


def _csv_safe(value: str) -> str:
    """Stop a spreadsheet from running a typed value as a formula."""
    value = str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/vehicles", response_model=List[schemas.VehicleOut])
def list_vehicles(db: Session = Depends(get_db), current_user: models.User = Depends(_gate_staff)):
    return db.query(models.Vehicle).all()


@router.get("/credentials", response_model=List[schemas.CredentialOut])
def list_credentials(db: Session = Depends(get_db), current_user: models.User = Depends(_gate_staff)):
    return db.query(models.VehicleCredential).all()


@router.get("/residents", response_model=List[schemas.ResidentOut])
def list_residents(db: Session = Depends(get_db), current_user: models.User = Depends(_gate_staff)):
    residents = db.query(models.Resident).order_by(models.Resident.apartment_no, models.Resident.name).all()
    if current_user.role != models.UserRole.ADMIN:
        # Guards need a name and a flat to find who a visitor is for, not everyone's phone number.
        return [schemas.ResidentOut(id=r.id, name=r.name, apartment_no=r.apartment_no, phone=None) for r in residents]
    return residents
