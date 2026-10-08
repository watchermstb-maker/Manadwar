from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .models import AccessResult, CredentialStatus, CredentialType, Direction, VehicleType


class ResidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    apartment_no: str
    phone: Optional[str] = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resident_id: Optional[int] = None
    vehicle_number: str
    vehicle_type: VehicleType


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: int
    credential_type: CredentialType
    credential_value: str
    status: CredentialStatus
    expires_at: Optional[datetime] = None
    issued_date: datetime


class VerifyRFIDRequest(BaseModel):
    credential_value: str
    gate_name: str = "MAIN_GATE"
    direction: Direction = Direction.IN


class VerifyRFIDResponse(BaseModel):
    access: AccessResult
    message: str
    vehicle_number: Optional[str] = None
    resident_name: Optional[str] = None


class EntryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: Optional[int] = None
    credential_id: Optional[int] = None
    credential_value: str
    gate_name: str
    direction: Direction
    access: AccessResult
    timestamp: datetime
