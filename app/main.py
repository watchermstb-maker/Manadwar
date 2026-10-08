from fastapi import FastAPI

from .database import Base, engine
from .routers import rfid, visitors

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ManaDwar - Access Control API",
    description="RFID vehicle access control and OTP visitor entry for a smart-community gate system.",
    version="2.0.0",
)

app.include_router(rfid.router)
app.include_router(visitors.router)
