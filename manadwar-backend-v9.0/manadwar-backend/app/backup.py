"""Back up the SQLite database (and photo uploads).

    python -m app.backup                 # copies to ./backups
    python -m app.backup --dest D:\\manadwar-backups --keep 30

Uses SQLite's own backup API, so it is safe while the server is running.
Put the backup folder somewhere other than the database folder (and ideally on
another disk or cloud drive).
"""
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from .database import DATABASE_URL
from .uploads import UPLOAD_ROOT


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Back up the ManaDwar database.")
    parser.add_argument("--dest", default="backups")
    parser.add_argument("--keep", type=int, default=14, help="how many backups to keep (default 14)")
    args = parser.parse_args(argv)

    if not DATABASE_URL.startswith("sqlite"):
        print("This helper only handles SQLite. For Postgres use pg_dump.", file=sys.stderr)
        return 1
    source = Path(DATABASE_URL.replace("sqlite:///", "", 1))
    if not source.is_file():
        print(f"Database file not found: {source}", file=sys.stderr)
        return 1

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = dest / f"manadwar-{stamp}.db"
    src, dst = sqlite3.connect(str(source)), sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"Database backed up to {target}")

    if UPLOAD_ROOT.is_dir() and any(UPLOAD_ROOT.rglob("*")):
        archive = shutil.make_archive(str(dest / f"uploads-{stamp}"), "zip", str(UPLOAD_ROOT))
        print(f"Photos backed up to {archive}")

    for pattern in ("manadwar-*.db", "uploads-*.zip"):
        old = sorted(dest.glob(pattern))
        for path in old[: max(0, len(old) - max(1, args.keep))]:
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
