from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .models import (
    AccessResult,
    ApprovalMode,
    BillStatus,
    ComplaintStatus,
    CredentialScope,
    CredentialStatus,
    CredentialType,
    DeliveryStatus,
    Direction,
    EntryMethod,
    StaffRole,
    StaffStatus,
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
    delivery_id: Optional[int] = None
    staff_id: Optional[int] = None
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


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------

class DeliveryCreate(BaseModel):
    courier_name: str
    courier_phone: Optional[str] = None
    platform: Optional[str] = None
    host_resident_id: int
    purpose: Optional[str] = None
    approval_mode: ApprovalMode


class DeliveryDecision(BaseModel):
    approve: bool
    gate_name: str = "MAIN_GATE"


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    courier_name: str
    courier_phone: Optional[str] = None
    platform: Optional[str] = None
    host_resident_id: int
    purpose: Optional[str] = None
    approval_mode: ApprovalMode
    status: DeliveryStatus
    requested_at: datetime
    decided_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Maintenance: bills + complaints
# ---------------------------------------------------------------------------

class MaintenanceBillCreate(BaseModel):
    resident_id: int
    billing_month: str  # "YYYY-MM"
    amount_due: float
    due_date: datetime


class MaintenanceBillPay(BaseModel):
    payment_reference: Optional[str] = None


class MaintenanceBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resident_id: int
    billing_month: str
    amount_due: float
    due_date: datetime
    status: BillStatus
    paid_at: Optional[datetime] = None
    payment_reference: Optional[str] = None
    created_at: datetime


class ComplaintCreate(BaseModel):
    resident_id: int
    category: Optional[str] = None
    description: str


class ComplaintStatusUpdate(BaseModel):
    status: ComplaintStatus
    resolution_notes: Optional[str] = None


class ComplaintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resident_id: int
    category: Optional[str] = None
    description: str
    status: ComplaintStatus
    raised_at: datetime
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# General Staff (house help / driver / security / cook / gardener)
# ---------------------------------------------------------------------------

class StaffCreate(BaseModel):
    name: str
    phone: str
    role: StaffRole
    employed_by_resident_id: Optional[int] = None
    # 12-digit Aadhaar number. Accepted here only to be hashed immediately --
    # it is never persisted in plaintext and is never echoed back by the API.
    aadhaar_number: str
    expires_at: Optional[datetime] = None  # NULL = permanent staff


class StaffStatusUpdate(BaseModel):
    status: StaffStatus


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: str
    role: StaffRole
    employed_by_resident_id: Optional[int] = None
    credential_value: str
    aadhaar_last4: str
    status: StaffStatus
    expires_at: Optional[datetime] = None
    created_at: datetime


class VerifyStaffRequest(BaseModel):
    credential_value: str
    gate_name: str = "MAIN_GATE"
    direction: Direction = Direction.IN


class VerifyStaffResponse(BaseModel):
    access: AccessResult
    message: str
    staff_name: Optional[str] = None
    role: Optional[StaffRole] = None
    employer_name: Optional[str] = None
