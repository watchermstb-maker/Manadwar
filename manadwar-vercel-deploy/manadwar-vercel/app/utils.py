import hashlib
import random

from . import models


def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP string of the given length.

    NOTE: not sent via any real SMS gateway -- it is returned directly in
    the API response / shown in the demo UI (no third-party SMS
    integration exists in this prototype).
    """
    return "".join(str(random.randint(0, 9)) for _ in range(length))


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
):
    """Record one gate-entry attempt (granted or denied) to the EntryLog."""
    entry = models.EntryLog(
        vehicle_id=vehicle_id,
        credential_id=credential_id,
        visitor_id=visitor_id,
        delivery_id=delivery_id,
        staff_id=staff_id,
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
    """Hash an Aadhaar (government ID) number for storage.

    Returns (hash_hex, last4). The raw number is never persisted anywhere --
    only this SHA-256 hash (for exact-match dedup lookups, so the same
    person can't be registered as staff twice) and the last 4 digits (for
    human display/verification, the standard masking convention for Indian
    ID numbers) are stored.
    """
    digits = "".join(ch for ch in aadhaar_number if ch.isdigit())
    hash_hex = hashlib.sha256(digits.encode("utf-8")).hexdigest()
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return hash_hex, last4
