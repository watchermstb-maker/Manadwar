from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import deliveries, maintenance, rfid, staff, visitors

Base.metadata.create_all(bind=engine)

# Auto-reseed: on Vercel, /tmp (where the SQLite file lives) is wiped
# whenever a new serverless instance starts, so the demo data would
# otherwise vanish. seed() itself is idempotent -- it checks the DB first
# and skips silently if data already exists -- so this is harmless to run
# on every cold start, and a no-op anywhere the data already persists.
try:
    from .seed import seed

    seed()
except Exception:  # pragma: no cover - never let a seed hiccup break startup
    pass

app = FastAPI(
    title="ManaDwar - Access Control API",
    description=(
        "RFID vehicle access control, OTP visitor entry, delivery approval, "
        "maintenance/complaints, and general staff (house help/driver/"
        "security) access for a smart-community gate system."
    ),
    version="5.0.0",
)
app.include_router(rfid.router)
app.include_router(visitors.router)
app.include_router(deliveries.router)
app.include_router(maintenance.router)
app.include_router(staff.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/app/")
