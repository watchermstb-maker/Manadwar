import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# On Vercel, the project directory is read-only at runtime -- only /tmp is
# writable, and /tmp is wiped whenever a new serverless instance spins up
# (so data doesn't persist long-term there; see app/main.py's auto-seed).
# VERCEL=1 is set automatically by the Vercel runtime, so local/other
# hosting is unaffected unless DATABASE_URL is already set explicitly.
_default_db_url = (
    "sqlite:////tmp/manadwar.db" if os.getenv("VERCEL") else "sqlite:///./manadwar.db"
)
DATABASE_URL = os.getenv("DATABASE_URL", _default_db_url)

# SQLite needs this flag for use with FastAPI's threaded request handling.
# It is ignored by other database backends (e.g. Postgres), so this stays
# safe if DATABASE_URL is later swapped to a Postgres connection string.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
