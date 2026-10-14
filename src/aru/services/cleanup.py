"""Nightly filesystem and log retention cleanup service for ARU AI V4."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from aru.core.config.models import AppSettings
from aru.core.logging import StructuredLogger
from aru.services.scheduler import SchedulerService


class CleanupReport(BaseModel):
    """Telemetry report produced by a cleanup execution run."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    files_deleted: int = 0
    bytes_reclaimed: int = 0
    deleted_paths: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    status: str = "success"
    error: str | None = None


class CleanupService:
    """
    Manages filesystem hygiene, including:
    - Log retention pruning (deleting rotated log files older than N days)
    - Temporary and cache file cleanup
    - Nightly automated maintenance scheduling
    """

    def __init__(
        self,
        settings: AppSettings,
        scheduler: SchedulerService | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._settings = settings
        self._scheduler = scheduler
        self._logger = logger or StructuredLogger("aru.services.cleanup")

    async def clean_logs(
        self,
        retention_days: int = 7,
        dry_run: bool = False,
    ) -> CleanupReport:
        """
        Prune rotated/archived log files in logs_dir older than retention_days.
        Never deletes the active log file.
        """
        start = time.perf_counter()
        report = CleanupReport()
        logs_dir = Path(self._settings.system.logs_dir)
        active_log = Path(self._settings.system.log_file).resolve()

        if not logs_dir.exists():
            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return report

        now = time.time()
        max_age_seconds = retention_days * 86400

        try:
            for item in logs_dir.iterdir():
                if not item.is_file():
                    continue

                # Never delete active log file
                if item.resolve() == active_log:
                    continue

                # Target log files (*.log.*, *.log)
                if not (item.name.endswith(".log") or ".log." in item.name):
                    continue

                try:
                    stat = item.stat()
                    age_seconds = now - stat.st_mtime
                    if age_seconds > max_age_seconds:
                        size = stat.st_size
                        if not dry_run:
                            item.unlink(missing_ok=True)
                            self._logger.info("Deleted stale log file: %s (%d bytes)", item.name, size)
                        report.files_deleted += 1
                        report.bytes_reclaimed += size
                        report.deleted_paths.append(str(item))
                except Exception as file_err:
                    self._logger.warning("Error inspecting/deleting file %s: %s", item, file_err)

            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return report

        except Exception as exc:
            report.status = "error"
            report.error = str(exc)
            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._logger.error("Error during log cleanup: %s", exc, exc_info=True)
            return report

    async def clean_temp_directory(
        self,
        temp_dir: Path | str,
        max_age_hours: float = 24.0,
        dry_run: bool = False,
    ) -> CleanupReport:
        """Prune temporary/transient files older than max_age_hours."""
        start = time.perf_counter()
        report = CleanupReport()
        target = Path(temp_dir)

        if not target.exists():
            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return report

        now = time.time()
        max_age_seconds = max_age_hours * 3600

        try:
            for item in target.glob("**/*"):
                if not item.is_file():
                    continue
                try:
                    stat = item.stat()
                    if (now - stat.st_mtime) > max_age_seconds:
                        size = stat.st_size
                        if not dry_run:
                            item.unlink(missing_ok=True)
                        report.files_deleted += 1
                        report.bytes_reclaimed += size
                        report.deleted_paths.append(str(item))
                except Exception as file_err:
                    self._logger.warning("Error deleting temp file %s: %s", item, file_err)

            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return report
        except Exception as exc:
            report.status = "error"
            report.error = str(exc)
            report.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return report

    async def run_nightly_cleanup(self, retention_days: int = 7) -> CleanupReport:
        """Run standard nightly cleanup cycle."""
        self._logger.info("Executing nightly cleanup routine (retention=%d days)...", retention_days)
        return await self.clean_logs(retention_days=retention_days)

    def schedule_nightly_cleanup(self, cron_expr: str = "0 4 * * *", retention_days: int = 7) -> None:
        """Schedule nightly cleanup job (default: 04:00 AM daily)."""
        if not self._scheduler:
            raise RuntimeError("SchedulerService is required to schedule nightly cleanup.")

        async def _job() -> None:
            await self.run_nightly_cleanup(retention_days=retention_days)

        self._scheduler.add_cron_job(
            _job,
            cron_expr=cron_expr,
            job_id="nightly_cleanup_job",
            name="Nightly Filesystem Cleanup",
        )
        self._logger.info("Nightly cleanup scheduled with cron: '%s'", cron_expr)
