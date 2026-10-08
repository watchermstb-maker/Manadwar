from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .models import (
    AccessResult,
    CredentialScope,
    CredentialStatus,
    CredentialType,
    Direction,
    EntryMethod,
    VehicleType,
    VisitType,
)


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
    credential_scope: CredentialScope
    expires_at: Optional[datetime] = None
    visitor_id: Optional[int] = None
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
    visitor_id: Optional[int] = None
    entry_method: EntryMethod
    credential_value: str
    gate_name: str
    direction: Direction
    access: AccessResult
    timestamp: datetime


class VisitorCreate(BaseModel):
    name: str
    phone: str
    host_resident_id: int
    visit_type: VisitType
    purpose: Optional[str] = None
    valid_until: Optional[datetime] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[VehicleType] = None


class VisitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    host_resident_id: int
    visit_type: VisitType
    purpose: Optional[str] = None
    valid_from: datetime
    valid_until: datetime
    vehicle_number: Optional[str] = None
    otp_code: str
    otp_expires_at: datetime
    otp_verified: bool
    otp_verified_at: Optional[datetime] = None
    created_at: datetime


class VerifyOTPRequest(BaseModel):
    otp_code: str
    gate_name: str = "MAIN_GATE"
    direction: Direction = Direction.IN


class VerifyOTPResponse(BaseModel):
    access: AccessResult
    message: str
    visitor_name: Optional[str] = None
    host_resident_name: Optional[str] = None
