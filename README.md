# ManaDwar — Access Control Backend (Phase 1: RFID Vehicle Access)

A prototype smart-community gate access system. This first phase covers
RFID/FASTag vehicle entry only.

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

Swagger docs: http://127.0.0.1:8000/docs

## Seeded demo data

- Residents: Arun Kumar (A-101), Priya Menon (B-204)
- Vehicles: `KA-01-AB-1234` (CAR), `KA-05-CD-5678` (BIKE)
- Credentials: `TEST-RFID-001` (ACTIVE), `TEST-FASTAG-002` (ACTIVE),
  `BLOCKED-RFID-999` (BLOCKED)

Try `POST /verify-rfid` with `{"credential_value": "TEST-RFID-001"}`.
