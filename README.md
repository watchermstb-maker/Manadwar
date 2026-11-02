# ManaDwar — Smart Apartment Access Control

A software pilot for apartment gate access: RFID/FASTag vehicle entry, OTP and
QR visitor passes, deliveries (with per-resident rules and parcel photos),
house staff and attendance, complaints, a notice board, SOS alerts and
role-based screens for **admin**, **guard** and **resident**.

It runs on FastAPI + SQLAlchemy (SQLite by default) with a vanilla-JS single
page frontend. RFID hardware is not required — tags are typed or scanned in as
text, so the whole flow can be piloted in software first.

> Version **9.0**. Upgrading from an older checkout? Read
> [Upgrading](#upgrading-from-an-older-version) first (the database must be
> recreated once).

## Contents

1. [Quick start (demo on your laptop)](#quick-start-demo-on-your-laptop)
2. [Real society (production)](#real-society-production)
3. [Demo accounts and data](#demo-accounts-and-data)
4. [What each role can do](#what-each-role-can-do)
5. [Settings (.env)](#settings-env)
6. [HTTPS, phones and the QR scanner](#https-phones-and-the-qr-scanner)
7. [Backups and where the database lives](#backups-and-where-the-database-lives)
8. [Security notes](#security-notes)
9. [Aadhaar and privacy](#aadhaar-and-privacy)
10. [Languages](#languages)
11. [Running the tests](#running-the-tests)
12. [Project structure](#project-structure)
13. [Version history](#version-history)

## Quick start (demo on your laptop)

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env         # Windows   (cp .env.example .env on macOS/Linux)

python -m app.seed             # demo data + demo logins (development mode only)
uvicorn app.main:app --reload
```

`.env.example` ships with `MANADWAR_ENV=development`, which is what allows the
demo seed, the API docs and an automatic temporary secret. Open
<http://127.0.0.1:8000/> for the app and <http://127.0.0.1:8000/docs> for the
API docs (docs are only served in development).

## Real society (production)

Without `MANADWAR_ENV=development` the app is strict: it **refuses to start**
without a real `JWT_SECRET_KEY`, serves no API docs and will not create demo
accounts (so nobody can sign in as `admin123`).

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # paste into .env as JWT_SECRET_KEY
python -m app.setup --name "Your Name" --email you@example.com   # asks for a password, creates the first admin
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then sign in as that admin and, from **People**, add residents, vehicles and
RFID/FASTag tags, create guard logins, and create **invite codes**: a family
member opens the app, taps *Create account*, and enters their code to make
their own resident login (see below).

## Demo accounts and data

`python -m app.seed` creates the following. These passwords are public — never
use the seed for a real society.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@manadwar.test` | `admin123` |
| Guards | `guard@`, `guard2@`, `guard3@`, `guard4@manadwar.test` | `guard123` |
| Residents | `arun@`, `priya@`, `rahul@`, `ananya@`, `karthik@`, `sneha@`, `vikram@manadwar.test` | `resident123` |

- **Residents (7)**: Arun Kumar A-101, Priya Menon B-204, Rahul Sharma C-303,
  Ananya Reddy D-402, Karthik Iyer A-205, Sneha Patil B-110, Vikram Singh C-501.
- **Guards (4)**: Gate Guard, Suresh Babu, Imran Khan, Prakash Rao.
- **Vehicles/tags**: `TEST-RFID-001` (Arun, active), `BLOCKED-RFID-999`
  (Arun, blocked), `TEST-FASTAG-002` (Priya), `TEST-RFID-003` (Rahul),
  `TEST-FASTAG-004` (Ananya), `TEST-RFID-005` (Karthik).
- **House staff (5)**: Lakshmi (Arun's maid, `TEST-STAFF-001`), Mohan (society
  security, `TEST-STAFF-002`), Ravi (Priya's driver, blocked,
  `BLOCKED-STAFF-999`), Savitri (Rahul's cook, `TEST-STAFF-004`), Gopal
  (gardener, `TEST-STAFF-005`).
- **Delivery rules**: Arun lets Swiggy in automatically, Priya has Amazon left
  at the gate, Rahul denies Dunzo.
- **Regular visitors**: Ramu (milk, daily mornings, Arun) and Meera (tutor,
  Mon/Wed/Fri evenings, Priya).
- A welcome notice and one announced Amazon delivery for Arun.

Demo Aadhaar numbers in the seed are fictional.

## What each role can do

**Resident** (portal with Home, Visitors, Deliveries, Complaints, Notices,
My Flat, Account)
- Home: pending approvals, SOS button, vehicles, house staff, recent activity.
- Schedule a visitor for a later time or cancel one; short visits can carry a
  vehicle number; share the OTP over WhatsApp or as a QR pass; see the photo
  the guard took at the gate.
- **Regular visitors** (milkman, tutor, …): a permanent code valid on chosen
  days/hours, pausable.
- **Deliveries**: announce one, approve/deny unexpected couriers, set **rules
  per company** (allow / leave at gate / deny) and view the parcel photo.
- Complaints with a photo, a message thread with the admin, reopen if not fixed.
- Notices from the society with a read receipt; alerts via the bell.
- My Flat: your tags and your house staff's monthly attendance.
- Account: change password, language.

**Guard** (Gate, Today, Staff, Account)
- Verify RFID/FASTag, OTP, QR pass, staff ID card; deliveries; log walk-ins.
- Photo of a visitor at the gate and of a parcel.
- **SOS banner** with siren/voice and Acknowledge / Resolve buttons.
- Today: who is expected, regular visitors, deliveries.
- Sounds (granted / denied) and voice announcements, with a mute button.
- Resident phone numbers are hidden from guards; the visit host is shown by
  name and flat.
- Guard sessions last a full shift (`GUARD_JWT_EXPIRE_MINUTES`, default 12 h).

**Admin** (everything above plus)
- **Dashboard**: live counts, entries per hour, latest gate activity.
- **People**: residents, vehicles and their RFID/FASTag tags (add, edit,
  block, expire), logins (create, reset password, deactivate) and invite codes.
- **Logs**: entry log with search, filters, pagination, CSV export and the
  guard who recorded each entry; audit trail of admin actions.
- **Complaints**: assign to someone, comment, resolve.
- **Notices**: post, pin, expire, delete, and see who has read each one.
- **Attendance**: who is in today, monthly report, CSV.
- Gets a bell alert when someone is guessing OTPs at the gate (10 wrong OTPs in
  5 minutes locks OTP entry for 2 minutes).

### Sign-up and passwords

- Residents create their own account with an **invite code** (`MD-XXXX-XXXX`,
  created by the admin, one use, valid 7 days, at most 5 logins per flat).
  Guard and admin logins are created by the admin only.
- Passwords need 8+ characters with at least one letter and one number (and not a common password or your email). There
  is no email reset: **the admin resets a password** and gives the resident a
  temporary one, which they must change on first sign-in.
- Changing or resetting a password, or deactivating a login, signs that
  person out everywhere at once.
- Repeated wrong passwords lock that email and that IP address for a while.

## Settings (.env)

See `.env.example` for the full annotated list.

| Variable | Meaning | Default |
|---|---|---|
| `MANADWAR_ENV` | `development` relaxes rules for demos | production |
| `JWT_SECRET_KEY` | login-token signing key, 32+ random characters | required in production |
| `AADHAAR_HASH_KEY` | key used to fingerprint Aadhaar numbers | derived from the JWT key |
| `DATABASE_URL` | SQLite file or Postgres URL | `sqlite:///./manadwar.db` |
| `JWT_EXPIRE_MINUTES` | resident/admin session length | 60 (renews silently while the app is open) |
| `GUARD_JWT_EXPIRE_MINUTES` | guard session length | 720 |
| `SOCIETY_UTC_OFFSET_MINUTES` | society time zone | 330 (India) |
| `UPLOAD_DIR` | where photos are stored | `uploads/` |
| `TRUST_PROXY` | `1` only behind a trusted reverse proxy | 0 |
| `ENABLE_DOCS` | `1` to show API docs in production | 0 |
| `ALLOW_DEMO_SEED` | `1` to run the demo seed outside development | unset |

## HTTPS, phones and the QR scanner

Browsers only allow the **live camera** on `localhost` or over HTTPS, and
HTTPS is also what keeps passwords private on the Wi-Fi.

```bash
python -m app.run_https          # self-signed certificate, port 8443, prints the LAN URLs
```

Open the printed `https://<laptop-ip>:8443/` on the phone and accept the
browser's one-time warning (the certificate is self-signed). For a real
deployment, put a proper certificate in front (a reverse proxy such as Caddy or
nginx, with `TRUST_PROXY=1`). Over plain HTTP the guard can still use **Take
photo of QR** or type the OTP.

The app is a normal responsive web page, so it works on phones with no
installation.

## Backups and where the database lives

SQLite files can be corrupted if a cloud-sync folder (OneDrive, Dropbox, Google
Drive) copies them mid-write. Keep the database **outside** such folders, for
example `DATABASE_URL=sqlite:///C:/ManaDwarData/manadwar.db` and
`UPLOAD_DIR=C:/ManaDwarData/uploads`.

```bash
python -m app.backup --dest C:\ManaDwarBackups --keep 14
```

This writes a consistent copy of the database plus a zip of the uploaded
photos into the folder, keeping the newest 14. Schedule it daily (Windows Task
Scheduler or cron). To restore, stop the app and copy the files back.

## Security notes

- Every endpoint is checked for the caller's role; residents only ever see
  their own flat's data.
- Responses carry security headers (CSP with no inline scripts, `nosniff`,
  frame denial, no referrer, HSTS over HTTPS).
- All text inputs have length limits; uploaded photos are checked by content
  (not just file name) and limited to 5 MB.
- Login, invite and OTP guessing are throttled. The throttles are **in
  memory**: they reset when the server restarts and are per process, which is
  fine for a single-server pilot.
- Entry-log CSV exports neutralise spreadsheet formulas.
- Still true: OTPs are shown on screen, not sent by SMS; there is no payment
  gateway and no real FASTag/bank integration (only the tag ID is read).

## Aadhaar and privacy

Staff registration still asks for an Aadhaar number, but the number itself is
never stored. The system keeps only:

- a **keyed hash** (HMAC-SHA-256 with `AADHAAR_HASH_KEY`) to catch duplicates,
- the **last 4 digits** for the ID card, and
- the date the staff member's **consent** was recorded (the form requires a
  consent tick box).

An admin can **erase** the Aadhaar record of a staff member (the hash and last
4 digits are overwritten). Changing `AADHAAR_HASH_KEY` means staff registered
earlier would have to be re-entered to be matched for duplicates.

> This is a technical safeguard, not legal advice. Before collecting
> Aadhaar or other personal data from real people, check the current rules
> (Aadhaar Act and the Digital Personal Data Protection Act) with a lawyer or
> your society's advisor. Many societies avoid Aadhaar altogether and use a
> different ID; if you do, simply leave it out.

## Languages

The interface has a language switcher: **English, Hindi, Telugu**. The Hindi
and Telugu text is a first draft and **needs review by a native speaker**
before real use. Strings live in `app/static/ext-core.js` (the `I18N` table);
anything untranslated falls back to English. Adding another language means
adding one block there.

## Upgrading from an older version

`Base.metadata.create_all()` only creates *missing* tables; it never alters
existing ones, and v9 changes many. On startup the app detects an out-of-date
database and tells you. For the demo, recreate it:

```bash
del manadwar.db        # Windows  (rm manadwar.db on macOS/Linux)
python -m app.seed
uvicorn app.main:app --reload
```

Also make sure `.env` has `MANADWAR_ENV=development` (demo) or a real
`JWT_SECRET_KEY` (production) — otherwise the app will not start. A database
with real data from an older version cannot be migrated automatically (there
is no migrations tool); export what you need first.

## Running the tests

The tests are scripts that start a fresh server on a throw-away database and
call it over HTTP (API checks) or drive it with a real browser (Playwright).
They are not bundled in this repository.

## Project structure

```
manadwar-backend/
  app/
    main.py              App, routers, security headers, static mount
    config.py            Environment settings, JWT secret rules
    auth.py              Password hashing, JWT, role dependencies
    security.py          Throttling, password rules
    database.py          Engine/session, schema check
    models.py            ORM models and enums
    schemas.py           Request/response schemas (with input limits)
    utils.py             OTP, entry logging, Aadhaar fingerprint
    timeutil.py          Society-local time helpers
    uploads.py           Safe photo storage
    audit.py notify.py logview.py
    seed.py              Demo data (development only)
    setup.py             First admin for a real society
    backup.py            Database + photo backups
    run_https.py         Self-signed HTTPS for phone testing
    routers/
      auth.py admin.py resident.py rfid.py visitors.py deliveries.py
      maintenance.py staff.py attendance.py notices.py notifications.py sos.py
    static/
      index.html         Page shell and styles
      app.js             Core app (login, gate console, forms)
      ext-core.js        Languages, sounds, bell, account, complaint threads
      ext-resident.js    Resident home, notices, flat, rules, regular visitors
      ext-staff.js       Guard/admin pages: dashboard, people, logs, notices, attendance
      qrcode-lib.js jsqr-lib.js   QR generator / reader (MIT / Apache-2.0)
```

## Version history

| Tag | What changed |
|---|---|
| v6.0 | JWT login, three roles, resident portal |
| v6.1 | Entry-only reusable visitor OTP, host search, bills hidden, complaint categories, staff search |
| v6.2 | Complaint photos, startup schema check |
| v6.2.1 | Fix: long-term visitor registration from the browser (timezone-aware dates) |
| v7.0 | Delivery redesign: residents announce, guard matches, resident approves unexpected couriers, admin overview |
| v7.0.1 | Phone fix: wide tables scroll inside their card |
| v7.1 | WhatsApp button and QR visitor pass |
| v7.2 | Guard QR scanner (live camera + photo fallback) |
| v9.0 | Big release: invite-code sign-up, admin People/Logs/Notices/Attendance screens, fail-safe secrets and first-run setup, login lockout, scheduled visits, regular visitors, delivery rules and parcel photos, SOS, notice board, staff attendance, notifications bell, guard shift sessions with sound/voice, Aadhaar keyed hash + consent, HTTPS helper, security headers, backups, change password, Hindi/Telugu, 7 demo residents and 4 guards |
