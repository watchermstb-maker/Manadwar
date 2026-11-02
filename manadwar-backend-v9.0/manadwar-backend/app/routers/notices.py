"""Notice board with read receipts."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models, notify, schemas
from ..audit import audit
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Notice board"])

_admin_only = require_roles(models.UserRole.ADMIN)


class PinUpdate(BaseModel):
    pinned: bool


def _resident_logins(db: Session):
    return db.query(models.User).filter(
        models.User.role == models.UserRole.RESIDENT, models.User.is_active == True).all()  # noqa: E712


def _out(db, n: models.Notice, user: models.User, reader_total: int) -> schemas.NoticeOut:
    author = db.query(models.User).filter(models.User.id == n.created_by_user_id).first()
    out = schemas.NoticeOut(
        id=n.id, title=n.title, body=n.body, pinned=n.pinned, created_at=n.created_at, expires_at=n.expires_at,
        created_by=author.name if author else None,
        read=db.query(models.NoticeRead).filter(
            models.NoticeRead.notice_id == n.id, models.NoticeRead.user_id == user.id).first() is not None,
    )
    if user.role == models.UserRole.ADMIN:
        out.read_count = (
            db.query(models.NoticeRead).join(models.User, models.User.id == models.NoticeRead.user_id)
            .filter(models.NoticeRead.notice_id == n.id, models.User.role == models.UserRole.RESIDENT,
                    models.User.is_active == True).count()  # noqa: E712
        )
        out.reader_total = reader_total
    return out


@router.get("/notices", response_model=List[schemas.NoticeOut])
def list_notices(
    include_expired: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    now = datetime.utcnow()
    query = db.query(models.Notice).filter(models.Notice.is_deleted == False)  # noqa: E712
    if not (include_expired and current_user.role == models.UserRole.ADMIN):
        query = query.filter(or_(models.Notice.expires_at.is_(None), models.Notice.expires_at >= now))
    rows = query.order_by(models.Notice.pinned.desc(), models.Notice.created_at.desc(), models.Notice.id.desc()).limit(100).all()
    total = len(_resident_logins(db)) if current_user.role == models.UserRole.ADMIN else 0
    return [_out(db, n, current_user, total) for n in rows]


@router.post("/notices", response_model=schemas.NoticeOut)
def create_notice(
    payload: schemas.NoticeCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    if payload.expires_at is not None and payload.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="The expiry must be in the future.")
    notice = models.Notice(
        title=payload.title, body=payload.body, pinned=payload.pinned, expires_at=payload.expires_at,
        created_by_user_id=admin.id,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    residents = _resident_logins(db)
    notify.notify_users(db, residents, "NOTICE", f"Notice: {notice.title}", notice.body[:140], "notice", notice.id)
    audit(db, admin, "notice.create", "notice", notice.id, notice.title)
    return _out(db, notice, admin, len(residents))


@router.post("/notices/{notice_id}/read")
def mark_notice_read(
    notice_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id, models.Notice.is_deleted == False).first()  # noqa: E712
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    exists = db.query(models.NoticeRead).filter(
        models.NoticeRead.notice_id == notice_id, models.NoticeRead.user_id == current_user.id).first()
    if exists is None:
        db.add(models.NoticeRead(notice_id=notice_id, user_id=current_user.id))
        db.commit()
    return {"read": True}


@router.get("/notices/{notice_id}/readers")
def notice_readers(
    notice_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    reads = {r.user_id: r.read_at for r in db.query(models.NoticeRead).filter(models.NoticeRead.notice_id == notice_id).all()}
    read, unread = [], []
    for u in _resident_logins(db):
        item = {"user_id": u.id, "name": u.name, "apartment_no": u.apartment_no}
        if u.id in reads:
            item["read_at"] = reads[u.id]
            read.append(item)
        else:
            unread.append(item)
    return {"read": read, "unread": unread}


@router.post("/notices/{notice_id}/pin", response_model=schemas.NoticeOut)
def pin_notice(
    notice_id: int,
    payload: PinUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id, models.Notice.is_deleted == False).first()  # noqa: E712
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    notice.pinned = payload.pinned
    db.commit()
    db.refresh(notice)
    return _out(db, notice, admin, len(_resident_logins(db)))


@router.delete("/notices/{notice_id}")
def delete_notice(
    notice_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id, models.Notice.is_deleted == False).first()  # noqa: E712
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    notice.is_deleted = True
    db.commit()
    audit(db, admin, "notice.delete", "notice", notice.id, notice.title)
    return {"deleted": True}
