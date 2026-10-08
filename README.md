# ManaDwar — Access Control Backend

A prototype smart-community gate access system: RFID/FASTag vehicle entry,
OTP visitor entry, delivery approval, maintenance (bills + complaints), and
general staff access (house help/driver/security).

This is a **deliberately simple prototype**, not a production system: no
authentication, no database migrations tool, no real SMS/payment gateway
integration. See "What this project intentionally does NOT include" below.

## Feature set

- **RFID vehicle access**: register vehicles + RFID/FASTag credentials,
  verify a credential at the gate, auto-expire credentials past their
  `expires_at`, full entry log.
- **OTP visitor entry**: register a visitor (short-term walk-in, 24h
  validity, no vehicle; or long-term, with an optional vehicle +
  visitor-scoped credential), verify their OTP at the gate.
- **Delivery approval**: register a delivery request as either
  auto-approved or pending manual approval; approve/deny pending ones.
- **Maintenance**: create/pay maintenance bills (auto-flip to OVERDUE
  past due date), raise/track complaints (OPEN → IN_PROGRESS → RESOLVED).
- **General staff**: register house help/drivers/security/cooks/gardeners
  with a gate ID-card credential; Aadhaar is hashed on registration (only
  the last 4 digits are ever stored or shown); verify at the gate; block/
  unblock; optional expiry for temporary/contract staff.
- **Demo gate-terminal UI**: a single-page dark "terminal" frontend
  covering all of the above — Vehicle, Visitor, Delivery, and Staff tabs,
  plus Maintenance and Staff Directory cards.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env         # Windows
# cp .env.example .env         # macOS/Linux

python -m app.seed             # creates manadwar.db with demo data
uvicorn app.main:app --reload
```

Then open:
- **Demo UI**: http://127.0.0.1:8000/ (redirects to `/app/`)
- **Swagger API docs**: http://127.0.0.1:8000/docs

## If you're re-running a newer version over an older checkout

`Base.metadata.create_all()` only ever **creates missing tables** — it
never alters an existing table's columns. If you're updating from an
older copy of this project, delete `manadwar.db` before running, then
re-seed:

```bash
del manadwar.db      # Windows
# rm manadwar.db     # macOS/Linux
python -m app.seed
uvicorn app.main:app --reload
```

## Seeded demo data

- Residents: Arun Kumar (A-101), Priya Menon (B-204)
- Vehicles: `KA-01-AB-1234` (CAR, Arun), `KA-05-CD-5678` (BIKE, Priya)
- Credentials:
  - `TEST-RFID-001` — ACTIVE (Arun's car)
  - `TEST-FASTAG-002` — ACTIVE (Priya's bike)
  - `BLOCKED-RFID-999` — BLOCKED (Arun's car, for testing denial)
- Staff: Lakshmi (MAID, employed by Arun) `TEST-STAFF-001` — ACTIVE;
  Mohan (SECURITY, society-employed) `TEST-STAFF-002` — ACTIVE;
  Ravi (DRIVER, employed by Priya) `BLOCKED-STAFF-999` — BLOCKED

## Trying each feature

**Vehicle access** — `POST /verify-rfid` with
`{"credential_value": "TEST-RFID-001"}` → granted;
`{"credential_value": "BLOCKED-RFID-999"}` → denied (blocked).

**Visitor entry** — `POST /visitors` to register a visitor and get back
an `otp_code`, then `POST /verify-otp` with that code → granted (once;
a second attempt is denied as already-used).

**Delivery** — `POST /deliveries` with `"approval_mode": "AUTO"` →
instantly approved; with `"approval_mode": "MANUAL"` → stays `PENDING`
until `POST /deliveries/{id}/decision`.

**Maintenance** — `POST /maintenance/bills` to create a bill,
`POST /maintenance/bills/{id}/pay` to pay it; `POST /complaints` to raise
one, `POST /complaints/{id}/status` to move it through
OPEN → IN_PROGRESS → RESOLVED.

**General staff** — `POST /staff` with a name, role, optional employing
resident, and a 12-digit `aadhaar_number` (hashed immediately, never
stored or returned raw) → get back an auto-generated `credential_value`
(e.g. `STAFF-A1B2C3D4`); `POST /verify-staff` with that code → granted;
`POST /staff/{id}/status` with `{"status": "BLOCKED"}` to revoke access.

All of the above also works through the demo UI at `/app/`.

## What this project intentionally does NOT include

Scoped out deliberately so the prototype stays focused on the
access-control logic itself:

- No authentication/login — any client can call any endpoint.
- No database migrations tool (e.g. Alembic) — schema changes require
  deleting and recreating `manadwar.db`.
- No real SMS gateway — OTPs are returned directly in the API response /
  shown in the UI, not actually texted anywhere.
- No real payment gateway — "paying" a bill just records a reference
  string, no money moves.
- No real FASTag/NETC bank or toll integration — only a locally-readable
  RFID/FASTag identifier (EPC) is used; no owner bank or wallet data is
  ever read or stored.
- No production security hardening (rate limiting, HTTPS enforcement,
  input sanitization beyond Pydantic's validation, etc.)
- No raw Aadhaar storage — staff registration hashes the Aadhaar number
  (SHA-256) immediately and only persists that hash plus the last 4
  digits; the full number is never written to the database or returned
  by any API response.

## Project structure

```
manadwar-backend/
  app/
    main.py              FastAPI app, routers, static frontend mount
    database.py          SQLAlchemy engine/session setup
    models.py            All ORM models + enums
    schemas.py           All Pydantic request/response schemas
    utils.py             Shared helpers (OTP generation, entry logging)
    seed.py              Demo data seed script
    routers/
      rfid.py            Vehicle credentials + /verify-rfid
      visitors.py        Visitor registration + /verify-otp
      deliveries.py      Delivery requests + approval decisions
      maintenance.py     Maintenance bills + complaints
      staff.py           General staff registration + /verify-staff
    static/
      index.html         Demo gate-terminal frontend (vanilla JS)
```
