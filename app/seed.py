"""Seed script: populates a fresh database with DEMO data.

Run with:  python -m app.seed

Demo accounts have well-known passwords, so this refuses to run unless
MANADWAR_ENV=development (or ALLOW_DEMO_SEED=1). For a real society use
`python -m app.setup` to create the first admin instead.
"""
import os
from datetime import datetime, timedelta

from .auth import hash_password
from .config import IS_DEV
from .database import Base, SessionLocal, engine
from .models import (
    CredentialStatus,
    CredentialType,
    Delivery,
    DeliveryRule,
    DeliveryRuleAction,
    DeliverySource,
    DeliveryStatus,
    Notice,
    RecurringVisitor,
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

RESIDENTS = [
    # name, flat, phone, login email
    ("Arun Kumar", "A-101", "9876500001", "arun@manadwar.test"),
    ("Priya Menon", "B-204", "9876500002", "priya@manadwar.test"),
    ("Rahul Sharma", "C-303", "9876500003", "rahul@manadwar.test"),
    ("Ananya Reddy", "D-402", "9876500004", "ananya@manadwar.test"),
    ("Karthik Iyer", "A-205", "9876500005", "karthik@manadwar.test"),
    ("Sneha Patil", "B-110", "9876500006", "sneha@manadwar.test"),
    ("Vikram Singh", "C-501", "9876500007", "vikram@manadwar.test"),
]

GUARDS = [
    ("Gate Guard", "guard@manadwar.test"),
    ("Suresh Babu", "guard2@manadwar.test"),
    ("Imran Khan", "guard3@manadwar.test"),
    ("Prakash Rao", "guard4@manadwar.test"),
]


def seed():
    if not (IS_DEV or os.getenv("ALLOW_DEMO_SEED") == "1"):
        raise SystemExit(
            "Refusing to create demo accounts (admin123, guard123, ...) outside development.\n"
            "  * For a demo/laptop run: add  MANADWAR_ENV=development  to .env and run this again.\n"
            "  * For a real society:    python -m app.setup --name \"Your Name\" --email you@example.com"
        )
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Resident).count() > 0:
            print("Database already has data -- skipping seed.")
            return

        residents = [Resident(name=n, apartment_no=f, phone=p) for n, f, p, _ in RESIDENTS]
        db.add_all(residents)
        db.commit()
        r1, r2, r3, r4, r5, r6, r7 = residents

        vehicles = [
            Vehicle(resident_id=r1.id, vehicle_number="KA-01-AB-1234", vehicle_type=VehicleType.CAR),
            Vehicle(resident_id=r2.id, vehicle_number="KA-05-CD-5678", vehicle_type=VehicleType.BIKE),
            Vehicle(resident_id=r3.id, vehicle_number="KA-03-EF-4321", vehicle_type=VehicleType.CAR),
            Vehicle(resident_id=r4.id, vehicle_number="KA-02-GH-8765", vehicle_type=VehicleType.CAR),
            Vehicle(resident_id=r5.id, vehicle_number="KA-04-JK-1111", vehicle_type=VehicleType.BIKE),
        ]
        db.add_all(vehicles)
        db.commit()
        v1, v2, v3, v4, v5 = vehicles

        db.add_all([
            VehicleCredential(vehicle_id=v1.id, credential_type=CredentialType.RFID,
                              credential_value="TEST-RFID-001", status=CredentialStatus.ACTIVE),
            VehicleCredential(vehicle_id=v2.id, credential_type=CredentialType.FASTAG,
                              credential_value="TEST-FASTAG-002", status=CredentialStatus.ACTIVE),
            VehicleCredential(vehicle_id=v1.id, credential_type=CredentialType.RFID,
                              credential_value="BLOCKED-RFID-999", status=CredentialStatus.BLOCKED),
            VehicleCredential(vehicle_id=v3.id, credential_type=CredentialType.RFID,
                              credential_value="TEST-RFID-003", status=CredentialStatus.ACTIVE),
            VehicleCredential(vehicle_id=v4.id, credential_type=CredentialType.FASTAG,
                              credential_value="TEST-FASTAG-004", status=CredentialStatus.ACTIVE),
            VehicleCredential(vehicle_id=v5.id, credential_type=CredentialType.RFID,
                              credential_value="TEST-RFID-005", status=CredentialStatus.ACTIVE),
        ])
        db.commit()

        # Demo-only Aadhaar numbers -- fictional, 12 digits each. They are
        # fingerprinted immediately, exactly like a real registration.
        def staff(name, phone, role, employer, aadhaar, cred, status=StaffStatus.ACTIVE):
            h, last4 = hash_aadhaar(aadhaar)
            return Staff(
                name=name, phone=phone, role=role, employed_by_resident_id=employer,
                aadhaar_hash=h, aadhaar_last4=last4, aadhaar_consent_at=datetime.utcnow(),
                credential_value=cred, status=status,
            )

        db.add_all([
            staff("Lakshmi", "9876500010", StaffRole.MAID, r1.id, "111122223333", "TEST-STAFF-001"),
            staff("Mohan", "9876500011", StaffRole.SECURITY, None, "444455556666", "TEST-STAFF-002"),
            staff("Ravi", "9876500012", StaffRole.DRIVER, r2.id, "777788889999", "BLOCKED-STAFF-999", StaffStatus.BLOCKED),
            staff("Savitri", "9876500013", StaffRole.COOK, r3.id, "999900001111", "TEST-STAFF-004"),
            staff("Gopal", "9876500014", StaffRole.GARDENER, None, "888800002222", "TEST-STAFF-005"),
        ])
        db.commit()

        # Demo login accounts. Change these passwords (or never seed) for real use.
        users = [User(name="Society Admin", email="admin@manadwar.test",
                      password_hash=hash_password("admin123"), role=UserRole.ADMIN)]
        for name, email in GUARDS:
            users.append(User(name=name, email=email, password_hash=hash_password("guard123"), role=UserRole.GUARD))
        for res, (_n, _f, _p, email) in zip(residents, RESIDENTS):
            users.append(User(name=res.name, email=email, password_hash=hash_password("resident123"),
                              role=UserRole.RESIDENT, resident_id=res.id))
        db.add_all(users)
        db.commit()

        now = datetime.utcnow()
        # One announced delivery so the delivery screens aren't empty on day one.
        db.add(Delivery(
            host_resident_id=r1.id, source=DeliverySource.ANNOUNCED, platform="Amazon",
            description="Laptop box", expected_from=now, expected_until=now + timedelta(hours=8),
            status=DeliveryStatus.EXPECTED,
        ))
        # A few standing delivery rules.
        for res, platform, action in (
            (r1, "Swiggy", DeliveryRuleAction.ALLOW),
            (r2, "Amazon", DeliveryRuleAction.LEAVE_AT_GATE),
            (r3, "Dunzo", DeliveryRuleAction.DENY),
        ):
            db.add(DeliveryRule(resident_id=res.id, platform=platform, platform_key=platform.lower(), action=action))
        # Regular visitors: a milkman every morning, a tutor on Mon/Wed/Fri evenings.
        db.add(RecurringVisitor(host_resident_id=r1.id, name="Ramu (milk)", phone="9876500020", purpose="Milk delivery",
                                days="0,1,2,3,4,5,6", start_minute=5 * 60, end_minute=8 * 60, otp_code="555111"))
        db.add(RecurringVisitor(host_resident_id=r2.id, name="Meera (tutor)", phone="9876500021", purpose="Tuition",
                                days="0,2,4", start_minute=17 * 60, end_minute=19 * 60, otp_code="555222"))
        admin = users[0]
        db.add(Notice(title="Welcome to ManaDwar",
                      body="Gate passes, deliveries and complaints now live here. Use the bell for alerts and the SOS button in an emergency.",
                      pinned=True, created_by_user_id=admin.id))
        db.commit()

        print("Seed complete (7 residents, 4 guards, 1 admin).")
        print()
        print("Demo login accounts:")
        print("  Admin:     admin@manadwar.test                     / admin123")
        print("  Guards:    guard@ / guard2@ / guard3@ / guard4@manadwar.test   / guard123")
        print("  Residents: arun@ priya@ rahul@ ananya@ karthik@ sneha@ vikram@manadwar.test / resident123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
