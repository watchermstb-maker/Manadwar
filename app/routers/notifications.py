"""The bell menu: alerts for whoever is signed in."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", response_model=List[schemas.NotificationOut])
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.Notification).filter(models.Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(models.Notification.read_at.is_(None))
    return query.order_by(models.Notification.created_at.desc(), models.Notification.id.desc()).limit(limit).all()


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    n = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id, models.Notification.read_at.is_(None)).count()
    return {"unread": n}


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    now = datetime.utcnow()
    rows = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id, models.Notification.read_at.is_(None)).all()
    for n in rows:
        n.read_at = now
    db.commit()
    return {"marked": len(rows)}


@router.post("/notifications/{notification_id}/read", response_model=schemas.NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    n = db.query(models.Notification).filter(
        models.Notification.id == notification_id, models.Notification.user_id == current_user.id).first()
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if n.read_at is None:
        n.read_at = datetime.utcnow()
        db.commit()
        db.refresh(n)
    return n
