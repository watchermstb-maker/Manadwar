"""In-app alerts. Residents (and admins) are never left guessing: the gate
actions that concern them create a Notification they see in the bell menu."""
from typing import Iterable, Optional

from . import models


def notify_users(db, users: Iterable[models.User], kind: str, title: str, body: str = None,
                 ref_type: str = None, ref_id=None, commit: bool = True) -> int:
    n = 0
    for u in users:
        db.add(models.Notification(
            user_id=u.id, kind=kind, title=title[:120], body=(body or None) and body[:300],
            ref_type=ref_type, ref_id=str(ref_id) if ref_id is not None else None,
        ))
        n += 1
    if commit and n:
        db.commit()
    return n


def residents_users(db, resident_id: Optional[int]):
    if resident_id is None:
        return []
    return (
        db.query(models.User)
        .filter(models.User.resident_id == resident_id, models.User.is_active == True)  # noqa: E712
        .all()
    )


def notify_resident(db, resident_id, kind, title, body=None, ref_type=None, ref_id=None):
    return notify_users(db, residents_users(db, resident_id), kind, title, body, ref_type, ref_id)


def role_users(db, *roles):
    return (
        db.query(models.User)
        .filter(models.User.role.in_(roles), models.User.is_active == True)  # noqa: E712
        .all()
    )


def notify_admins(db, kind, title, body=None, ref_type=None, ref_id=None):
    return notify_users(db, role_users(db, models.UserRole.ADMIN), kind, title, body, ref_type, ref_id)


def notify_gate(db, kind, title, body=None, ref_type=None, ref_id=None):
    return notify_users(
        db, role_users(db, models.UserRole.ADMIN, models.UserRole.GUARD),
        kind, title, body, ref_type, ref_id,
    )
