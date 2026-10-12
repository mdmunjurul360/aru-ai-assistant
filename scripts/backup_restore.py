#!/usr/bin/env python3
"""Zero-downtime automated backup and restore utility for Aru AI OS."""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sqlite3
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "memory.db"
BACKUPS_DIR = ROOT / "database" / "backups"


def perform_backup(target_dir: Path | None = None) -> Path:
    """Execute SQLite online backup with WAL checkpointing and tar.gz compression."""
    out_dir = target_dir or BACKUPS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_backup_db = out_dir / f"memory_snapshot_{timestamp}.db"
    final_archive = out_dir / f"aru_backup_{timestamp}.tar.gz"

    print(f"Starting online backup of {DB_PATH}...")
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    # 1. Connect and perform online WAL checkpoint and backup
    src_conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        dst_conn = sqlite3.connect(str(temp_backup_db))
        try:
            src_conn.backup(dst_conn, pages=100)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    # 2. Compress snapshot into tar.gz
    with tarfile.open(final_archive, "w:gz") as tar:
        tar.add(temp_backup_db, arcname="memory.db")
        # Add sessions if present
        sessions_dir = ROOT / "sessions"
        if sessions_dir.exists():
            tar.add(sessions_dir, arcname="sessions")

    # Clean temporary snapshot
    temp_backup_db.unlink(missing_ok=True)
    print(f"Backup created successfully: {final_archive} ({final_archive.stat().st_size} bytes)")
    return final_archive


def verify_and_restore(archive_path: Path, restore_dir: Path | None = None) -> bool:
    """Verify archive integrity and extract backup."""
    target_dir = restore_dir or (ROOT / "database" / "restored_test")
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"Verifying backup archive {archive_path}...")
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(target_dir)

    restored_db = target_dir / "memory.db"
    if not restored_db.exists():
        print("Restore verification failed: memory.db not found in archive")
        return False

    conn = sqlite3.connect(str(restored_db))
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        res = cursor.fetchone()
        if res and res[0] == "ok":
            print(f"Restore verification PASSED: SQLite integrity check OK at {restored_db}")
            return True
        else:
            print(f"Restore verification FAILED: {res}")
            return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Aru AI backup & restore utility")
    parser.add_argument("--backup", action="store_true", help="Create new backup")
    parser.add_argument("--restore", type=str, help="Path to archive to verify and restore")
    args = parser.parse_args()

    if args.restore:
        ok = verify_and_restore(Path(args.restore))
        return 0 if ok else 1

    # Default to backup
    perform_backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
