from . import models


def log_attempt(
    db,
    *,
    vehicle_id=None,
    credential_id=None,
    gate_name,
    direction,
    access,
    credential_value,
):
    """Record one gate-entry attempt (granted or denied) to the EntryLog."""
    entry = models.EntryLog(
        vehicle_id=vehicle_id,
        credential_id=credential_id,
        credential_value=credential_value,
        gate_name=gate_name,
        direction=direction,
        access=access,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
