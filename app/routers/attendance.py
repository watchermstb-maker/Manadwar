"""Staff attendance, worked out from gate scans (no manual register).

A staff member is "present" on a society-local day when they have at least one
granted IN scan that day. First IN and last OUT give arrival/departure times
(OUT scans are optional; without one the day still counts as present).
"""
import csv
import io
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models, timeutil
from ..audit import audit
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(tags=["Staff attendance"])

_admin_only = require_roles(models.UserRole.ADMIN)
_gate_staff = require_roles(models.UserRole.GUARD, models.UserRole.ADMIN)


def _parse_month(month: Optional[str]):
    if not month:
        today = timeutil.local_today()
        return today.year, today.month
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=400, detail="month must look like 2026-11.")
    year, mon = int(month[:4]), int(month[5:])
    if not (1 <= mon <= 12 and 2000 <= year <= 2100):
        raise HTTPException(status_code=400, detail="month must look like 2026-11.")
    return year, mon


def _days(db: Session, staff_ids, start_utc: datetime, end_utc: datetime) -> Dict[int, Dict[date, dict]]:
    """staff_id -> local date -> {first_in, last_out, inside}"""
    EL = models.EntryLog
    rows = (
        db.query(EL.staff_id, EL.direction, EL.timestamp)
        .filter(EL.staff_id.in_(list(staff_ids) or [-1]), EL.access == models.AccessResult.GRANTED,
                EL.timestamp >= start_utc, EL.timestamp < end_utc)
        .order_by(EL.timestamp, EL.id).all()
    )
    out: Dict[int, Dict[date, dict]] = {}
    for staff_id, direction, ts in rows:
        local = timeutil.to_local(ts)
        day = out.setdefault(staff_id, {}).setdefault(local.date(), {"first_in": None, "last_out": None, "inside": False})
        if direction == models.Direction.IN:
            if day["first_in"] is None:
                day["first_in"] = local
            day["inside"] = True
        else:
            day["last_out"] = local
            day["inside"] = False
    return out


def _fmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%H:%M") if dt else None


def _month_rows(db: Session, staff: List[models.Staff], year: int, month: int):
    start, end = timeutil.month_bounds_utc(year, month)
    days = _days(db, [s.id for s in staff], start, end)
    result = []
    for s in staff:
        mine = days.get(s.id, {})
        entries = []
        for d in sorted(mine):
            info = mine[d]
            hours = None
            if info["first_in"] and info["last_out"] and info["last_out"] > info["first_in"]:
                hours = round((info["last_out"] - info["first_in"]).total_seconds() / 3600, 1)
            entries.append({
                "date": d.isoformat(), "first_in": _fmt(info["first_in"]), "last_out": _fmt(info["last_out"]),
                "hours": hours, "inside": info["inside"],
            })
        employer = s.employed_by
        result.append({
            "staff_id": s.id, "name": s.name, "role": s.role.value, "status": s.status.value,
            "employer": f"{employer.name} ({employer.apartment_no})" if employer else "Society",
            "present_days": len(entries), "days": entries,
        })
    return result


@router.get("/attendance/today")
def attendance_today(db: Session = Depends(get_db), user: models.User = Depends(_gate_staff)):
    """Who has come in today and who is still inside."""
    today = timeutil.local_today()
    start, end = timeutil.local_day_bounds_utc(today)
    ids = [r[0] for r in db.query(models.EntryLog.staff_id).filter(
        models.EntryLog.staff_id.isnot(None), models.EntryLog.timestamp >= start,
        models.EntryLog.timestamp < end).distinct().all()]
    staff = db.query(models.Staff).filter(models.Staff.id.in_(ids or [-1])).all()
    days = _days(db, ids, start, end)
    items = []
    for s in staff:
        info = days.get(s.id, {}).get(today)
        if not info or info["first_in"] is None:
            continue
        employer = s.employed_by
        items.append({
            "staff_id": s.id, "name": s.name, "role": s.role.value,
            "employer": f"{employer.name} ({employer.apartment_no})" if employer else "Society",
            "first_in": _fmt(info["first_in"]), "last_out": _fmt(info["last_out"]), "inside": info["inside"],
        })
    items.sort(key=lambda i: i["first_in"])
    total_active = db.query(models.Staff).filter(models.Staff.status == models.StaffStatus.ACTIVE).count()
    return {"date": today.isoformat(), "present": items, "inside_now": sum(1 for i in items if i["inside"]),
            "active_staff": total_active}


@router.get("/attendance/staff/{staff_id}")
def staff_month(
    staff_id: int,
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    staff = db.query(models.Staff).filter(models.Staff.id == staff_id).first()
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found.")
    if user.role == models.UserRole.RESIDENT:
        if staff.employed_by_resident_id != user.resident_id:
            raise HTTPException(status_code=403, detail="You can only see attendance for your own staff.")
    elif user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You don't have permission to do this.")
    year, mon = _parse_month(month)
    row = _month_rows(db, [staff], year, mon)[0]
    row["month"] = f"{year:04d}-{mon:02d}"
    return row


@router.get("/attendance/my-staff")
def my_staff(
    month: Optional[str] = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles(models.UserRole.RESIDENT)),
):
    year, mon = _parse_month(month)
    staff = db.query(models.Staff).filter(models.Staff.employed_by_resident_id == user.resident_id).order_by(models.Staff.name).all()
    rows = _month_rows(db, staff, year, mon)
    today = timeutil.local_today().isoformat()
    for row in rows:
        row["today"] = next((d for d in row["days"] if d["date"] == today), None)
    return {"month": f"{year:04d}-{mon:02d}", "staff": rows}


@router.get("/attendance/report")
def report(
    month: Optional[str] = None,
    employer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    year, mon = _parse_month(month)
    query = db.query(models.Staff)
    if employer_id is not None:
        query = query.filter(models.Staff.employed_by_resident_id == employer_id)
    staff = query.order_by(models.Staff.name).all()
    rows = _month_rows(db, staff, year, mon)
    return {"month": f"{year:04d}-{mon:02d}", "staff": rows}


def _csv_safe(value) -> str:
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/attendance/export.csv")
def export(
    month: Optional[str] = None,
    employer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_only),
):
    year, mon = _parse_month(month)
    query = db.query(models.Staff)
    if employer_id is not None:
        query = query.filter(models.Staff.employed_by_resident_id == employer_id)
    rows = _month_rows(db, query.order_by(models.Staff.name).all(), year, mon)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["staff", "role", "employer", "date", "first in", "last out", "hours"])
    for r in rows:
        if not r["days"]:
            w.writerow([_csv_safe(r["name"]), r["role"], _csv_safe(r["employer"]), "(no visits)", "", "", ""])
        for d in r["days"]:
            w.writerow([_csv_safe(r["name"]), r["role"], _csv_safe(r["employer"]), d["date"], d["first_in"] or "",
                        d["last_out"] or "", d["hours"] if d["hours"] is not None else ""])
    audit(db, admin, "attendance.export", "staff", None, f"{year:04d}-{mon:02d}")
    return Response(
        content=out.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="manadwar-attendance-{year:04d}-{mon:02d}.csv"'},
    )
