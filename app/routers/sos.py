"""SOS: a resident raises an emergency alert; the gate and admin respond."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, notify, schemas
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["SOS"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)
_resident_only = require_roles(models.UserRole.RESIDENT)

MAX_PER_HOUR = 5


def _out(db: Session, a: models.SosAlert, viewer: models.User) -> schemas.SosOut:
    r = a.resident
    by = None
    if a.acknowledged_by_user_id:
        u = db.query(models.User).filter(models.User.id == a.acknowledged_by_user_id).first()
        by = u.name if u else None
    return schemas.SosOut(
        id=a.id, resident_id=a.resident_id, resident_name=r.name if r else None,
        apartment_no=r.apartment_no if r else None,
        phone=(r.phone if r and viewer.role != models.UserRole.RESIDENT else None),
        kind=a.kind, message=a.message, status=a.status, created_at=a.created_at,
        acknowledged_at=a.acknowledged_at, acknowledged_by=by, resolved_at=a.resolved_at, note=a.note,
    )


@router.post("/sos", response_model=schemas.SosOut)
def raise_sos(
    payload: schemas.SosCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(_resident_only),
):
    now = datetime.utcnow()
    open_alert = db.query(models.SosAlert).filter(
        models.SosAlert.resident_id == user.resident_id, models.SosAlert.status != models.SosStatus.RESOLVED).first()
    if open_alert is not None:
        raise HTTPException(status_code=409, detail="You already have an alert open. The gate has been told.")
    recent = db.query(models.SosAlert).filter(
        models.SosAlert.resident_id == user.resident_id, models.SosAlert.created_at >= now - timedelta(hours=1)).count()
    if recent >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many alerts in the last hour. Call the gate directly.")

    alert = models.SosAlert(resident_id=user.resident_id, user_id=user.id, kind=payload.kind, message=payload.message)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    r = alert.resident
    notify.notify_gate(
        db, "SOS", f"SOS {payload.kind}: Flat {r.apartment_no}",
        f"{r.name}" + (f" — {payload.message}" if payload.message else ""), "sos", alert.id,
    )
    return _out(db, alert, user)


@router.get("/sos", response_model=List[schemas.SosOut])
def list_sos(
    active_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = db.query(models.SosAlert)
    if user.role == models.UserRole.RESIDENT:
        query = query.filter(models.SosAlert.resident_id == user.resident_id)
    if active_only:
        query = query.filter(models.SosAlert.status != models.SosStatus.RESOLVED)
    rows = query.order_by(models.SosAlert.created_at.desc(), models.SosAlert.id.desc()).limit(limit).all()
    return [_out(db, a, user) for a in rows]


def _get(db: Session, alert_id: int) -> models.SosAlert:
    a = db.query(models.SosAlert).filter(models.SosAlert.id == alert_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return a


@router.post("/sos/{alert_id}/ack", response_model=schemas.SosOut)
def acknowledge(alert_id: int, db: Session = Depends(get_db), user: models.User = Depends(_gate_staff)):
    a = _get(db, alert_id)
    if a.status != models.SosStatus.ACTIVE:
        raise HTTPException(status_code=400, detail=f"This alert is already {a.status.value.lower()}.")
    a.status = models.SosStatus.ACKNOWLEDGED
    a.acknowledged_by_user_id = user.id
    a.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(a)
    notify.notify_resident(db, a.resident_id, "SOS", "Help is on the way", f"{user.name} at the gate has seen your alert.", "sos", a.id)
    return _out(db, a, user)


@router.post("/sos/{alert_id}/resolve", response_model=schemas.SosOut)
def resolve(
    alert_id: int,
    payload: schemas.SosResolve = schemas.SosResolve(),
    db: Session = Depends(get_db),
    user: models.User = Depends(_gate_staff),
):
    a = _get(db, alert_id)
    if a.status == models.SosStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="This alert is already resolved.")
    now = datetime.utcnow()
    if a.acknowledged_at is None:
        a.acknowledged_by_user_id, a.acknowledged_at = user.id, now
    a.status = models.SosStatus.RESOLVED
    a.resolved_by_user_id, a.resolved_at, a.note = user.id, now, payload.note
    db.commit()
    db.refresh(a)
    notify.notify_resident(db, a.resident_id, "SOS", "Your alert was closed", payload.note, "sos", a.id)
    return _out(db, a, user)
