"""The resident's own home screen: what is happening in my flat."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import logview, models, timeutil
from ..auth import require_roles
from ..database import get_db
from .attendance import _days

router = APIRouter(tags=["Resident home"])

_resident_only = require_roles(models.UserRole.RESIDENT)


@router.get("/me/home")
def home(db: Session = Depends(get_db), user: models.User = Depends(_resident_only)):
    rid = user.resident_id
    now = datetime.utcnow()
    from .deliveries import _expire_stale
    _expire_stale(db, now)

    V, D, DS = models.Visitor, models.Delivery, models.DeliveryStatus
    live = db.query(V).filter(V.host_resident_id == rid, V.cancelled_at.is_(None), V.valid_from <= now, V.valid_until >= now).count()
    scheduled = db.query(V).filter(V.host_resident_id == rid, V.cancelled_at.is_(None), V.valid_from > now).count()
    expected = db.query(D).filter(D.host_resident_id == rid, D.status == DS.EXPECTED).count()
    awaiting = (
        db.query(D).filter(D.host_resident_id == rid, D.status == DS.AWAITING_APPROVAL)
        .order_by(D.requested_at).all()
    )
    open_complaints = db.query(models.Complaint).filter(
        models.Complaint.resident_id == rid, models.Complaint.status != models.ComplaintStatus.RESOLVED).count()

    # Notices this person has not opened yet.
    read_ids = [r[0] for r in db.query(models.NoticeRead.notice_id).filter(models.NoticeRead.user_id == user.id).all()]
    unread_notices = (
        db.query(models.Notice)
        .filter(models.Notice.is_deleted == False,  # noqa: E712
                or_(models.Notice.expires_at.is_(None), models.Notice.expires_at >= now),
                ~models.Notice.id.in_(read_ids or [-1])).count()
    )
    unread_alerts = db.query(models.Notification).filter(
        models.Notification.user_id == user.id, models.Notification.read_at.is_(None)).count()

    vehicles = []
    for v in db.query(models.Vehicle).filter(models.Vehicle.resident_id == rid).all():
        vehicles.append({
            "id": v.id, "vehicle_number": v.vehicle_number, "vehicle_type": v.vehicle_type.value,
            "credentials": [
                {"type": c.credential_type.value, "value": c.credential_value, "status": c.status.value,
                 "expires_at": c.expires_at}
                for c in v.credentials
            ],
        })

    staff = db.query(models.Staff).filter(models.Staff.employed_by_resident_id == rid).order_by(models.Staff.name).all()
    today = timeutil.local_today()
    start, end = timeutil.local_day_bounds_utc(today)
    days = _days(db, [s.id for s in staff], start, end)
    staff_out = []
    for s in staff:
        info = days.get(s.id, {}).get(today)
        staff_out.append({
            "id": s.id, "name": s.name, "role": s.role.value, "status": s.status.value,
            "present_today": bool(info), "inside": bool(info and info["inside"]),
            "first_in": info["first_in"].strftime("%H:%M") if info and info["first_in"] else None,
            "last_out": info["last_out"].strftime("%H:%M") if info and info["last_out"] else None,
        })

    EL = models.EntryLog
    logs = (
        db.query(EL)
        .outerjoin(models.Vehicle, EL.vehicle_id == models.Vehicle.id)
        .outerjoin(models.Visitor, EL.visitor_id == models.Visitor.id)
        .outerjoin(models.Staff, EL.staff_id == models.Staff.id)
        .outerjoin(models.Delivery, EL.delivery_id == models.Delivery.id)
        .outerjoin(models.RecurringVisitor, EL.recurring_visitor_id == models.RecurringVisitor.id)
        .filter(or_(
            models.Vehicle.resident_id == rid, models.Visitor.host_resident_id == rid,
            models.Staff.employed_by_resident_id == rid, models.Delivery.host_resident_id == rid,
            models.RecurringVisitor.host_resident_id == rid,
        ))
        .options(*logview.LOG_LOAD)
        .order_by(EL.timestamp.desc(), EL.id.desc()).limit(15).all()
    )
    activity = []
    for l in logs:
        d = logview.log_dict(l)
        activity.append({
            "timestamp": l.timestamp, "method": l.entry_method.value, "direction": l.direction.value,
            "access": l.access.value, "subject": d["subject"],
        })

    sos = (
        db.query(models.SosAlert)
        .filter(models.SosAlert.resident_id == rid, models.SosAlert.status != models.SosStatus.RESOLVED)
        .order_by(models.SosAlert.created_at.desc()).first()
    )
    return {
        "counts": {
            "visitors_live": live, "visitors_scheduled": scheduled, "deliveries_expected": expected,
            "deliveries_awaiting": len(awaiting), "complaints_open": open_complaints,
            "notices_unread": unread_notices, "alerts_unread": unread_alerts,
        },
        "awaiting_approval": [
            {"id": d.id, "platform": d.platform, "courier_name": d.courier_name, "description": d.description,
             "requested_at": d.requested_at}
            for d in awaiting
        ],
        "vehicles": vehicles,
        "staff": staff_out,
        "recent_activity": activity,
        "sos_active": ({"id": sos.id, "status": sos.status.value, "kind": sos.kind, "created_at": sos.created_at}
                       if sos else None),
    }
