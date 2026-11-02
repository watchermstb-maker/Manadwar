"""Turns raw EntryLog rows into display-ready dicts (who/what/for whom)."""
from sqlalchemy.orm import selectinload

from . import models, timeutil

LOG_LOAD = (
    selectinload(models.EntryLog.actor),
    selectinload(models.EntryLog.vehicle).selectinload(models.Vehicle.resident),
    selectinload(models.EntryLog.visitor).selectinload(models.Visitor.host_resident),
    selectinload(models.EntryLog.delivery).selectinload(models.Delivery.host_resident),
    selectinload(models.EntryLog.staff).selectinload(models.Staff.employed_by),
    selectinload(models.EntryLog.recurring_visitor).selectinload(models.RecurringVisitor.host_resident),
)


def _label(resident):
    return f"{resident.name} ({resident.apartment_no})" if resident is not None else None


def describe(log: models.EntryLog):
    """Returns (subject, resident_label) for a log row."""
    if log.recurring_visitor is not None:
        return f"{log.recurring_visitor.name} (regular visitor)", _label(log.recurring_visitor.host_resident)
    if log.visitor is not None:
        return log.visitor.name, _label(log.visitor.host_resident)
    if log.staff is not None:
        return f"{log.staff.name} ({log.staff.role.value})", _label(log.staff.employed_by)
    if log.delivery is not None:
        d = log.delivery
        return d.platform or d.courier_name or "Delivery", _label(d.host_resident)
    if log.vehicle is not None:
        return log.vehicle.vehicle_number, _label(log.vehicle.resident)
    return None, None


def log_dict(log: models.EntryLog) -> dict:
    subject, resident_label = describe(log)
    return {
        "id": log.id,
        "vehicle_id": log.vehicle_id,
        "credential_id": log.credential_id,
        "visitor_id": log.visitor_id,
        "delivery_id": log.delivery_id,
        "staff_id": log.staff_id,
        "recurring_visitor_id": log.recurring_visitor_id,
        "actor_user_id": log.actor_user_id,
        "entry_method": log.entry_method,
        "credential_value": log.credential_value,
        "gate_name": log.gate_name,
        "direction": log.direction,
        "access": log.access,
        "timestamp": log.timestamp,
        "actor_name": log.actor.name if log.actor is not None else None,
        "subject": subject,
        "resident_label": resident_label,
    }


def local_str(dt) -> str:
    return timeutil.to_local(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else ""
