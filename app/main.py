from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, check_schema, engine
from .routers import auth, deliveries, maintenance, rfid, staff, visitors

Base.metadata.create_all(bind=engine)
check_schema()

app = FastAPI(
    title="ManaDwar - Access Control API",
    description=(
        "RFID vehicle access control, OTP visitor entry, delivery announcements, "
        "maintenance/complaints, general staff (house help/driver/"
        "security) access, and JWT-based authentication with ADMIN/GUARD/"
        "RESIDENT roles, for a smart-community gate system."
    ),
    version="7.0.1",
)
app.include_router(auth.router)
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
