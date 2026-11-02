from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import DOCS_ENABLED
from .database import Base, check_schema, engine
from .routers import (
    admin, attendance, auth, deliveries, maintenance, notices, notifications,
    resident, rfid, sos, staff, visitors,
)

VERSION = "9.0.0"

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
    version=VERSION,
    # The interactive API docs are for development; production serves no docs.
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

# Largest request we accept (photos are capped at 5 MB; JSON bodies are far smaller).
MAX_BODY_BYTES = 6 * 1024 * 1024

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data: blob:; media-src 'self' blob:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)


@app.middleware("http")
async def protect(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request is too large."})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        response.headers.setdefault("Content-Security-Policy", _CSP)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


for module in (auth, admin, rfid, visitors, deliveries, maintenance, staff, attendance,
               notifications, notices, sos, resident):
    app.include_router(module.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/app/")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "version": VERSION}
