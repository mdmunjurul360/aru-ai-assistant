"""SQLite-backed activity logging for Aru v2 modules."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from modules.config import DATABASE_DIR, DATABASE_PATH

logger = logging.getLogger("aru.activity")

MODULES = ("memory", "voice", "research", "tasks", "system")


@dataclass
class ActivityEntry:
    id: int
    module: str
    action: str
    detail: str
    level: str
    created_at: str


class ActivityLogger:
    """Persist and emit structured logs for v2 features."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT DEFAULT '',
                    level TEXT NOT NULL DEFAULT 'info',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_module ON activity_logs(module)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at)"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log(
        self,
        module: str,
        action: str,
        detail: str = "",
        *,
        level: str = "info",
    ) -> None:
        module = module if module in MODULES else "system"
        level = level.lower()
        detail = (detail or "")[:2000]

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO activity_logs (module, action, detail, level, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (module, action, detail, level, self._now()),
            )

        log_fn = {
            "debug": logger.debug,
            "warning": logger.warning,
            "error": logger.error,
        }.get(level, logger.info)
        log_fn("[%s] %s | %s", module, action, detail[:200] if detail else "—")

    def log_error(self, module: str, action: str, exc: Exception | str) -> None:
        detail = str(exc)
        self.log(module, action, detail, level="error")
        logger.exception("[%s] %s failed: %s", module, action, detail)

    def recent(self, *, module: str | None = None, limit: int = 20) -> list[ActivityEntry]:
        with self._conn() as conn:
            if module:
                rows = conn.execute(
                    """
                    SELECT * FROM activity_logs WHERE module = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (module, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            ActivityEntry(
                id=r["id"],
                module=r["module"],
                action=r["action"],
                detail=r["detail"] or "",
                level=r["level"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count(self, *, module: str | None = None) -> int:
        with self._conn() as conn:
            if module:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM activity_logs WHERE module = ?",
                    (module,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM activity_logs").fetchone()
        return int(row["c"]) if row else 0
