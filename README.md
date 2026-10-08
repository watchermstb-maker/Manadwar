# ManaDwar — Access Control Backend (Phase 4: + Maintenance)

A prototype smart-community gate access system: RFID vehicle entry, OTP
visitor entry, delivery approval, and maintenance (bills + complaints).

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
copy .env.example .env         # Windows
# cp .env.example .env         # macOS/Linux

python -m app.seed
uvicorn app.main:app --reload
```

- Demo UI (Vehicle + Visitor only so far): http://127.0.0.1:8000/
- Swagger docs: http://127.0.0.1:8000/docs

## If you're re-running a newer version over an older checkout

`Base.metadata.create_all()` only ever **creates missing tables** — it
never alters an existing table's columns. If you're updating from an
older copy of this project, delete `manadwar.db` first, then re-seed:

```bash
del manadwar.db      # Windows
# rm manadwar.db     # macOS/Linux
python -m app.seed
uvicorn app.main:app --reload
```

## Trying maintenance

- `POST /maintenance/bills` to create a bill;
  `POST /maintenance/bills/{id}/pay` to pay it.
- `POST /complaints` to raise one;
  `POST /complaints/{id}/status` to move it through
  OPEN → IN_PROGRESS → RESOLVED.
- Bills past their due date are flipped to `OVERDUE` automatically the
  next time `GET /maintenance/bills` is called (no scheduler — it's
  checked lazily, at read time).

Note: the demo UI at `/app/` does not have Delivery or Maintenance tabs
yet — those are API-only in this phase. Use `/docs` to try them.

## What this project intentionally does NOT include

- No authentication/login.
- No database migrations tool — delete `manadwar.db` to apply schema
  changes.
- No real SMS gateway — OTPs are returned directly in the response.
- No real payment gateway — "paying" a bill just records a reference
  string.
- No real FASTag/NETC bank or toll integration.
