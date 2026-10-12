"""Centralized SQLite database connection management with WAL mode and busy timeout."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from modules.config import DATABASE_DIR, DATABASE_PATH

logger = logging.getLogger("aru.db")


def apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Apply performant and concurrency-safe pragmas to an active SQLite connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def get_db_connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """
    Provide a transactional SQLite connection with WAL mode and busy timeout.
    
    Commits on clean exit, rolls back on exception, and ensures connection closure.
    """
    path = str(db_path or DATABASE_PATH)
    target_dir = Path(path).parent
    target_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        apply_connection_pragmas(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_db_ready(db_path: str | Path | None = None) -> str:
    """Verify that SQLite can be opened in WAL mode and return effective journal mode."""
    with get_db_connection(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    logger.debug("Database ready (path=%s, journal_mode=%s)", db_path or DATABASE_PATH, mode)
    return str(mode).upper()
