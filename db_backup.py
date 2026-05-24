"""SQLite backup/restore helpers for local (non-Docker) installs."""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sqlite3
import zipfile
from datetime import UTC, datetime

import config

DBBACKUP_DIR = os.path.join(config.BASE_DIR, "dbbackup")
DB_FILENAME = "bulk_video.db"
RESTORE_ZIP_NAME = "restore.zip"


def uses_sqlite() -> bool:
    import database

    return not database.is_mysql() and not database.is_postgres()


def ensure_dbbackup_dir() -> str:
    os.makedirs(DBBACKUP_DIR, exist_ok=True)
    return DBBACKUP_DIR


def _checkpoint_sqlite(db_path: str) -> None:
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
        conn.commit()
    finally:
        conn.close()


def _remove_wal_shm(db_path: str) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = db_path + suffix
        if os.path.exists(sidecar):
            os.remove(sidecar)


def build_backup_zip_bytes(db_path: str | None = None) -> bytes:
    db_path = db_path or config.DATABASE_PATH
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    _checkpoint_sqlite(db_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, DB_FILENAME)
    return buf.getvalue()


def backup_download_name() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"bulk_video_backup_{stamp}.zip"


def save_backup_to_folder(db_path: str | None = None) -> str:
    ensure_dbbackup_dir()
    out_path = os.path.join(DBBACKUP_DIR, backup_download_name())
    with open(out_path, "wb") as handle:
        handle.write(build_backup_zip_bytes(db_path))
    return out_path


def bundled_seed_db_path() -> str:
    return os.path.join(DBBACKUP_DIR, DB_FILENAME)


def find_restore_zip() -> str | None:
    ensure_dbbackup_dir()
    explicit = os.path.join(DBBACKUP_DIR, RESTORE_ZIP_NAME)
    if os.path.isfile(explicit):
        return explicit

    zips = sorted(
        (
            os.path.join(DBBACKUP_DIR, name)
            for name in os.listdir(DBBACKUP_DIR)
            if name.lower().endswith(".zip")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    return zips[0] if zips else None


def restore_from_zip(zip_path: str, db_path: str | None = None, *, overwrite: bool = False) -> None:
    db_path = db_path or config.DATABASE_PATH
    os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)

    if os.path.exists(db_path) and not overwrite:
        raise FileExistsError(f"Database already exists: {db_path}")

    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".before-restore")

    with zipfile.ZipFile(zip_path, "r") as zf:
        member = next(
            (name for name in zf.namelist() if os.path.basename(name) == DB_FILENAME),
            None,
        )
        if not member:
            raise ValueError(f"No {DB_FILENAME} found in {zip_path}")

        with zf.open(member) as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    _remove_wal_shm(db_path)


def run_install_setup() -> dict:
    """Create dbbackup/, restore from zip if needed, otherwise init a fresh SQLite DB."""
    ensure_dbbackup_dir()

    import database

    if not uses_sqlite():
        database.init_db()
        return {"action": "external_db", "restored": False}

    db_path = config.DATABASE_PATH
    zip_path = find_restore_zip()
    explicit_restore = zip_path and os.path.basename(zip_path) == RESTORE_ZIP_NAME

    if zip_path and explicit_restore:
        restore_from_zip(zip_path, db_path, overwrite=True)
        database.init_db()
        return {"action": "restored", "restored": True, "from": zip_path}

    if zip_path and not os.path.exists(db_path):
        restore_from_zip(zip_path, db_path)
        database.init_db()
        return {"action": "restored", "restored": True, "from": zip_path}

    seed_path = bundled_seed_db_path()
    if not os.path.exists(db_path) and os.path.isfile(seed_path):
        shutil.copy2(seed_path, db_path)
        database.init_db()
        return {"action": "seeded", "restored": False, "from": seed_path}

    database.init_db()
    if zip_path and os.path.exists(db_path):
        return {
            "action": "initialized",
            "restored": False,
            "note": "Existing database kept. Put restore.zip in dbbackup/ and rerun install.bat to overwrite.",
        }
    return {"action": "initialized", "restored": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite database backup and install setup")
    parser.add_argument("--install", action="store_true", help="Initialize or restore the database")
    parser.add_argument("--backup", action="store_true", help="Write a backup zip into dbbackup/")
    args = parser.parse_args()

    if args.install:
        result = run_install_setup()
        print(f"Database setup: {result['action']}")
        if result.get("from"):
            print(f"Restored from: {result['from']}")
        if result.get("note"):
            print(result["note"])
        return

    if args.backup:
        if not uses_sqlite():
            raise SystemExit("Backup is only available when using SQLite.")
        path = save_backup_to_folder()
        print(f"Backup saved to {path}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
