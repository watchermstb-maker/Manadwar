"""Deliveries: residents pre-announce, guards match arrivals, admin oversees.

Flow
- Resident announces what they expect (platform + time window)   -> EXPECTED
- Courier arrives; guard finds the announcement and lets them in -> ADMITTED
- Courier arrives UNannounced; guard logs it                     -> AWAITING_APPROVAL
  - the resident approves (-> APPROVED, guard can now let in) or denies (-> DENIED)
  - admin can decide on a resident's behalf
- Guard may refuse any open delivery                              -> DENIED
- Resident/admin may cancel an open delivery                      -> CANCELLED
- Announcements past their window, and unanswered walk-ins older than
  WALK_IN_TTL, flip to EXPIRED lazily whenever deliveries are read/acted on
  (same no-scheduler pattern used elsewhere in this project).
Exits are not tracked.

v8.3 additions
- Standing rules: a resident can say "always allow Swiggy", "leave Amazon at the
  gate" or "never admit Dunzo". Rules are applied the moment a guard logs an
  unexpected courier, so most of them never need an approval tap.
- The guard can attach a photo of the parcel; the resident sees it.
- Residents are notified at every step.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models, notify, schemas, uploads, utils
from ..audit import audit
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Deliveries"])

_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)
_admin_only = require_roles(models.UserRole.ADMIN)

S = models.DeliveryStatus
OPEN_STATUSES = (S.EXPECTED, S.AWAITING_APPROVAL, S.APPROVED)
MAX_ANNOUNCE_WINDOW = timedelta(days=7)
WALK_IN_TTL = timedelta(hours=2)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _expire_stale(db: Session, now: datetime) -> None:
    """Flip announcements past their window, and old unanswered walk-ins, to EXPIRED."""
    changed = False
    for d in db.query(models.Delivery).filter(models.Delivery.status.in_(OPEN_STATUSES)).all():
        if d.status == S.EXPECTED and d.expected_until is not None and d.expected_until < now:
            d.status, changed = S.EXPIRED, True
        elif (
            d.source == models.DeliverySource.WALK_IN
            and d.status in (S.AWAITING_APPROVAL, S.APPROVED)
            and d.requested_at < now - WALK_IN_TTL
        ):
            d.status, changed = S.EXPIRED, True
    if changed:
        db.commit()


def _get_delivery(db: Session, delivery_id: int) -> models.Delivery:
    delivery = db.query(models.Delivery).filter(models.Delivery.id == delivery_id).first()
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found.")
    return delivery


def _require_resident_access(delivery: models.Delivery, user: models.User) -> None:
    """Residents may act only on their own deliveries; admin on any; guards never."""
    if user.role == models.UserRole.RESIDENT:
        if delivery.host_resident_id != user.resident_id:
            raise HTTPException(status_code=403, detail="You can only manage your own deliveries.")
    elif user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")


def _require_host(db: Session, host_resident_id: int) -> None:
    if db.query(models.Resident).filter(models.Resident.id == host_resident_id).first() is None:
        raise HTTPException(status_code=404, detail="Host resident not found.")


def _label(d: models.Delivery) -> str:
    return d.platform or d.courier_name or "delivery"


def _not_in_state(d: models.Delivery, action: str) -> HTTPException:
    return HTTPException(status_code=400, detail=f"Can't {action}: this delivery is {d.status.value}.")


# ---------------------------------------------------------------------------
# resident side
# ---------------------------------------------------------------------------

@router.post("/deliveries/announce", response_model=schemas.DeliveryOut)
def announce_delivery(
    payload: schemas.DeliveryAnnounce,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role == models.UserRole.RESIDENT:
        if current_user.resident_id != payload.host_resident_id:
            raise HTTPException(status_code=403, detail="Residents can only announce deliveries for themselves.")
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    _require_host(db, payload.host_resident_id)

    platform = payload.platform.strip()
    if not platform:
        raise HTTPException(status_code=400, detail="Please say which platform or courier to expect.")
    now = datetime.utcnow()
    if payload.expected_until <= now:
        raise HTTPException(status_code=400, detail="The expected window must end in the future.")
    if payload.expected_until <= payload.expected_from:
        raise HTTPException(status_code=400, detail="The window's end must be after its start.")
    if payload.expected_until - payload.expected_from > MAX_ANNOUNCE_WINDOW:
        raise HTTPException(status_code=400, detail="The expected window can be at most 7 days long.")

    delivery = models.Delivery(
        host_resident_id=payload.host_resident_id,
        source=models.DeliverySource.ANNOUNCED,
        platform=platform,
        description=(payload.description or "").strip() or None,
        expected_from=payload.expected_from,
        expected_until=payload.expected_until,
        leave_at_gate=payload.leave_at_gate,
        status=S.EXPECTED,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/deliveries/{delivery_id}/decision", response_model=schemas.DeliveryOut)
def decide_walk_in(
    delivery_id: int,
    payload: schemas.DeliveryDecision,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Resident (or admin on their behalf) approves/denies an unexpected arrival."""
    now = datetime.utcnow()
    _expire_stale(db, now)
    delivery = _get_delivery(db, delivery_id)
    _require_resident_access(delivery, current_user)
    if delivery.status != S.AWAITING_APPROVAL:
        raise _not_in_state(delivery, "decide")

    delivery.status = S.APPROVED if payload.approve else S.DENIED
    delivery.decided_at = now
    db.commit()
    db.refresh(delivery)
    if current_user.role == models.UserRole.ADMIN:
        audit(db, current_user, "delivery.decide", "delivery", delivery.id,
              f"{'approved' if payload.approve else 'denied'} {_label(delivery)} for resident {delivery.host_resident_id}")
    if not payload.approve:
        utils.log_attempt(
            db, actor=current_user, delivery_id=delivery.id, entry_method=models.EntryMethod.DELIVERY,
            credential_value=_label(delivery), gate_name="MAIN_GATE",
            direction=models.Direction.IN, access=models.AccessResult.DENIED,
        )
    return delivery


@router.post("/deliveries/{delivery_id}/cancel", response_model=schemas.DeliveryOut)
def cancel_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _expire_stale(db, datetime.utcnow())
    delivery = _get_delivery(db, delivery_id)
    _require_resident_access(delivery, current_user)
    if delivery.status not in OPEN_STATUSES:
        raise _not_in_state(delivery, "cancel")
    delivery.status = S.CANCELLED
    db.commit()
    db.refresh(delivery)
    if current_user.role == models.UserRole.ADMIN:
        audit(db, current_user, "delivery.cancel", "delivery", delivery.id, _label(delivery))
    return delivery


# ---------------------------------------------------------------------------
# gate side (guard / admin)
# ---------------------------------------------------------------------------

@router.post("/deliveries/walk-in", response_model=schemas.DeliveryOut)
def log_walk_in(
    payload: schemas.DeliveryWalkIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    _require_host(db, payload.host_resident_id)
    platform = (payload.platform or "").strip() or None
    courier_name = (payload.courier_name or "").strip() or None
    if not platform and not courier_name:
        raise HTTPException(status_code=400, detail="Enter the platform or the courier's name.")

    delivery = models.Delivery(
        host_resident_id=payload.host_resident_id,
        source=models.DeliverySource.WALK_IN,
        platform=platform,
        courier_name=courier_name,
        courier_phone=(payload.courier_phone or "").strip() or None,
        description=(payload.description or "").strip() or None,
        status=S.AWAITING_APPROVAL,
    )

    # A standing rule from the resident answers for them straight away.
    rule = None
    if platform:
        rule = (
            db.query(models.DeliveryRule)
            .filter(models.DeliveryRule.resident_id == payload.host_resident_id,
                    models.DeliveryRule.platform_key == platform.lower())
            .first()
        )
    now = datetime.utcnow()
    A = models.DeliveryRuleAction
    if rule is not None:
        delivery.decided_at = now
        if rule.action == A.ALLOW:
            delivery.status = S.APPROVED
            delivery.rule_applied = f"Resident's rule: always allow {rule.platform}"
        elif rule.action == A.LEAVE_AT_GATE:
            delivery.status = S.APPROVED
            delivery.leave_at_gate = True
            delivery.rule_applied = f"Resident's rule: leave {rule.platform} at the gate"
        else:
            delivery.status = S.DENIED
            delivery.rule_applied = f"Resident's rule: never admit {rule.platform}"
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    who = delivery.platform or delivery.courier_name or "A courier"
    if rule is None:
        notify.notify_resident(
            db, delivery.host_resident_id, "DELIVERY_APPROVAL", f"{who} is at the gate",
            "Approve or deny the delivery so the guard knows.", "delivery", delivery.id,
        )
    else:
        if delivery.status == S.DENIED:
            utils.log_attempt(
                db, actor=current_user, delivery_id=delivery.id, entry_method=models.EntryMethod.DELIVERY,
                credential_value=_label(delivery), gate_name="MAIN_GATE",
                direction=models.Direction.IN, access=models.AccessResult.DENIED,
            )
        notify.notify_resident(
            db, delivery.host_resident_id, "DELIVERY", f"{who}: {delivery.rule_applied.split(': ', 1)[1]}",
            "Handled by your delivery rule.", "delivery", delivery.id,
        )
    return delivery


@router.post("/deliveries/{delivery_id}/admit", response_model=schemas.DeliveryOut)
def admit_delivery(
    delivery_id: int,
    payload: schemas.DeliveryGateAction = schemas.DeliveryGateAction(),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    now = datetime.utcnow()
    _expire_stale(db, now)
    delivery = _get_delivery(db, delivery_id)
    if delivery.status == S.AWAITING_APPROVAL:
        raise HTTPException(status_code=400, detail="Waiting for the resident to approve this delivery first.")
    if delivery.status not in (S.EXPECTED, S.APPROVED):
        raise _not_in_state(delivery, "admit")

    delivery.status = S.ADMITTED
    delivery.admitted_at = now
    delivery.admitted_by_user_id = current_user.id
    db.commit()
    db.refresh(delivery)
    utils.log_attempt(
        db, actor=current_user, delivery_id=delivery.id, entry_method=models.EntryMethod.DELIVERY,
        credential_value=_label(delivery), gate_name=payload.gate_name,
        direction=models.Direction.IN, access=models.AccessResult.GRANTED,
    )
    notify.notify_resident(
        db, delivery.host_resident_id, "DELIVERY",
        f"{_label(delivery).capitalize()} " + ("parcel left with security" if delivery.leave_at_gate else "let in"),
        "Collect it from the security desk." if delivery.leave_at_gate else "The courier is on the way to your flat.",
        "delivery", delivery.id,
    )
    return delivery


@router.post("/deliveries/{delivery_id}/refuse", response_model=schemas.DeliveryOut)
def refuse_delivery(
    delivery_id: int,
    payload: schemas.DeliveryGateAction = schemas.DeliveryGateAction(),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    _expire_stale(db, datetime.utcnow())
    delivery = _get_delivery(db, delivery_id)
    if delivery.status not in OPEN_STATUSES:
        raise _not_in_state(delivery, "refuse")
    delivery.status = S.DENIED
    db.commit()
    db.refresh(delivery)
    notify.notify_resident(
        db, delivery.host_resident_id, "DELIVERY", f"{_label(delivery).capitalize()} was turned away",
        "The guard refused this delivery.", "delivery", delivery.id,
    )
    utils.log_attempt(
        db, actor=current_user, delivery_id=delivery.id, entry_method=models.EntryMethod.DELIVERY,
        credential_value=_label(delivery), gate_name=payload.gate_name,
        direction=models.Direction.IN, access=models.AccessResult.DENIED,
    )
    return delivery


# ---------------------------------------------------------------------------
# parcel photo
# ---------------------------------------------------------------------------

@router.post("/deliveries/{delivery_id}/parcel-photo", response_model=schemas.DeliveryOut)
def upload_parcel_photo(
    delivery_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_gate_staff),
):
    delivery = _get_delivery(db, delivery_id)
    if delivery.status in (S.DENIED, S.CANCELLED, S.EXPIRED):
        raise _not_in_state(delivery, "attach a photo to")
    name = uploads.save_image("parcels", file)
    previous = delivery.parcel_photo_path
    delivery.parcel_photo_path = name
    db.commit()
    db.refresh(delivery)
    uploads.remove_image("parcels", previous)
    notify.notify_resident(
        db, delivery.host_resident_id, "DELIVERY", f"Photo of your {_label(delivery)} parcel",
        "Open Deliveries to see it.", "delivery", delivery.id,
    )
    return delivery


@router.get("/deliveries/{delivery_id}/parcel-photo")
def get_parcel_photo(
    delivery_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    delivery = _get_delivery(db, delivery_id)
    if current_user.role == models.UserRole.RESIDENT and delivery.host_resident_id != current_user.resident_id:
        raise HTTPException(status_code=403, detail="You can only see your own deliveries.")
    path = uploads.image_path("parcels", delivery.parcel_photo_path)
    return FileResponse(
        path, media_type=uploads.MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


# ---------------------------------------------------------------------------
# standing rules ("always allow Swiggy")
# ---------------------------------------------------------------------------

@router.get("/delivery-rules", response_model=List[schemas.DeliveryRuleOut])
def list_rules(
    resident_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.DeliveryRule)
    if current_user.role == models.UserRole.RESIDENT:
        query = query.filter(models.DeliveryRule.resident_id == current_user.resident_id)
    elif current_user.role == models.UserRole.ADMIN:
        if resident_id is not None:
            query = query.filter(models.DeliveryRule.resident_id == resident_id)
    else:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    return query.order_by(models.DeliveryRule.platform).all()


@router.post("/delivery-rules", response_model=schemas.DeliveryRuleOut)
def set_rule(
    payload: schemas.DeliveryRuleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create the rule for a platform, or change it if one already exists."""
    if current_user.role == models.UserRole.RESIDENT:
        resident_id = current_user.resident_id
    elif current_user.role == models.UserRole.ADMIN:
        resident_id = payload.resident_id
        if resident_id is None:
            raise HTTPException(status_code=400, detail="Choose the resident.")
    else:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    _require_host(db, resident_id)
    key = payload.platform.lower()
    rule = (
        db.query(models.DeliveryRule)
        .filter(models.DeliveryRule.resident_id == resident_id, models.DeliveryRule.platform_key == key)
        .first()
    )
    if rule is None:
        if db.query(models.DeliveryRule).filter(models.DeliveryRule.resident_id == resident_id).count() >= 30:
            raise HTTPException(status_code=400, detail="You have reached the limit of 30 delivery rules.")
        rule = models.DeliveryRule(resident_id=resident_id, platform=payload.platform, platform_key=key, action=payload.action)
        db.add(rule)
    else:
        rule.action = payload.action
        rule.platform = payload.platform
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/delivery-rules/{rule_id}")
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    rule = db.query(models.DeliveryRule).filter(models.DeliveryRule.id == rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    if current_user.role == models.UserRole.RESIDENT:
        if rule.resident_id != current_user.resident_id:
            raise HTTPException(status_code=403, detail="You can only manage your own rules.")
    elif current_user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# listing + admin overview
# ---------------------------------------------------------------------------

@router.get("/deliveries", response_model=List[schemas.DeliveryOut])
def list_deliveries(
    status: Optional[models.DeliveryStatus] = None,
    needs_action: bool = False,
    q: Optional[str] = None,
    days: Optional[int] = Query(None, ge=1, le=365),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    now = datetime.utcnow()
    _expire_stale(db, now)

    query = db.query(models.Delivery).join(
        models.Resident, models.Delivery.host_resident_id == models.Resident.id
    )
    if current_user.role == models.UserRole.RESIDENT:
        query = query.filter(models.Delivery.host_resident_id == current_user.resident_id)
    elif current_user.role not in (models.UserRole.GUARD, models.UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")

    if needs_action:
        query = query.filter(models.Delivery.status.in_(OPEN_STATUSES))
    if status is not None:
        query = query.filter(models.Delivery.status == status)
    if days is not None:
        query = query.filter(models.Delivery.requested_at >= now - timedelta(days=days))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(
            func.lower(func.coalesce(models.Delivery.platform, "")).like(like),
            func.lower(func.coalesce(models.Delivery.courier_name, "")).like(like),
            func.lower(func.coalesce(models.Delivery.description, "")).like(like),
            func.lower(models.Resident.name).like(like),
            func.lower(models.Resident.apartment_no).like(like),
        ))
    return query.order_by(models.Delivery.requested_at.desc()).limit(limit).all()


@router.get("/deliveries/summary", response_model=schemas.DeliverySummary)
def delivery_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(_admin_only),
):
    now = datetime.utcnow()
    _expire_stale(db, now)

    pending_now = {s.value: 0 for s in OPEN_STATUSES}
    for status, count in (
        db.query(models.Delivery.status, func.count())
        .filter(models.Delivery.status.in_(OPEN_STATUSES))
        .group_by(models.Delivery.status).all()
    ):
        pending_now[status.value] = count

    since = now - timedelta(hours=24)
    last_24h = {s.value: 0 for s in models.DeliveryStatus}
    for status, count in (
        db.query(models.Delivery.status, func.count())
        .filter(models.Delivery.requested_at >= since)
        .group_by(models.Delivery.status).all()
    ):
        last_24h[status.value] = count
    last_24h["TOTAL"] = sum(last_24h.values())

    top = (
        db.query(func.coalesce(models.Delivery.platform, models.Delivery.courier_name, "Unknown"), func.count())
        .filter(models.Delivery.requested_at >= since)
        .group_by(func.coalesce(models.Delivery.platform, models.Delivery.courier_name, "Unknown"))
        .order_by(func.count().desc()).limit(5).all()
    )
    return schemas.DeliverySummary(
        pending_now=pending_now,
        last_24h=last_24h,
        top_platforms_24h=[{"platform": name, "count": count} for name, count in top],
    )
