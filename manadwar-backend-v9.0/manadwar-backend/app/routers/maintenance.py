from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, notify, schemas, uploads
from ..audit import audit
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Maintenance: Bills & Complaints"])

_admin_only = require_roles(models.UserRole.ADMIN)

# Complaint photos live on disk (not in the database), under UPLOAD_DIR/complaints.
UPLOAD_DIR = uploads.kind_dir("complaints")
MAX_IMAGE_BYTES = uploads.MAX_IMAGE_BYTES
_IMAGE_MEDIA_TYPES = uploads.MEDIA_TYPES
REOPEN_WINDOW = timedelta(days=7)


def _validate_billing_month(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="billing_month must be in 'YYYY-MM' format.")


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

@router.post("/maintenance/bills", response_model=schemas.MaintenanceBillOut)
def create_bill(
    payload: schemas.MaintenanceBillCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
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
def pay_bill(
    bill_id: int,
    payload: schemas.MaintenanceBillPay,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    bill = db.query(models.MaintenanceBill).filter(models.MaintenanceBill.id == bill_id).first()
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found.")

    if current_user.role == models.UserRole.RESIDENT:
        if bill.resident_id != current_user.resident_id:
            raise HTTPException(status_code=403, detail="You can only pay your own bills.")
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

    if bill.status == models.BillStatus.PAID:
        raise HTTPException(status_code=400, detail="This bill has already been paid.")

    bill.status = models.BillStatus.PAID
    bill.paid_at = datetime.utcnow()
    bill.payment_reference = payload.payment_reference
    db.commit()
    db.refresh(bill)
    return bill


@router.get("/maintenance/bills", response_model=List[schemas.MaintenanceBillOut])
def list_bills(
    resident_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        resident_id = current_user.resident_id
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

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
def create_complaint(
    payload: schemas.ComplaintCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        if current_user.resident_id != payload.resident_id:
            raise HTTPException(status_code=403, detail="Residents can only raise complaints for themselves.")
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

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
    if current_user.role == models.UserRole.RESIDENT:
        notify.notify_admins(
            db, "COMPLAINT", f"New complaint: {complaint.category or 'General'}",
            f"{resident.name} ({resident.apartment_no}): {complaint.description[:120]}", "complaint", complaint.id,
        )
    else:
        notify.notify_resident(
            db, resident.id, "COMPLAINT", "A complaint was raised for you",
            f"{complaint.category or 'General'}: {complaint.description[:120]}", "complaint", complaint.id,
        )
        audit(db, current_user, "complaint.create", "complaint", complaint.id, f"for resident {resident.id}")
    return complaint


@router.post("/complaints/{complaint_id}/status", response_model=schemas.ComplaintOut)
def update_complaint_status(
    complaint_id: int,
    payload: schemas.ComplaintStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    complaint = db.query(models.Complaint).filter(models.Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")

    complaint.status = payload.status
    if payload.resolution_notes is not None:
        complaint.resolution_notes = payload.resolution_notes
    if payload.status == models.ComplaintStatus.RESOLVED:
        complaint.resolved_at = datetime.utcnow()
    else:
        complaint.resolved_at = None

    db.commit()
    db.refresh(complaint)
    audit(db, current_user, "complaint.status", "complaint", complaint.id, payload.status.value)
    notify.notify_resident(
        db, complaint.resident_id, "COMPLAINT",
        f"Your complaint is now {payload.status.value.replace('_', ' ').title()}",
        (payload.resolution_notes or complaint.category or "")[:200] or None, "complaint", complaint.id,
    )
    return complaint


@router.post("/complaints/{complaint_id}/assign", response_model=schemas.ComplaintOut)
def assign_complaint(
    complaint_id: int,
    payload: schemas.ComplaintAssign,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    complaint = db.query(models.Complaint).filter(models.Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    if complaint.status == models.ComplaintStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="This complaint is already resolved.")
    complaint.assigned_to = payload.assigned_to
    complaint.assigned_at = datetime.utcnow()
    if complaint.status == models.ComplaintStatus.OPEN:
        complaint.status = models.ComplaintStatus.IN_PROGRESS
    db.commit()
    db.refresh(complaint)
    audit(db, current_user, "complaint.assign", "complaint", complaint.id, payload.assigned_to)
    notify.notify_resident(
        db, complaint.resident_id, "COMPLAINT", "Your complaint was assigned",
        f"{payload.assigned_to} will look into it.", "complaint", complaint.id,
    )
    return complaint


@router.post("/complaints/{complaint_id}/reopen", response_model=schemas.ComplaintOut)
def reopen_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    complaint = _accessible_complaint(db, complaint_id, current_user)
    if complaint.status != models.ComplaintStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Only a resolved complaint can be reopened.")
    if complaint.resolved_at is not None and datetime.utcnow() - complaint.resolved_at > REOPEN_WINDOW:
        raise HTTPException(status_code=400, detail="This complaint was resolved more than 7 days ago. Please raise a new one.")
    complaint.status = models.ComplaintStatus.OPEN
    complaint.resolved_at = None
    db.commit()
    db.refresh(complaint)
    if current_user.role == models.UserRole.RESIDENT:
        notify.notify_admins(
            db, "COMPLAINT", "Complaint reopened", f"Complaint #{complaint.id} was reopened by the resident.",
            "complaint", complaint.id,
        )
    else:
        audit(db, current_user, "complaint.reopen", "complaint", complaint.id)
    return complaint


@router.get("/complaints/{complaint_id}/comments", response_model=List[schemas.ComplaintCommentOut])
def list_comments(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    complaint = _accessible_complaint(db, complaint_id, current_user)
    return (
        db.query(models.ComplaintComment)
        .filter(models.ComplaintComment.complaint_id == complaint.id)
        .order_by(models.ComplaintComment.created_at, models.ComplaintComment.id).all()
    )


@router.post("/complaints/{complaint_id}/comments", response_model=schemas.ComplaintCommentOut)
def add_comment(
    complaint_id: int,
    payload: schemas.ComplaintCommentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    complaint = _accessible_complaint(db, complaint_id, current_user)
    comment = models.ComplaintComment(
        complaint_id=complaint.id, user_id=current_user.id, author_name=current_user.name,
        author_role=current_user.role.value, body=payload.body,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    if current_user.role == models.UserRole.ADMIN:
        notify.notify_resident(
            db, complaint.resident_id, "COMPLAINT", "New reply on your complaint",
            payload.body[:160], "complaint", complaint.id,
        )
    else:
        notify.notify_admins(
            db, "COMPLAINT", f"Reply on complaint #{complaint.id}", f"{current_user.name}: {payload.body[:140]}",
            "complaint", complaint.id,
        )
    return comment


@router.get("/complaints", response_model=List[schemas.ComplaintOut])
def list_complaints(
    resident_id: Optional[int] = None,
    status: Optional[models.ComplaintStatus] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        resident_id = current_user.resident_id
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

    query = db.query(models.Complaint)
    if resident_id is not None:
        query = query.filter(models.Complaint.resident_id == resident_id)
    if status is not None:
        query = query.filter(models.Complaint.status == status)
    if category is not None:
        query = query.filter(models.Complaint.category == category)
    return query.order_by(models.Complaint.raised_at.desc()).all()


@router.get("/complaints/categories", response_model=List[str])
def list_complaint_categories(current_user: models.User = Depends(get_current_user)):
    return schemas.COMPLAINT_CATEGORIES


def _accessible_complaint(db: Session, complaint_id: int, current_user: models.User) -> models.Complaint:
    complaint = db.query(models.Complaint).filter(models.Complaint.id == complaint_id).first()
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    if current_user.role == models.UserRole.RESIDENT:
        if complaint.resident_id != current_user.resident_id:
            raise HTTPException(status_code=403, detail="You can only access your own complaints.")
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return complaint


@router.post("/complaints/{complaint_id}/image", response_model=schemas.ComplaintOut)
def upload_complaint_image(
    complaint_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    complaint = _accessible_complaint(db, complaint_id, current_user)
    if complaint.status == models.ComplaintStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="This complaint is already resolved.")

    filename = uploads.save_image("complaints", file)
    previous = complaint.image_path
    complaint.image_path = filename
    db.commit()
    db.refresh(complaint)
    uploads.remove_image("complaints", previous)
    return complaint


@router.get("/complaints/{complaint_id}/image")
def get_complaint_image(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    complaint = _accessible_complaint(db, complaint_id, current_user)
    name = complaint.image_path
    if not name or Path(name).name != name:
        raise HTTPException(status_code=404, detail="This complaint has no photo.")
    path = UPLOAD_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This complaint has no photo.")
    return FileResponse(
        path,
        media_type=_IMAGE_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )
