# ManaDwar — Access Control Backend

A prototype smart-community gate access system: RFID/FASTag vehicle entry,
OTP visitor entry, delivery approval, maintenance (bills + complaints), and
general staff access (house help/driver/security), with login and
role-based access (admin / guard / resident).

This is a **deliberately simple prototype** aimed at a single-community
software pilot, not a production system: no database migrations tool, no
real SMS/payment gateway integration, no password reset. See "What this
project intentionally does NOT include" below.

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
- **Authentication & roles**: JWT login with three roles — **admin**,
  **guard**, **resident** — enforced on every endpoint (see "Roles &
  permissions" below). Passwords are bcrypt-hashed.
- **Web UI** (single page, vanilla JS), different per role: admins and
  guards get the dark gate-terminal console (Vehicle, Visitor, Delivery,
  Staff tabs; admins also get Maintenance and full Staff Directory
  control); residents get a simpler portal to register visitors, request
  deliveries, raise complaints, and view/pay their own bills.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env         # Windows
# cp .env.example .env         # macOS/Linux

python -m app.seed             # creates manadwar.db with demo data + demo logins
uvicorn app.main:app --reload
```

Before sharing this with anyone, open `.env` and set `JWT_SECRET_KEY` to
your own random value (it signs login tokens; anyone who knows it can
forge a login). Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Then open:
- **Demo UI**: http://127.0.0.1:8000/ (redirects to `/app/`)
- **Swagger API docs**: http://127.0.0.1:8000/docs

## If you're re-running a newer version over an older checkout

`Base.metadata.create_all()` only ever **creates missing tables** — it
never alters an existing table's columns. **Upgrading to v6.0 from an
older version: you must do this**, because the seed script skips itself
when residents already exist, so an old `manadwar.db` would have no login
accounts and you couldn't sign in. Delete `manadwar.db` and re-seed:

```bash
del manadwar.db      # Windows
# rm manadwar.db     # macOS/Linux
python -m app.seed
uvicorn app.main:app --reload
```

## Seeded demo data

- **Login accounts** (demo only — change or delete before any real use):

  | Role | Email | Password |
  |---|---|---|
  | Admin | `admin@manadwar.test` | `admin123` |
  | Guard | `guard@manadwar.test` | `guard123` |
  | Resident (Arun Kumar, A-101) | `arun@manadwar.test` | `resident123` |
  | Resident (Priya Menon, B-204) | `priya@manadwar.test` | `resident123` |

- Residents: Arun Kumar (A-101), Priya Menon (B-204)
- Vehicles: `KA-01-AB-1234` (CAR, Arun), `KA-05-CD-5678` (BIKE, Priya)
- Credentials:
  - `TEST-RFID-001` — ACTIVE (Arun's car)
  - `TEST-FASTAG-002` — ACTIVE (Priya's bike)
  - `BLOCKED-RFID-999` — BLOCKED (Arun's car, for testing denial)
- Staff: Lakshmi (MAID, employed by Arun) `TEST-STAFF-001` — ACTIVE;
  Mohan (SECURITY, society-employed) `TEST-STAFF-002` — ACTIVE;
  Ravi (DRIVER, employed by Priya) `BLOCKED-STAFF-999` — BLOCKED

## Roles & permissions

| | Admin | Guard | Resident |
|---|---|---|---|
| Verify RFID / OTP / staff ID at the gate | yes | yes | no |
| Entry logs, vehicles, credentials, residents list | yes | yes | no |
| Approve/deny delivery requests | yes | yes | no |
| Register visitors / request deliveries | for anyone | for anyone | **own flat only** |
| See visitors / deliveries | all | all | **own only** |
| Create maintenance bills | yes | no | no |
| Pay a bill | any | no | **own only** |
| Raise a complaint | for anyone | no | **own only** |
| Update complaint status | yes | no | no |
| Register staff, block/unblock staff | yes | no | no |
| View staff directory | yes | read-only | no |

Residents self-register via `POST /auth/register` (needs a `resident_id`
that doesn't already have an account). Guard and admin accounts can't be
self-registered; they're created by whoever runs the deployment (the seed
script, for now).

Using the API directly: `POST /auth/login` takes a **form-encoded** body
(`username` = email, `password`) and returns a token; send it as
`Authorization: Bearer <token>`. In Swagger (`/docs`), use the
**Authorize** button.

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

(With auth on, every call below needs a Bearer token from `/auth/login`
— easiest via the Authorize button in Swagger, or just use the web UI.)

All of the above also works through the web UI at `/app/`.

## What this project intentionally does NOT include

Scoped out deliberately so the prototype stays focused on the
access-control logic itself:

- No password reset, email verification, refresh tokens, or login rate
  limiting. Login tokens last `JWT_EXPIRE_MINUTES` (default 60) and are
  kept in the browser's localStorage. Fine for a trusted pilot; add these
  before exposing it publicly.
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
    auth.py              Password hashing, JWT, role-check dependencies
    database.py          SQLAlchemy engine/session setup
    models.py            All ORM models + enums
    schemas.py           All Pydantic request/response schemas
    utils.py             Shared helpers (OTP generation, entry logging)
    seed.py              Demo data seed script
    routers/
      auth.py            /auth/register, /auth/login, /auth/me
      rfid.py            Vehicle credentials + /verify-rfid
      visitors.py        Visitor registration + /verify-otp
      deliveries.py      Delivery requests + approval decisions
      maintenance.py     Maintenance bills + complaints
      staff.py           General staff registration + /verify-staff
    static/
      index.html         Frontend: login + guard/admin console + resident portal
```
