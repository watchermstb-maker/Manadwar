"""Seed script: populates a fresh database with demo data.

Run with:  python -m app.seed
"""
from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import (
    CredentialStatus,
    CredentialType,
    Resident,
    Staff,
    StaffRole,
    StaffStatus,
    User,
    UserRole,
    Vehicle,
    VehicleCredential,
    VehicleType,
)
from .utils import hash_aadhaar

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

        # Demo-only Aadhaar numbers -- fictional, 12 digits each, hashed
        # immediately like any real registration would be.
        maid_hash, maid_last4 = hash_aadhaar("111122223333")
        security_hash, security_last4 = hash_aadhaar("444455556666")
        driver_hash, driver_last4 = hash_aadhaar("777788889999")

        s1 = Staff(
            name="Lakshmi", phone="9876500010", role=StaffRole.MAID,
            employed_by_resident_id=r1.id,
            aadhaar_hash=maid_hash, aadhaar_last4=maid_last4,
            credential_value="TEST-STAFF-001", status=StaffStatus.ACTIVE,
        )
        s2 = Staff(
            name="Mohan", phone="9876500011", role=StaffRole.SECURITY,
            employed_by_resident_id=None,
            aadhaar_hash=security_hash, aadhaar_last4=security_last4,
            credential_value="TEST-STAFF-002", status=StaffStatus.ACTIVE,
        )
        s3 = Staff(
            name="Ravi", phone="9876500012", role=StaffRole.DRIVER,
            employed_by_resident_id=r2.id,
            aadhaar_hash=driver_hash, aadhaar_last4=driver_last4,
            credential_value="BLOCKED-STAFF-999", status=StaffStatus.BLOCKED,
        )
        db.add_all([s1, s2, s3])
        db.commit()

        # Demo login accounts -- one per role, so the software pilot has
        # something to log in with on day one. Change these passwords
        # (or delete these accounts) before any real-world use.
        u1 = User(
            name="Society Admin", email="admin@manadwar.test",
            password_hash=hash_password("admin123"), role=UserRole.ADMIN,
        )
        u2 = User(
            name="Gate Guard", email="guard@manadwar.test",
            password_hash=hash_password("guard123"), role=UserRole.GUARD,
        )
        u3 = User(
            name="Arun Kumar", email="arun@manadwar.test",
            password_hash=hash_password("resident123"), role=UserRole.RESIDENT,
            resident_id=r1.id,
        )
        u4 = User(
            name="Priya Menon", email="priya@manadwar.test",
            password_hash=hash_password("resident123"), role=UserRole.RESIDENT,
            resident_id=r2.id,
        )
        db.add_all([u1, u2, u3, u4])
        db.commit()

        print("Seed complete.")
        print()
        print("Demo login accounts:")
        print("  Admin:    admin@manadwar.test    / admin123")
        print("  Guard:    guard@manadwar.test     / guard123")
        print("  Resident: arun@manadwar.test      / resident123  (Arun Kumar, A-101)")
        print("  Resident: priya@manadwar.test     / resident123  (Priya Menon, B-204)")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
