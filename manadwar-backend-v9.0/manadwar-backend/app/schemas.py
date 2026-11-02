import re
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .models import (
    AccessResult,
    BillStatus,
    ComplaintStatus,
    CredentialScope,
    CredentialStatus,
    CredentialType,
    DeliveryRuleAction,
    DeliverySource,
    DeliveryStatus,
    Direction,
    EntryMethod,
    SosStatus,
    StaffRole,
    StaffStatus,
    UserRole,
    VehicleType,
    VisitType,
)
from .security import validate_password


def _to_naive_utc(value: datetime) -> datetime:
    """The database stores naive UTC datetimes. Browsers send timezone-aware
    ISO strings (trailing Z, or an offset like +05:30); convert those to UTC
    and drop the tzinfo so they compare safely with datetime.utcnow()."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# Use for every datetime a client can SEND (not for ones we return).
UtcDateTime = Annotated[datetime, AfterValidator(_to_naive_utc)]


# ---------------------------------------------------------------------------
# Input limits. Everything a client can send is bounded here, on the server.
# ---------------------------------------------------------------------------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Medium = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Platform = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


def _clean_phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not re.fullmatch(r"\+?\d{10,15}", cleaned):
        raise ValueError("Phone must be 10 to 15 digits (a leading + is allowed).")
    return cleaned


Phone = Annotated[str, AfterValidator(_clean_phone)]


def _clean_vehicle(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip().upper())
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 \-]{3,14}", cleaned):
        raise ValueError("Vehicle number must be 4 to 15 letters, digits, spaces or hyphens.")
    return cleaned


VehicleNumber = Annotated[str, AfterValidator(_clean_vehicle)]

# Light email check (no extra dependency, and accepts the demo ".test" addresses).
Email = Annotated[str, StringConstraints(
    strip_whitespace=True, to_lower=True, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
)]


def _blank_to_none(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


# ---------------------------------------------------------------------------
# Residents / vehicles / credentials
# ---------------------------------------------------------------------------

class ResidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    apartment_no: str
    phone: Optional[str] = None   # hidden (null) for guards: they only need name + flat


class ResidentCreate(BaseModel):
    name: Name
    apartment_no: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    phone: Optional[Phone] = None

    _blank = field_validator("phone", mode="before")(_blank_to_none)


class ResidentUpdate(BaseModel):
    name: Optional[Name] = None
    apartment_no: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]] = None
    phone: Optional[Phone] = None

    _blank = field_validator("phone", mode="before")(_blank_to_none)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resident_id: Optional[int] = None
    vehicle_number: str
    vehicle_type: VehicleType


class VehicleCreate(BaseModel):
    resident_id: Optional[int] = None
    vehicle_number: VehicleNumber
    vehicle_type: VehicleType = VehicleType.CAR


class VehicleUpdate(BaseModel):
    resident_id: Optional[int] = None
    vehicle_number: Optional[VehicleNumber] = None
    vehicle_type: Optional[VehicleType] = None


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


class CredentialCreate(BaseModel):
    vehicle_id: int
    credential_type: CredentialType = CredentialType.RFID
    # Leave empty to have the server generate one (e.g. RFID-1A2B3C4D).
    credential_value: Optional[Code] = None
    expires_at: Optional[UtcDateTime] = None

    _blank = field_validator("credential_value", mode="before")(_blank_to_none)


class CredentialUpdate(BaseModel):
    status: Optional[CredentialStatus] = None
    expires_at: Optional[UtcDateTime] = None
    clear_expiry: bool = False


class VerifyRFIDRequest(BaseModel):
    credential_value: Code
    gate_name: Annotated[str, StringConstraints(max_length=40)] = "MAIN_GATE"
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
    recurring_visitor_id: Optional[int] = None
    actor_user_id: Optional[int] = None
    entry_method: EntryMethod
    credential_value: str
    gate_name: str
    direction: Direction
    access: AccessResult
    timestamp: datetime
    # Added in v8.1: who did it and who/what it was for, ready to display.
    actor_name: Optional[str] = None
    subject: Optional[str] = None
    resident_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Visitors
# ---------------------------------------------------------------------------

class VisitorCreate(BaseModel):
    name: Name
    phone: Phone
    host_resident_id: int
    visit_type: VisitType
    purpose: Optional[Short] = None
    # When the visit starts (default: now). Lets a resident plan ahead.
    valid_from: Optional[UtcDateTime] = None
    # SHORT_TERM: optional end (at most 24 h after the start; default 24 h).
    # LONG_TERM: required (at most 90 days after the start).
    valid_until: Optional[UtcDateTime] = None
    vehicle_number: Optional[VehicleNumber] = None
    vehicle_type: Optional[VehicleType] = None

    _blank = field_validator("purpose", "vehicle_number", mode="before")(_blank_to_none)


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
    cancelled_at: Optional[datetime] = None
    status: str = "ACTIVE"          # SCHEDULED / ACTIVE / EXPIRED / CANCELLED
    has_photo: bool = False
    host_name: Optional[str] = None
    host_apartment: Optional[str] = None


class VerifyOTPRequest(BaseModel):
    otp_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    gate_name: Annotated[str, StringConstraints(max_length=40)] = "MAIN_GATE"
    direction: Direction = Direction.IN


class VerifyOTPResponse(BaseModel):
    access: AccessResult
    message: str
    visitor_name: Optional[str] = None
    host_resident_name: Optional[str] = None
    host_apartment: Optional[str] = None
    visitor_id: Optional[int] = None      # lets the gate attach a photo to this visitor
    vehicle_number: Optional[str] = None  # the guard can compare it with the vehicle at the gate
    recurring: bool = False


# ---------------------------------------------------------------------------
# Recurring (pre-approved) visitors
# ---------------------------------------------------------------------------

class RecurringCreate(BaseModel):
    host_resident_id: Optional[int] = None   # admin only; residents always use their own
    name: Name
    phone: Phone
    purpose: Optional[Short] = None
    days: List[int] = Field(min_length=1, max_length=7)   # 0 = Monday ... 6 = Sunday
    start_time: Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")] = "06:00"
    end_time: Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")] = "20:00"
    valid_until: Optional[UtcDateTime] = None

    _blank = field_validator("purpose", mode="before")(_blank_to_none)

    @field_validator("days")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be numbers 0 (Monday) to 6 (Sunday).")
        return sorted(set(v))

    @model_validator(mode="after")
    def _times(self):
        for label, value in (("start_time", self.start_time), ("end_time", self.end_time)):
            h, m = int(value[:2]), int(value[3:])
            if h > 23 or m > 59:
                raise ValueError(f"{label} must be a valid HH:MM time.")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time.")
        return self


class RecurringOut(BaseModel):
    id: int
    host_resident_id: int
    host_name: Optional[str] = None
    name: str
    phone: str
    purpose: Optional[str] = None
    days: List[int]
    start_time: str
    end_time: str
    valid_until: Optional[datetime] = None
    otp_code: str
    is_active: bool
    created_at: datetime
    last_entry_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------

class DeliveryAnnounce(BaseModel):
    """A resident (or admin on their behalf) telling us what to expect."""
    host_resident_id: int
    platform: Platform  # e.g. Amazon, Swiggy, Flipkart
    description: Optional[Short] = None
    expected_from: UtcDateTime
    expected_until: UtcDateTime
    leave_at_gate: bool = False   # security takes the parcel; courier does not come up

    _blank = field_validator("description", mode="before")(_blank_to_none)


class DeliveryWalkIn(BaseModel):
    """Guard logging a courier who turned up without being announced."""
    host_resident_id: int
    platform: Optional[Platform] = None
    courier_name: Optional[Name] = None
    courier_phone: Optional[Phone] = None
    description: Optional[Short] = None

    _blank = field_validator("platform", "courier_name", "courier_phone", "description", mode="before")(_blank_to_none)


class DeliveryDecision(BaseModel):
    approve: bool


class DeliveryGateAction(BaseModel):
    gate_name: Annotated[str, StringConstraints(max_length=40)] = "MAIN_GATE"


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    host_resident_id: int
    source: DeliverySource
    platform: Optional[str] = None
    courier_name: Optional[str] = None
    courier_phone: Optional[str] = None
    description: Optional[str] = None
    expected_from: Optional[datetime] = None
    expected_until: Optional[datetime] = None
    status: DeliveryStatus
    requested_at: datetime
    decided_at: Optional[datetime] = None
    admitted_at: Optional[datetime] = None
    leave_at_gate: bool = False
    rule_applied: Optional[str] = None
    has_parcel_photo: bool = False


class DeliverySummary(BaseModel):
    pending_now: dict      # current counts: EXPECTED / AWAITING_APPROVAL / APPROVED
    last_24h: dict         # counts by final status over the last 24 hours (+ total)
    top_platforms_24h: list


class DeliveryRuleCreate(BaseModel):
    resident_id: Optional[int] = None   # admin only
    platform: Platform
    action: DeliveryRuleAction


class DeliveryRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resident_id: int
    platform: str
    action: DeliveryRuleAction
    created_at: datetime


# ---------------------------------------------------------------------------
# Maintenance: bills + complaints
# ---------------------------------------------------------------------------

class MaintenanceBillCreate(BaseModel):
    resident_id: int
    billing_month: Annotated[str, StringConstraints(max_length=7)]  # "YYYY-MM"
    amount_due: float = Field(gt=0, le=10_000_000)
    due_date: UtcDateTime


class MaintenanceBillPay(BaseModel):
    payment_reference: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]] = None


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
    description: Long

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
    resolution_notes: Optional[Medium] = None


class ComplaintAssign(BaseModel):
    assigned_to: Name


class ComplaintCommentCreate(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ComplaintCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    complaint_id: int
    author_name: str
    author_role: str
    body: str
    created_at: datetime


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
    assigned_to: Optional[str] = None
    assigned_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# General Staff (house help / driver / security / cook / gardener)
# ---------------------------------------------------------------------------

class StaffCreate(BaseModel):
    name: Name
    phone: Phone
    role: StaffRole
    employed_by_resident_id: Optional[int] = None
    # 12-digit Aadhaar number. Accepted here only to be turned into a keyed
    # one-way fingerprint -- never stored in plaintext and never echoed back.
    aadhaar_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=12, max_length=20)]
    # The admin must confirm the staff member agreed to the stated purpose.
    consent_given: bool = False
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
    credential_value: Code
    gate_name: Annotated[str, StringConstraints(max_length=40)] = "MAIN_GATE"
    direction: Direction = Direction.IN


class VerifyStaffResponse(BaseModel):
    access: AccessResult
    message: str
    staff_name: Optional[str] = None
    role: Optional[StaffRole] = None
    employer_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Authentication and user management
# ---------------------------------------------------------------------------

Password = Annotated[str, AfterValidator(lambda v: validate_password(v))]


class UserRegister(BaseModel):
    """Self-service sign-up with an invite code from the society admin.

    The invite decides which resident record the new login belongs to, so
    nobody can claim a flat they were not invited to.
    """
    invite_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=40)]
    name: Name
    email: Email
    password: str

    @model_validator(mode="after")
    def _pw(self):
        validate_password(self.password, self.email)
        return self


class ChangePassword(BaseModel):
    current_password: Annotated[str, StringConstraints(max_length=128)]
    new_password: Password


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
    must_change_password: bool = False
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    """Admin creates a GUARD or ADMIN login (residents sign up with an invite)."""
    name: Name
    email: Email
    role: UserRole
    # Leave empty to have a one-time password generated and shown once.
    password: Optional[str] = None

    @model_validator(mode="after")
    def _rules(self):
        if self.role == UserRole.RESIDENT:
            raise ValueError("Residents sign up with an invite code; create GUARD or ADMIN accounts here.")
        if self.password:
            validate_password(self.password, self.email)
        return self


class UserCreated(UserOut):
    temporary_password: Optional[str] = None


class PasswordReset(BaseModel):
    password: Optional[str] = None

    @model_validator(mode="after")
    def _pw(self):
        if self.password:
            validate_password(self.password)
        return self


class ActiveUpdate(BaseModel):
    is_active: bool


class InviteCreate(BaseModel):
    resident_id: int


class InviteOut(BaseModel):
    id: int
    code: str
    resident_id: int
    resident_label: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None
    status: str   # ACTIVE / USED / EXPIRED


class Token(BaseModel):
    access_token: str
    token_type: str


# ---------------------------------------------------------------------------
# Notifications, notices, SOS, audit
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    title: str
    body: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class NoticeCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    pinned: bool = False
    expires_at: Optional[UtcDateTime] = None


class NoticeOut(BaseModel):
    id: int
    title: str
    body: str
    pinned: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    created_by: Optional[str] = None
    read: bool = False
    read_count: Optional[int] = None      # admin only: residents who have read it
    reader_total: Optional[int] = None    # admin only: resident logins that could read it


SOS_KINDS = ["MEDICAL", "FIRE", "INTRUDER", "OTHER"]


class SosCreate(BaseModel):
    kind: str = "OTHER"
    message: Optional[Short] = None

    _blank = field_validator("message", mode="before")(_blank_to_none)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        v = (v or "OTHER").strip().upper()
        if v not in SOS_KINDS:
            raise ValueError("kind must be one of: " + ", ".join(SOS_KINDS))
        return v


class SosResolve(BaseModel):
    note: Optional[Short] = None

    _blank = field_validator("note", mode="before")(_blank_to_none)


class SosOut(BaseModel):
    id: int
    resident_id: int
    resident_name: Optional[str] = None
    apartment_no: Optional[str] = None
    phone: Optional[str] = None   # shown to gate staff and admin only
    kind: str
    message: Optional[str] = None
    status: SosStatus
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    note: Optional[str] = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime
