"""First-run setup for a REAL society: creates the first admin, no demo data.

    python -m app.setup --name "Your Name" --email you@example.com

You are asked for the password (it is not echoed). The admin then adds
residents, vehicles, RFID tags and guards from the Admin console.
"""
import argparse
import getpass
import sys

from .auth import hash_password
from .database import Base, SessionLocal, engine
from .models import User, UserRole
from .security import validate_password


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the first ManaDwar admin account.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Avoid this on shared machines; you will be asked if omitted.")
    args = parser.parse_args(argv)

    email = args.email.strip().lower()
    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("The passwords do not match.", file=sys.stderr)
            return 1
    try:
        validate_password(password, email)
    except ValueError as exc:
        print(f"Password rejected: {exc}", file=sys.stderr)
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            print("An account with that email already exists.", file=sys.stderr)
            return 1
        db.add(User(name=args.name.strip()[:80], email=email, password_hash=hash_password(password), role=UserRole.ADMIN))
        db.commit()
    finally:
        db.close()
    print(f"Admin account created for {email}. Start the server and sign in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
