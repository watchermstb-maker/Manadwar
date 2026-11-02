"""Environment-driven settings, checked once at import.

MANADWAR_ENV=development  -> relaxed (demo data, API docs, random dev secret if none is set)
anything else (default)   -> production rules: the app refuses to start without a real
                             JWT_SECRET_KEY, and demo seeding is blocked.
"""
import hashlib
import hmac
import os
import secrets
import sys

from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("MANADWAR_ENV", "production").strip().lower()
IS_DEV = ENV in ("development", "dev", "demo")

_PLACEHOLDERS = {
    "", "change-this-to-a-random-secret-before-real-use",
    "dev-only-insecure-secret-change-before-real-use", "secret", "changeme",
}


def _load_secret() -> str:
    raw = os.getenv("JWT_SECRET_KEY", "").strip()
    lowered = raw.lower()
    weak = (
        raw in _PLACEHOLDERS or len(raw) < 32 or len(set(raw)) < 8
        or any(word in lowered for word in ("change-this", "change-me", "changeme", "insecure", "your-secret", "placeholder"))
    )
    if not weak:
        return raw
    if IS_DEV:
        print(
            "WARNING: JWT_SECRET_KEY is missing or weak, so a random secret is used for this run "
            "(everyone is signed out whenever the server restarts). Set a real one in .env.",
            file=sys.stderr,
        )
        return secrets.token_urlsafe(48)
    raise RuntimeError(
        "JWT_SECRET_KEY is missing, too short (< 32 characters) or still the placeholder. "
        "Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\"  and put it in .env.\n"
        "For a local demo you can instead add  MANADWAR_ENV=development  to .env."
    )


SECRET_KEY = _load_secret()


def _load_aadhaar_key() -> bytes:
    raw = os.getenv("AADHAAR_HASH_KEY", "").strip()
    if raw:
        return raw.encode("utf-8")
    if IS_DEV:
        return b"dev-only-aadhaar-key"
    return hmac.new(SECRET_KEY.encode("utf-8"), b"aadhaar-v1", hashlib.sha256).digest()


AADHAAR_KEY = _load_aadhaar_key()

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
# Gate staff work long shifts and cannot be signed out mid-shift.
GUARD_TOKEN_EXPIRE_MINUTES = int(os.getenv("GUARD_JWT_EXPIRE_MINUTES", "720"))

DOCS_ENABLED = IS_DEV or os.getenv("ENABLE_DOCS") == "1"
