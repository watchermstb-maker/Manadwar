import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./manadwar.db")

# A SQLite file inside a synced folder (OneDrive, Dropbox, Google Drive) can be
# locked or duplicated by the sync client while the app is writing to it.
if DATABASE_URL.startswith("sqlite") and "onedrive" in os.path.abspath(DATABASE_URL.replace("sqlite:///", "", 1)).lower():
    print(
        "WARNING: the database file is inside a OneDrive folder. Set DATABASE_URL in .env to a path "
        "outside it, e.g. sqlite:///C:/manadwar-data/manadwar.db (create the folder first).",
        file=__import__("sys").stderr,
    )

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


def check_schema():
    """Fail early, with a clear message, if the database file predates the code.

    create_all() only creates missing tables; it never adds columns to
    existing ones. Without this check, an old manadwar.db shows up as
    confusing 500 errors ("no such column") at request time instead.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    problems = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [col.name for col in table.columns if col.name not in existing]
        if missing:
            problems.append(f"{table.name}: {', '.join(missing)}")
    if problems:
        raise RuntimeError(
            "Your database file is from an older version of ManaDwar (missing columns -> "
            + "; ".join(problems)
            + "). Stop the server, delete manadwar.db, run `python -m app.seed`, then start again."
        )
