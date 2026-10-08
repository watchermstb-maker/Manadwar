# ManaDwar — Access Control Backend (Phase 3: + Delivery Approval)

A prototype smart-community gate access system: RFID vehicle entry, OTP
visitor entry, and delivery approval (auto or manual).

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

## Trying delivery approval

- `POST /deliveries` with `"approval_mode": "AUTO"` → instantly approved
  and logged.
- `POST /deliveries` with `"approval_mode": "MANUAL"` → stays `PENDING`
  until `POST /deliveries/{id}/decision` with `{"approve": true}` or
  `{"approve": false}`.
- `GET /deliveries` to see all requests.

Note: the demo UI at `/app/` does not have a Delivery tab yet — delivery
approval is API-only in this phase. Use `/docs` to try it.
