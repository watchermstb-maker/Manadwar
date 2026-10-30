from datetime import datetime, timezone
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator

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
    UserRole,
    VehicleType,
    VisitType,
)


def _to_naive_utc(value: datetime) -> datetime:
    """The database stores naive UTC datetimes. Browsers send timezone-aware
    ISO strings (trailing Z, or an offset like +05:30); convert those to UTC
    and drop the tzinfo so they compare safely with datetime.utcnow()."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# Use for every datetime a client can SEND (not for ones we return).
UtcDateTime = Annotated[datetime, AfterValidator(_to_naive_utc)]


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
    valid_until: Optional[UtcDateTime] = None
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
    due_date: UtcDateTime


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


COMPLAINT_CATEGORIES = [
    "Parking", "Cleaning", "Plumbing", "Electrical", "Lift",
    "Security", "Noise", "Water Supply", "Garbage", "Other",
]


class ComplaintCreate(BaseModel):
    resident_id: int
    category: Optional[str] = None
    description: str

    @field_validator("category")
    @classmethod
    def _known_category(cls, value):
        if value is None or value == "":
            return None
        for allowed in COMPLAINT_CATEGORIES:
            if value.strip().lower() == allowed.lower():
                return allowed  # normalise capitalisation
        raise ValueError("category must be one of: " + ", ".join(COMPLAINT_CATEGORIES))


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
    has_image: bool = False


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
    expires_at: Optional[UtcDateTime] = None  # NULL = permanent staff


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


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class UserRegister(BaseModel):
    """Self-service registration -- always creates a RESIDENT account.

    GUARD and ADMIN accounts are not self-service in this pilot; they're
    created via the seed script / directly by whoever administers the
    deployment, to keep gate-operation access deliberate.
    """
    name: str
    email: str
    password: str
    resident_id: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole
    resident_id: Optional[int] = None
    apartment_no: Optional[str] = None
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str
