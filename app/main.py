from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import deliveries, rfid, visitors

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ManaDwar - Access Control API",
    description=(
        "RFID vehicle access control, OTP visitor entry, and delivery "
        "approval for a smart-community gate system."
    ),
    version="3.0.0",
)

app.include_router(rfid.router)
app.include_router(visitors.router)
app.include_router(deliveries.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/app/")
