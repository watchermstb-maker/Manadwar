"""Seed script: populates a fresh database with demo data.

Run with:  python -m app.seed
"""
from .database import Base, SessionLocal, engine
from .models import CredentialStatus, CredentialType, Resident, Vehicle, VehicleCredential, VehicleType

Base.metadata.create_all(bind=engine)


def seed():
    db = SessionLocal()
    try:
        if db.query(Resident).count() > 0:
            print("Database already has data -- skipping seed.")
            return

        r1 = Resident(name="Arun Kumar", apartment_no="A-101", phone="9876500001")
        r2 = Resident(name="Priya Menon", apartment_no="B-204", phone="9876500002")
        db.add_all([r1, r2])
        db.commit()

        v1 = Vehicle(resident_id=r1.id, vehicle_number="KA-01-AB-1234", vehicle_type=VehicleType.CAR)
        v2 = Vehicle(resident_id=r2.id, vehicle_number="KA-05-CD-5678", vehicle_type=VehicleType.BIKE)
        db.add_all([v1, v2])
        db.commit()

        c1 = VehicleCredential(
            vehicle_id=v1.id, credential_type=CredentialType.RFID,
            credential_value="TEST-RFID-001", status=CredentialStatus.ACTIVE,
        )
        c2 = VehicleCredential(
            vehicle_id=v2.id, credential_type=CredentialType.FASTAG,
            credential_value="TEST-FASTAG-002", status=CredentialStatus.ACTIVE,
        )
        c3 = VehicleCredential(
            vehicle_id=v1.id, credential_type=CredentialType.RFID,
            credential_value="BLOCKED-RFID-999", status=CredentialStatus.BLOCKED,
        )
        db.add_all([c1, c2, c3])
        db.commit()

        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
