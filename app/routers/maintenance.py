from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(tags=["Maintenance: Bills & Complaints"])


def _validate_billing_month(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="billing_month must be in 'YYYY-MM' format.")


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

@router.post("/maintenance/bills", response_model=schemas.MaintenanceBillOut)
def create_bill(payload: schemas.MaintenanceBillCreate, db: Session = Depends(get_db)):
    resident = db.query(models.Resident).filter(models.Resident.id == payload.resident_id).first()
    if resident is None:
        raise HTTPException(status_code=404, detail="Resident not found.")

    _validate_billing_month(payload.billing_month)

    bill = models.MaintenanceBill(
        resident_id=payload.resident_id,
        billing_month=payload.billing_month,
        amount_due=payload.amount_due,
        due_date=payload.due_date,
        status=models.BillStatus.PENDING,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill


@router.post("/maintenance/bills/{bill_id}/pay", response_model=schemas.MaintenanceBillOut)
def pay_bill(bill_id: int, payload: schemas.MaintenanceBillPay, db: Session = Depends(get_db)):
    bill = db.query(models.MaintenanceBill).filter(models.MaintenanceBill.id == bill_id).first()
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found.")

    if bill.status == models.BillStatus.PAID:
        raise HTTPException(status_code=400, detail="This bill has already been paid.")

    bill.status = models.BillStatus.PAID
    bill.paid_at = datetime.utcnow()
    bill.payment_reference = payload.payment_reference
    db.commit()
    db.refresh(bill)
    return bill


@router.get("/maintenance/bills", response_model=List[schemas.MaintenanceBillOut])
def list_bills(resident_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.MaintenanceBill)
    if resident_id is not None:
        query = query.filter(models.MaintenanceBill.resident_id == resident_id)
    bills = query.order_by(models.MaintenanceBill.due_date.desc()).all()

    # Opportunistic expiry: flip any still-PENDING bill whose due_date has
    # passed to OVERDUE at read-time (no scheduler/cron in this prototype).
    now = datetime.utcnow()
    changed = False
    for bill in bills:
        if bill.status == models.BillStatus.PENDING and bill.due_date < now:
            bill.status = models.BillStatus.OVERDUE
            changed = True
    if changed:
        db.commit()

    return bills


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

@router.post("/complaints", response_model=schemas.ComplaintOut)
def create_complaint(payload: schemas.ComplaintCreate, db: Session = Depends(get_db)):
    resident = db.query(models.Resident).filter(models.Resident.id == payload.resident_id).first()
    if resident is None:
        raise HTTPException(status_code=404, detail="Resident not found.")

    complaint = models.Complaint(
        resident_id=payload.resident_id,
        category=payload.category,
        description=payload.description,
        status=models.ComplaintStatus.OPEN,
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return complaint


@router.post("/complaints/{complaint_id}/status", response_model=schemas.ComplaintOut)
def update_complaint_status(
    complaint_id: int, payload: schemas.ComplaintStatusUpdate, db: Session = Depends(get_db)
):
    complaint = db.query(models.Complaint).filter(models.Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")

    complaint.status = payload.status
    if payload.resolution_notes is not None:
        complaint.resolution_notes = payload.resolution_notes
    if payload.status == models.ComplaintStatus.RESOLVED:
        complaint.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(complaint)
    return complaint


@router.get("/complaints", response_model=List[schemas.ComplaintOut])
def list_complaints(
    resident_id: Optional[int] = None,
    status: Optional[models.ComplaintStatus] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Complaint)
    if resident_id is not None:
        query = query.filter(models.Complaint.resident_id == resident_id)
    if status is not None:
        query = query.filter(models.Complaint.status == status)
    return query.order_by(models.Complaint.raised_at.desc()).all()
