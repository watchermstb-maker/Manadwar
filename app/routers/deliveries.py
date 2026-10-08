from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, utils
from ..database import get_db

router = APIRouter(tags=["Deliveries"])


@router.post("/deliveries", response_model=schemas.DeliveryOut)
def create_delivery(payload: schemas.DeliveryCreate, db: Session = Depends(get_db)):
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
    delivery_id: int, payload: schemas.DeliveryDecision, db: Session = Depends(get_db)
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
def list_deliveries(db: Session = Depends(get_db)):
    return db.query(models.Delivery).order_by(models.Delivery.requested_at.desc()).all()
