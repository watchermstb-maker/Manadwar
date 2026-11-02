# ManaDwar — Access Control Backend

A prototype smart-community gate access system: RFID/FASTag vehicle entry,
OTP visitor entry, delivery announcements, community/flat complaints (with
photos), and general staff access (house help/driver/security), with login and
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
  visitor-scoped credential). The OTP is **entry-only and reusable**: it
  works for every entry during the visit window, so a visitor can leave and
  come back several times in a day. Exits are not tracked and need no OTP.
  The guard can search hosts by name or flat number when registering.
- **Deliveries (v7.0)**: residents **announce** what they expect (platform,
  note, time window). The guard sees the list at the gate and taps
  **Let in** when the courier arrives. If nobody announced it, the guard
  logs an **unexpected arrival** and the resident approves or denies it
  from their portal. Open requests expire on their own (announced ones at
  the end of the window, unexpected ones after 2 hours). Admins get a
  summary and searchable history, and can approve/deny/cancel on a
  resident's behalf.
- **Complaints**: categories such as Parking, Cleaning, Lift, Garbage,
  Water, Electricity, Noise, Security, Other. Residents can attach one photo
  (JPG/PNG/WebP, up to 5 MB, stored in the `uploads/` folder). Admins view,
  search, filter, start and resolve complaints. (Maintenance **bills** are
  hidden from the screens; the backend endpoints and data are still there.)
- **General staff**: register house help/drivers/security/cooks/gardeners
  with a gate ID-card credential; Aadhaar is hashed on registration (only
  the last 4 digits are ever stored or shown); verify at the gate; block/
  unblock; optional expiry for temporary/contract staff.
- **Authentication & roles**: JWT login with three roles — **admin**,
  **guard**, **resident** — enforced on every endpoint (see "Roles &
  permissions" below). Passwords are bcrypt-hashed.
- **Web UI** (single page, vanilla JS), different per role: admins and
  guards get the dark gate-terminal console (Vehicle, Visitor, Delivery,
  Staff tabs; admins also get Deliveries overview, Complaints, and full
  Staff Directory control with search); residents get a simpler portal to
  register visitors, announce deliveries, and raise complaints with photos.

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
never alters an existing table's columns. **Upgrading from an older
version (v7.0 changed the deliveries table and complaints gained photos):
you must do this.** On startup the app checks the schema and tells you if
the database is out of date. Delete `manadwar.db` and re-seed:

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
| Announce a delivery | for anyone | no | **own flat only** |
| Log an unexpected delivery, let in / refuse | yes | yes | no |
| Approve/deny an unexpected delivery | any | no | **own flat only** |
| Cancel an announced delivery | any | no | **own only** |
| Delivery summary and history overview | yes | no | no |
| Register visitors | for anyone | for anyone | **own flat only** |
| See visitors / deliveries | all | all | **own only** |
| Raise a complaint (with photo) | for anyone | no | **own only** |
| View complaints, update status | yes | no | **own only** (view) |
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
an `otp_code`, then `POST /verify-otp` with that code → granted, and
again on every later entry until `valid_until` (exits are not tracked; an
`OUT` direction is rejected).

**Delivery** — a resident calls `POST /deliveries/announce` with a
`platform` and an `expected_from` / `expected_until` window → `EXPECTED`.
At the gate the guard calls `POST /deliveries/{id}/admit` → `ADMITTED`
(or `/refuse`). For a courier nobody announced:
`POST /deliveries/walk-in` → `AWAITING_APPROVAL`, the resident answers
with `POST /deliveries/{id}/decision` `{"approve": true}`, then the guard
admits it. `POST /deliveries/{id}/cancel` withdraws an open one;
`GET /deliveries?needs_action=true&q=amazon` lists what is waiting.
`GET /deliveries/summary` (admin) gives the counts. The old
`POST /deliveries` with `approval_mode` no longer exists.

**Complaints** — `POST /complaints` with a `category` and `description`,
then `POST /complaints/{id}/image` (multipart) to attach a photo;
`POST /complaints/{id}/status` to move it OPEN → IN_PROGRESS → RESOLVED.

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
- No real payment gateway — the (hidden) bill endpoints only record a
  reference string, no money moves.
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
  uploads/               Complaint photos (created on first upload; git-ignored)
    routers/
      auth.py            /auth/register, /auth/login, /auth/me
      rfid.py            Vehicle credentials + /verify-rfid
      visitors.py        Visitor registration + /verify-otp
      deliveries.py      Announced / unexpected deliveries, admit, refuse
      maintenance.py     Complaints + photos (bills API kept, unused by the UI)
      staff.py           General staff registration + /verify-staff
    static/
      index.html         Frontend: login + guard/admin console + resident portal
```

## Version history

| Tag | What changed |
|---|---|
| v6.0 | JWT login, three roles, resident portal |
| v6.1 | Entry-only reusable visitor OTP, host search, bills hidden, complaint categories, staff search |
| v6.2 | Complaint photos (uploads folder), startup schema check |
| v6.2.1 | Fix: long-term visitor registration from the browser (timezone-aware dates) |
| v7.0 | Delivery redesign: residents announce, guard matches, resident approves unexpected couriers, admin overview |
| v7.0.1 | Phone fix: wide tables scroll sideways inside their card so action buttons are never cut off |
