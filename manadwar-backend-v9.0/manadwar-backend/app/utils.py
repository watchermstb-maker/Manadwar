import hashlib
import hmac
import secrets

from . import models
from .config import AADHAAR_KEY


def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP string of the given length.

    NOTE: not sent via any real SMS gateway -- it is returned directly in
    the API response / shown in the demo UI (no third-party SMS
    integration exists in this prototype).
    """
    return "".join(secrets.choice("0123456789") for _ in range(length))


def log_attempt(
    db,
    *,
    vehicle_id=None,
    credential_id=None,
    visitor_id=None,
    entry_method,
    credential_value,
    gate_name,
    direction,
    access,
    delivery_id=None,
    staff_id=None,
    recurring_visitor_id=None,
    actor=None,
):
    """Record one gate-entry attempt (granted or denied) to the EntryLog."""
    entry = models.EntryLog(
        vehicle_id=vehicle_id,
        credential_id=credential_id,
        visitor_id=visitor_id,
        delivery_id=delivery_id,
        staff_id=staff_id,
        recurring_visitor_id=recurring_visitor_id,
        actor_user_id=actor.id if actor is not None else None,
        entry_method=entry_method,
        credential_value=credential_value,
        gate_name=gate_name,
        direction=direction,
        access=access,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def hash_aadhaar(aadhaar_number: str):
    """Fingerprint an Aadhaar (government ID) number for storage.

    Returns (fingerprint_hex, last4). The raw number is never persisted. The
    fingerprint is an HMAC-SHA256 keyed with a server-side secret
    (AADHAAR_HASH_KEY), so a leaked database alone cannot be used to
    brute-force the 12-digit numbers. It exists only so the same person
    cannot be registered twice; last4 is for human verification.
    """
    digits = "".join(ch for ch in aadhaar_number if ch.isdigit())
    hash_hex = hmac.new(AADHAAR_KEY, digits.encode("utf-8"), hashlib.sha256).hexdigest()
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return hash_hex, last4
