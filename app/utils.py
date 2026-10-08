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
):
    """Record one gate-entry attempt (granted or denied) to the EntryLog."""
    entry = models.EntryLog(
        vehicle_id=vehicle_id,
        credential_id=credential_id,
        visitor_id=visitor_id,
        delivery_id=delivery_id,
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
