from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Deliveries"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)


@router.post("/deliveries", response_model=schemas.DeliveryOut)
def create_delivery(
    payload: schemas.DeliveryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        if current_user.resident_id != payload.host_resident_id:
            raise HTTPException(status_code=403, detail="Residents can only request deliveries for themselves.")
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

    host = db.query(models.Resident).filter(models.Resident.id == payload.host_resident_id).first()
    if host is None:
        raise HTTPException(status_code=404, detail="Host resident not found.")

    delivery = models.Delivery(
        courier_name=payload.courier_name,
        courier_phone=payload.courier_phone,
        platform=payload.platform,
        host_resident_id=payload.host_resident_id,
        purpose=payload.purpose,
        approval_mode=payload.approval_mode,
        status=models.DeliveryStatus.PENDING,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    if payload.approval_mode == models.ApprovalMode.AUTO:
        delivery.status = models.DeliveryStatus.APPROVED
        delivery.decided_at = datetime.utcnow()
        db.commit()
        utils.log_attempt(
            db,
            delivery_id=delivery.id,
            entry_method=models.EntryMethod.DELIVERY,
            credential_value=payload.courier_name,
            gate_name="MAIN_GATE",
            direction=models.Direction.IN,
            access=models.AccessResult.GRANTED,
        )

    return delivery


@router.post("/deliveries/{delivery_id}/decision", response_model=schemas.DeliveryOut)
def decide_delivery(
    delivery_id: int,
    payload: schemas.DeliveryDecision,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery request not found.")

    if delivery.approval_mode != models.ApprovalMode.MANUAL:
        raise HTTPException(
            status_code=400,
            detail="Only MANUAL-approval delivery requests can be decided on explicitly.",
        )

    if delivery.status != models.DeliveryStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"This delivery request has already been decided ({delivery.status.value}).",
        )

    delivery.status = models.DeliveryStatus.APPROVED if payload.approve else models.DeliveryStatus.DENIED
    delivery.decided_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)

    utils.log_attempt(
        db,
        delivery_id=delivery.id,
        entry_method=models.EntryMethod.DELIVERY,
        credential_value=delivery.courier_name,
        gate_name=payload.gate_name,
        direction=models.Direction.IN,
        access=models.AccessResult.GRANTED if payload.approve else models.AccessResult.DENIED,
    )

    return delivery


@router.get("/deliveries", response_model=List[schemas.DeliveryOut])
def list_deliveries(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Delivery)
    if current_user.role == models.UserRole.RESIDENT:
        query = query.filter(models.Delivery.host_resident_id == current_user.resident_id)
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return query.order_by(models.Delivery.requested_at.desc()).all()
