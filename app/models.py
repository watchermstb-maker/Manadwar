import enum
from datetime import datetime

from sqlalchemy import Column, DateTime
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


class VehicleCredential(Base):
    __tablename__ = "vehicle_credentials"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    credential_type = Column(SAEnum(CredentialType), nullable=False)
    credential_value = Column(String, nullable=False, unique=True, index=True)
    status = Column(SAEnum(CredentialStatus), nullable=False, default=CredentialStatus.ACTIVE)
    # NULL = permanent (resident credentials never expire on their own).
    expires_at = Column(DateTime, nullable=True)
    issued_date = Column(DateTime, default=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="credentials")


class EntryLog(Base):
    __tablename__ = "entry_logs"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)
    credential_id = Column(Integer, ForeignKey("vehicle_credentials.id"), nullable=True)
    credential_value = Column(String, nullable=False)
    gate_name = Column(String, nullable=False, default="MAIN_GATE")
    direction = Column(SAEnum(Direction), nullable=False, default=Direction.IN)
    access = Column(SAEnum(AccessResult), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
