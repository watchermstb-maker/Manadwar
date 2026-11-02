"""Password policy, brute-force throttling and small request helpers."""
import os
import re
import threading
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request

# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

_COMMON = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwertyui", "qwerty123", "iloveyou", "admin123456", "letmein123", "welcome123",
    "abcd1234", "abc12345", "11111111", "00000000",
}


def validate_password(password: str, email: str = None) -> str:
    """Return the password if acceptable, else raise ValueError with a clear reason."""
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number.")
    if password.lower() in _COMMON:
        raise ValueError("That password is too common. Choose another.")
    if email and password.lower() == email.lower():
        raise ValueError("Password must not be the same as your email.")
    return password


# ---------------------------------------------------------------------------
# Failure throttling (in memory: fine for the single-process pilot; a restart
# clears it. Use a shared store such as Redis if you ever run several workers.)
# ---------------------------------------------------------------------------

class FailureTracker:
    """Counts failures per key inside a window and locks a key out with
    increasing delays. tiers = [(failures, lock_seconds), ...] ascending."""

    def __init__(self, window_seconds: int, tiers):
        self.window = window_seconds
        self.tiers = sorted(tiers)
        self._lock = threading.Lock()
        self._state: Dict[str, dict] = {}

    def _get(self, key: str, now: float) -> dict:
        st = self._state.get(key)
        if st is None or now - st["last"] > self.window:
            st = {"count": 0, "last": now, "locked_until": 0.0}
            self._state[key] = st
        return st

    def retry_after(self, key: str) -> int:
        """Seconds the key is still locked for (0 = free)."""
        now = time.time()
        with self._lock:
            st = self._state.get(key)
            if st is None:
                return 0
            remaining = st["locked_until"] - now
            return int(remaining) + 1 if remaining > 0 else 0

    def fail(self, key: str) -> Tuple[int, bool]:
        """Record a failure. Returns (count, newly_locked)."""
        now = time.time()
        with self._lock:
            st = self._get(key, now)
            st["count"] += 1
            st["last"] = now
            newly = False
            for threshold, seconds in self.tiers:
                if st["count"] >= threshold and st["locked_until"] <= now:
                    st["locked_until"] = now + seconds
                    newly = True
            return st["count"], newly

    def reset(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# 5 wrong passwords for one email -> 1 min lock, 8 -> 5 min, 12 -> 15 min.
login_by_email = FailureTracker(900, [
    (_int_env("LOGIN_MAX_FAILS", 5), 60), (_int_env("LOGIN_MAX_FAILS", 5) + 3, 300),
    (_int_env("LOGIN_MAX_FAILS", 5) + 7, 900)])
# One address hammering many accounts.
login_by_ip = FailureTracker(900, [(_int_env("LOGIN_MAX_FAILS_PER_IP", 30), 300)])
# Wrong OTP guesses made by one gate account: 10 in 5 minutes -> 2 minute lock.
otp_by_user = FailureTracker(300, [(_int_env("OTP_MAX_FAILS", 10), 120)])
# Wrong invite codes from one address.
invite_by_ip = FailureTracker(900, [(10, 300)])


def client_ip(request: Request) -> str:
    if os.getenv("TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def raise_if_locked(tracker: FailureTracker, key: str, what: str = "attempts") -> None:
    wait = tracker.retry_after(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed {what}. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )
