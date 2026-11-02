"""Society-local time helpers.

The database stores naive UTC. Anything that depends on "today" or "what time
is it at the society" (staff attendance days, recurring-visitor windows,
the "expected today" list) is worked out in society-local time. India has no
daylight saving, so a fixed offset is enough; change it with
SOCIETY_UTC_OFFSET_MINUTES in .env (default 330 = UTC+05:30).
"""
import os
from datetime import date, datetime, timedelta

OFFSET = timedelta(minutes=int(os.getenv("SOCIETY_UTC_OFFSET_MINUTES", "330")))


def to_local(utc_dt: datetime) -> datetime:
    return utc_dt + OFFSET


def local_now() -> datetime:
    return datetime.utcnow() + OFFSET


def local_today() -> date:
    return local_now().date()


def local_day_bounds_utc(day: date):
    """[start, end) of a society-local calendar day, as naive UTC datetimes."""
    start_local = datetime(day.year, day.month, day.day)
    return start_local - OFFSET, start_local - OFFSET + timedelta(days=1)


def month_bounds_utc(year: int, month: int):
    start_local = datetime(year, month, 1)
    nxt = datetime(year + (month == 12), (month % 12) + 1, 1)
    return start_local - OFFSET, nxt - OFFSET


def minutes_of_day(local_dt: datetime) -> int:
    return local_dt.hour * 60 + local_dt.minute
