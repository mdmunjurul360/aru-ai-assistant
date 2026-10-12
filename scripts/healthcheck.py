#!/usr/bin/env python3
"""Container healthcheck script for Aru AI OS."""

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "memory.db"


def check_health() -> int:
    # 1. Check database exists and is readable
    if not DB_PATH.exists():
        print("Healthcheck FAIL: memory.db does not exist")
        return 1

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
        cursor = conn.cursor()
        cursor.execute("PRAGMA schema_version;")
        cursor.execute("SELECT 1;")
        conn.close()
    except Exception as exc:
        print(f"Healthcheck FAIL: SQLite query error: {exc}")
        return 1

    print("Healthcheck PASS: Aru OS container healthy")
    return 0


if __name__ == "__main__":
    sys.exit(check_health())
