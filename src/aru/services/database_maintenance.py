"""Database maintenance service for ARU AI V4 (WAL checkpoint, VACUUM, cleanup)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field

from aru.core.logging import StructuredLogger
from aru.database.connection import DatabaseManager
from aru.services.scheduler import SchedulerService


class DatabaseMaintenanceReport(BaseModel):
    """Execution statistics and results from a database maintenance pass."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    wal_checkpoint: dict[str, Any] = Field(default_factory=dict)
    vacuum_success: bool = False
    expired_cooldowns_purged: int = 0
    duration_ms: float = 0.0
    status: str = "success"
    error: str | None = None


class DatabaseMaintenanceService:
    """
    Executes database maintenance routines:
    1. SQLite WAL checkpointing (PRAGMA wal_checkpoint(TRUNCATE))
    2. Database vacuuming (VACUUM)
    3. Pruning of expired anti-spam cooldowns and transient data
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        scheduler: SchedulerService | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._scheduler = scheduler
        self._logger = logger or StructuredLogger("aru.services.db_maintenance")

    async def wal_checkpoint(self, mode: str = "TRUNCATE") -> dict[str, Any]:
        """
        Force SQLite WAL checkpoint to flush pending write-ahead log pages
        into the main database file.
        """
        async with self._db_manager.get_connection() as conn:
            cursor = await conn.execute(f"PRAGMA wal_checkpoint({mode});")
            row = await cursor.fetchone()
            if row:
                busy = int(row[0])
                log_pages = int(row[1])
                checkpointed_pages = int(row[2])
            else:
                busy, log_pages, checkpointed_pages = 0, 0, 0

            self._logger.debug(
                "WAL checkpoint (%s) complete: busy=%d, log=%d, checkpointed=%d",
                mode,
                busy,
                log_pages,
                checkpointed_pages,
            )
            return {
                "mode": mode,
                "busy": busy,
                "log_pages": log_pages,
                "checkpointed_pages": checkpointed_pages,
            }

    async def vacuum(self) -> bool:
        """
        Execute VACUUM to reclaim free pages and defragment the SQLite database.
        Note: VACUUM is executed outside multi-statement transactions.
        """
        async with self._db_manager.get_connection() as conn:
            await conn.execute("VACUUM;")
            self._logger.debug("Database VACUUM completed successfully.")
            return True

    async def purge_expired_cooldowns(self) -> int:
        """Purge expired anti-spam cooldown entries."""
        now_str = datetime.now(timezone.utc).isoformat()
        async with self._db_manager.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM anti_spam_cooldowns WHERE cooldown_until < ?;",
                (now_str,),
            )
            purged = cursor.rowcount
            if purged > 0:
                self._logger.info("Purged %d expired anti-spam cooldowns.", purged)
            return purged

    async def run_full_maintenance(self) -> DatabaseMaintenanceReport:
        """
        Run complete maintenance pass: WAL checkpoint, VACUUM, and expired data purge.
        """
        start = time.perf_counter()
        self._logger.info("Starting scheduled database maintenance run...")
        report = DatabaseMaintenanceReport()

        try:
            # 1. Purge expired transient cooldowns
            report.expired_cooldowns_purged = await self.purge_expired_cooldowns()

            # 2. Checkpoint WAL
            report.wal_checkpoint = await self.wal_checkpoint("TRUNCATE")

            # 3. Compact database
            report.vacuum_success = await self.vacuum()

            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._logger.info(
                "Database maintenance finished successfully in %.2fms (purged=%d, checkpointed=%d)",
                report.duration_ms,
                report.expired_cooldowns_purged,
                report.wal_checkpoint.get("checkpointed_pages", 0),
            )
            return report

        except Exception as exc:
            report.status = "error"
            report.error = str(exc)
            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._logger.error("Database maintenance failed after %.2fms: %s", report.duration_ms, exc, exc_info=True)
            return report

    def schedule_maintenance(self, cron_expr: str = "0 3 * * *") -> None:
        """
        Schedule regular maintenance with the scheduler (default: daily at 03:00 AM).
        """
        if not self._scheduler:
            raise RuntimeError("SchedulerService is required to schedule maintenance.")

        self._scheduler.add_cron_job(
            self.run_full_maintenance,
            cron_expr=cron_expr,
            job_id="db_maintenance_job",
            name="Nightly Database Maintenance",
        )
        self._logger.info("Database maintenance scheduled with cron: '%s'", cron_expr)
