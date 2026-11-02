"""Audit trail: who changed what. Written by admin/management actions."""
from . import models


def audit(db, user, action: str, target_type: str = None, target_id=None, detail: str = None):
    db.add(models.AuditLog(
        user_id=user.id if user is not None else None,
        user_name=user.name if user is not None else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=(detail or "")[:500] or None,
    ))
    db.commit()
