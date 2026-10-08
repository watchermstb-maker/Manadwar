from fastapi import FastAPI

from .database import Base, engine
from .routers import rfid

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ManaDwar - Access Control API",
    description="RFID vehicle access control for a smart-community gate system.",
    version="1.0.0",
)

app.include_router(rfid.router)
