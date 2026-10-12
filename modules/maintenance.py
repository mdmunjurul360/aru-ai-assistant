"""Database maintenance jobs: log cleanup, cooldown pruning, WAL checkpoint, VACUUM, ANALYZE."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from modules.config import (
    COOLDOWN_RETENTION_HOURS,
    DATABASE_PATH,
    LOG_RETENTION_DAYS,
)
from modules.db import get_db_connection

logger = logging.getLogger("aru.maintenance")


class DatabaseMaintenance:
    """Automated and on-demand maintenance routines for SQLite database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or DATABASE_PATH)

    def cleanup_activity_logs(self, days: int = LOG_RETENTION_DAYS) -> int:
        """Delete activity log rows older than given days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute(
                    "DELETE FROM activity_logs WHERE created_at < ?",
                    (cutoff,),
                )
                deleted = cur.rowcount
            logger.info("Maintenance: pruned %d activity log rows older than %d days", deleted, days)
            return deleted
        except sqlite3.OperationalError as exc:
            logger.warning("Cleanup activity logs skipped: %s", exc)
            return 0

    def cleanup_expired_cooldowns(self, hours: int = COOLDOWN_RETENTION_HOURS) -> int:
        """Delete user cooldowns older than given hours."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute(
                    "DELETE FROM user_cooldowns WHERE updated_at < ?",
                    (cutoff,),
                )
                deleted = cur.rowcount
            logger.info("Maintenance: pruned %d expired cooldown records older than %d hours", deleted, hours)
            return deleted
        except sqlite3.OperationalError as exc:
            logger.warning("Cleanup cooldowns skipped: %s", exc)
            return 0

    def wal_checkpoint(self, mode: str = "TRUNCATE") -> str:
        """
        Execute WAL checkpoint (PASSIVE, FULL, RESTART, TRUNCATE).
        TRUNCATE flushes and truncates the WAL file to zero bytes.
        """
        valid_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
        mode = mode.upper() if mode.upper() in valid_modes else "TRUNCATE"
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            status = f"mode={mode}, busy={row[0]}, log={row[1]}, checkpointed={row[2]}"
        logger.info("Maintenance WAL checkpoint completed: %s", status)
        return status

    def vacuum_database(self) -> bool:
        """Rebuild the database file to reclaim unused space (requires autocommit connection)."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
            try:
                conn.execute("VACUUM")
            finally:
                conn.close()
            logger.info("Maintenance: VACUUM completed successfully")
            return True
        except Exception as exc:
            logger.exception("Maintenance: VACUUM failed: %s", exc)
            return False

    def analyze_database(self) -> bool:
        """Run ANALYZE and PRAGMA optimize to refresh query planner statistics."""
        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute("ANALYZE")
                conn.execute("PRAGMA optimize")
            logger.info("Maintenance: ANALYZE and PRAGMA optimize completed successfully")
            return True
        except Exception as exc:
            logger.exception("Maintenance: ANALYZE failed: %s", exc)
            return False

    def cleanup_expired_research_cache(self) -> int:
        """Delete expired research cache records."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute("DELETE FROM research_cache WHERE expires_at <= ?", (now,))
                deleted = cur.rowcount
            if deleted:
                logger.info("Maintenance: pruned %d expired research cache records", deleted)
            return deleted
        except sqlite3.OperationalError:
            return 0

    def run_full_maintenance(
        self,
        log_retention_days: int = LOG_RETENTION_DAYS,
        cooldown_retention_hours: int = COOLDOWN_RETENTION_HOURS,
    ) -> dict[str, Any]:
        """Execute full suite of database maintenance jobs and return summary report."""
        logger.info("Starting scheduled full database maintenance...")
        logs_pruned = self.cleanup_activity_logs(days=log_retention_days)
        cooldowns_pruned = self.cleanup_expired_cooldowns(hours=cooldown_retention_hours)
        cache_pruned = self.cleanup_expired_research_cache()
        checkpoint_status = self.wal_checkpoint()
        vacuum_ok = self.vacuum_database()
        analyze_ok = self.analyze_database()

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logs_pruned": logs_pruned,
            "cooldowns_pruned": cooldowns_pruned,
            "cache_pruned": cache_pruned,
            "wal_checkpoint": checkpoint_status,
            "vacuum": vacuum_ok,
            "analyze": analyze_ok,
        }
        logger.info("Full database maintenance finished: %s", summary)
        return summary
