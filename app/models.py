import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class VehicleType(str, enum.Enum):
    CAR = "CAR"
    BIKE = "BIKE"


class CredentialType(str, enum.Enum):
    FASTAG = "FASTAG"
    RFID = "RFID"


class CredentialStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class CredentialScope(str, enum.Enum):
    RESIDENT = "RESIDENT"
    VISITOR = "VISITOR"


class VisitType(str, enum.Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"


class EntryMethod(str, enum.Enum):
    RFID = "RFID"
    OTP = "OTP"
    DELIVERY = "DELIVERY"
    STAFF = "STAFF"


class DeliverySource(str, enum.Enum):
    ANNOUNCED = "ANNOUNCED"  # resident told us to expect it
    WALK_IN = "WALK_IN"      # courier turned up unannounced; guard logged it


class DeliveryStatus(str, enum.Enum):
    EXPECTED = "EXPECTED"                    # announced; waiting for the courier
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # unexpected arrival; resident must decide
    APPROVED = "APPROVED"                    # resident approved the unexpected arrival
    ADMITTED = "ADMITTED"                    # guard let the courier in
    DENIED = "DENIED"                        # resident denied, or guard refused
    CANCELLED = "CANCELLED"                  # resident/admin cancelled it
    EXPIRED = "EXPIRED"                      # window passed / nobody answered in time


class DeliveryRuleAction(str, enum.Enum):
    ALLOW = "ALLOW"                  # let this platform in without asking me
    LEAVE_AT_GATE = "LEAVE_AT_GATE"  # security takes the parcel; courier does not come up
    DENY = "DENY"                    # never admit this platform
    # (no rule = the guard asks the resident, as before)


class SosStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class BillStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class ComplaintStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class StaffRole(str, enum.Enum):
    MAID = "MAID"
    DRIVER = "DRIVER"
    SECURITY = "SECURITY"
    COOK = "COOK"
    GARDENER = "GARDENER"
    OTHER = "OTHER"


class StaffStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class UserRole(str, enum.Enum):
    RESIDENT = "RESIDENT"
    GUARD = "GUARD"
    ADMIN = "ADMIN"


class Direction(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class AccessResult(str, enum.Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class Resident(Base):
    __tablename__ = "residents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    apartment_no = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicles = relationship("Vehicle", back_populates="resident")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=True)
    vehicle_number = Column(String, nullable=False, unique=True)
    vehicle_type = Column(SAEnum(VehicleType), nullable=False)

    resident = relationship("Resident", back_populates="vehicles")
    credentials = relationship("VehicleCredential", back_populates="vehicle")


class Visitor(Base):
    __tablename__ = "visitors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    host_resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    visit_type = Column(SAEnum(VisitType), nullable=False)
    purpose = Column(String, nullable=True)
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_until = Column(DateTime, nullable=False)
    vehicle_number = Column(String, nullable=True)
    otp_code = Column(String, nullable=False)
    otp_expires_at = Column(DateTime, nullable=False)
    otp_verified = Column(Boolean, nullable=False, default=False)
    otp_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)
    # Optional photo the guard took at the gate (file under uploads/visitors).
    photo_path = Column(String, nullable=True)
    photo_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    host_resident = relationship("Resident")
    vehicle_credential = relationship(
        "VehicleCredential", back_populates="visitor", uselist=False
    )


class VehicleCredential(Base):
    __tablename__ = "vehicle_credentials"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    credential_type = Column(SAEnum(CredentialType), nullable=False)
    credential_value = Column(String, nullable=False, unique=True, index=True)
    status = Column(SAEnum(CredentialStatus), nullable=False, default=CredentialStatus.ACTIVE)
    credential_scope = Column(
        SAEnum(CredentialScope), nullable=False, default=CredentialScope.RESIDENT
    )
    expires_at = Column(DateTime, nullable=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id"), nullable=True)
    issued_date = Column(DateTime, default=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="credentials")
    visitor = relationship("Visitor", back_populates="vehicle_credential")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    host_resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    source = Column(SAEnum(DeliverySource), nullable=False)
    platform = Column(String, nullable=True)       # e.g. Amazon, Swiggy
    courier_name = Column(String, nullable=True)   # unknown for announced deliveries
    courier_phone = Column(String, nullable=True)
    description = Column(String, nullable=True)    # parcel note, e.g. "Laptop box"
    # Announced deliveries: the window the resident expects it in (naive UTC).
    expected_from = Column(DateTime, nullable=True)
    expected_until = Column(DateTime, nullable=True)
    status = Column(SAEnum(DeliveryStatus), nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow)  # when announced / logged
    decided_at = Column(DateTime, nullable=True)   # resident's approve/deny time
    admitted_at = Column(DateTime, nullable=True)  # when the guard let them in
    leave_at_gate = Column(Boolean, nullable=False, default=False)  # security takes the parcel
    rule_applied = Column(String, nullable=True)   # e.g. "ALLOW rule: Swiggy"
    parcel_photo_path = Column(String, nullable=True)
    admitted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    host_resident = relationship("Resident")

    @property
    def has_parcel_photo(self) -> bool:
        return bool(self.parcel_photo_path)


class DeliveryRule(Base):
    """A resident's standing instruction for a platform (e.g. always allow Swiggy)."""
    __tablename__ = "delivery_rules"
    __table_args__ = (UniqueConstraint("resident_id", "platform_key", name="uq_rule_resident_platform"),)

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False, index=True)
    platform = Column(String, nullable=False)       # as typed, for display
    platform_key = Column(String, nullable=False)   # lower-case, for matching
    action = Column(SAEnum(DeliveryRuleAction), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    resident = relationship("Resident")


class MaintenanceBill(Base):
    __tablename__ = "maintenance_bills"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    billing_month = Column(String, nullable=False)  # "YYYY-MM"
    amount_due = Column(Float, nullable=False)
    due_date = Column(DateTime, nullable=False)
    status = Column(SAEnum(BillStatus), nullable=False, default=BillStatus.PENDING)
    paid_at = Column(DateTime, nullable=True)
    payment_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    resident = relationship("Resident")


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    category = Column(String, nullable=True)
    description = Column(String, nullable=False)
    status = Column(SAEnum(ComplaintStatus), nullable=False, default=ComplaintStatus.OPEN)
    raised_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(String, nullable=True)
    # Server-generated filename of an optional photo under the uploads
    # folder (never a client-supplied name or path).
    image_path = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)   # e.g. "Plumber Raju"
    assigned_at = Column(DateTime, nullable=True)

    resident = relationship("Resident")

    @property
    def has_image(self) -> bool:
        return bool(self.image_path)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False)
    # Set when role == RESIDENT: links this login to their Resident record.
    # NULL for GUARD/ADMIN accounts, which aren't residents.
    # Several logins may share one resident record (family members).
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Bumped on password change/reset/deactivation so older tokens stop working.
    token_version = Column(Integer, nullable=False, default=0)
    must_change_password = Column(Boolean, nullable=False, default=False)
    last_login_at = Column(DateTime, nullable=True)

    resident = relationship("Resident")

    @property
    def apartment_no(self):
        """Convenience for API responses: the linked resident's flat number."""
        return self.resident.apartment_no if self.resident is not None else None



class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    role = Column(SAEnum(StaffRole), nullable=False)
    # Nullable: security guards are typically employed by the society itself,
    # not by one resident. House help / drivers / cooks / gardeners are
    # usually employed by a specific resident.
    employed_by_resident_id = Column(Integer, ForeignKey("residents.id"), nullable=True)
    # Aadhaar (government ID) is never stored in plaintext: only a SHA-256
    # hash (for exact-match dedup lookups) and the last 4 digits (for human
    # display/verification) are persisted. The raw number is discarded by
    # the API layer immediately after hashing and is never returned by any
    # response.
    aadhaar_hash = Column(String, nullable=False, unique=True, index=True)
    aadhaar_last4 = Column(String(4), nullable=False)
    aadhaar_consent_at = Column(DateTime, nullable=True)  # when consent to hold the ID was recorded
    credential_value = Column(String, nullable=False, unique=True, index=True)
    status = Column(SAEnum(StaffStatus), nullable=False, default=StaffStatus.ACTIVE)
    # NULL = permanent staff; set for a temporary/contract worker.
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    employed_by = relationship("Resident")


class EntryLog(Base):
    __tablename__ = "entry_logs"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)
    credential_id = Column(Integer, ForeignKey("vehicle_credentials.id"), nullable=True)
    visitor_id = Column(Integer, ForeignKey("visitors.id"), nullable=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=True)
    staff_id = Column(Integer, ForeignKey("staff.id"), nullable=True)
    recurring_visitor_id = Column(Integer, ForeignKey("recurring_visitors.id"), nullable=True)
    # Who performed the action (guard/admin at the gate, resident for a denial).
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    entry_method = Column(SAEnum(EntryMethod), nullable=False, default=EntryMethod.RFID)
    credential_value = Column(String, nullable=False)
    gate_name = Column(String, nullable=False, default="MAIN_GATE")
    direction = Column(SAEnum(Direction), nullable=False, default=Direction.IN)
    access = Column(SAEnum(AccessResult), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    actor = relationship("User", foreign_keys=[actor_user_id])
    vehicle = relationship("Vehicle", foreign_keys=[vehicle_id])
    visitor = relationship("Visitor", foreign_keys=[visitor_id])
    delivery = relationship("Delivery", foreign_keys=[delivery_id])
    staff = relationship("Staff", foreign_keys=[staff_id])
    recurring_visitor = relationship("RecurringVisitor", foreign_keys=[recurring_visitor_id])


class Invite(Base):
    """One-time code an admin hands to a resident so they can create their login."""
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    resident = relationship("Resident")


class RecurringVisitor(Base):
    """A pre-approved repeat visitor (milkman, tutor, regular cab): one code
    that works on the chosen weekdays inside a daily time window."""
    __tablename__ = "recurring_visitors"

    id = Column(Integer, primary_key=True, index=True)
    host_resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    purpose = Column(String, nullable=True)
    days = Column(String, nullable=False)            # "0,2,4" = Mon, Wed, Fri
    start_minute = Column(Integer, nullable=False)   # society-local minutes after midnight
    end_minute = Column(Integer, nullable=False)
    valid_until = Column(DateTime, nullable=True)    # naive UTC; NULL = no end date
    otp_code = Column(String, nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_entry_at = Column(DateTime, nullable=True)

    host_resident = relationship("Resident")


class ComplaintComment(Base):
    __tablename__ = "complaint_comments"

    id = Column(Integer, primary_key=True, index=True)
    complaint_id = Column(Integer, ForeignKey("complaints.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_name = Column(String, nullable=False)
    author_role = Column(String, nullable=False)
    body = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    ref_type = Column(String, nullable=True)
    ref_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)


class Notice(Base):
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    pinned = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)


class NoticeRead(Base):
    __tablename__ = "notice_reads"
    __table_args__ = (UniqueConstraint("notice_id", "user_id", name="uq_notice_user"),)

    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(Integer, ForeignKey("notices.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    read_at = Column(DateTime, default=datetime.utcnow)


class SosAlert(Base):
    __tablename__ = "sos_alerts"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    kind = Column(String, nullable=False, default="OTHER")   # MEDICAL / FIRE / INTRUDER / OTHER
    message = Column(String, nullable=True)
    status = Column(SAEnum(SosStatus), nullable=False, default=SosStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    note = Column(String, nullable=True)

    resident = relationship("Resident")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String, nullable=True)
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
