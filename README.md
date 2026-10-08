# ManaDwar — Access Control Backend (Phase 2: + OTP Visitor Entry)

A prototype smart-community gate access system: RFID vehicle entry plus
OTP-based visitor entry.

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

## Trying it

- **Vehicle**: `POST /verify-rfid` with `{"credential_value": "TEST-RFID-001"}`.
- **Visitor**: `POST /visitors` to register (get back an `otp_code`), then
  `POST /verify-otp` with that code. A second attempt with the same code
  is denied as already-used.
