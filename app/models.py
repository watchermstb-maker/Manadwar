import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float
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

    host_resident = relationship("Resident")


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
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=True, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    entry_method = Column(SAEnum(EntryMethod), nullable=False, default=EntryMethod.RFID)
    credential_value = Column(String, nullable=False)
    gate_name = Column(String, nullable=False, default="MAIN_GATE")
    direction = Column(SAEnum(Direction), nullable=False, default=Direction.IN)
    access = Column(SAEnum(AccessResult), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
