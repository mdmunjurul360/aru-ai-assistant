"""System health, database integrity, and API latency monitoring service for ARU AI V4."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from aru.brain.models import LLMMessage
from aru.brain.router import LLMRouter
from aru.core.config.models import AppSettings
from aru.core.logging import StructuredLogger
from aru.database.connection import DatabaseManager
from aru.services.scheduler import SchedulerService


class ComponentHealth(BaseModel):
    """Health evaluation status for an individual subsystem."""

    status: Literal["healthy", "degraded", "unhealthy"]
    details: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    error: str | None = None


class SystemHealthReport(BaseModel):
    """Aggregated health report across core subsystems."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    database: ComponentHealth
    disk: ComponentHealth
    api: ComponentHealth
    uptime_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthMonitorService:
    """
    Monitors database connectivity, disk storage thresholds, and LLM API response latency.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        settings: AppSettings,
        router: LLMRouter | None = None,
        scheduler: SchedulerService | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._settings = settings
        self._router = router
        self._scheduler = scheduler
        self._logger = logger or StructuredLogger("aru.services.health")
        self._start_time = time.monotonic()
        self._last_report: SystemHealthReport | None = None

    @property
    def last_report(self) -> SystemHealthReport | None:
        return self._last_report

    async def check_database_health(self) -> ComponentHealth:
        """Verify database responsiveness and WAL configuration."""
        start = time.perf_counter()
        try:
            db_info = await self._db_manager.check_health()
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            return ComponentHealth(
                status="healthy",
                details=db_info,
                latency_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            self._logger.error("Database health check failed: %s", exc)
            return ComponentHealth(
                status="unhealthy",
                latency_ms=elapsed_ms,
                error=str(exc),
            )

    def check_disk_space(self, min_free_mb: float = 100.0) -> ComponentHealth:
        """Check free disk storage on the application database filesystem."""
        try:
            target_path = Path(self._settings.system.database_dir)
            target_path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(target_path)

            free_mb = round(usage.free / (1024 * 1024), 2)
            total_mb = round(usage.total / (1024 * 1024), 2)
            used_pct = round((usage.used / usage.total) * 100, 1)

            status: Literal["healthy", "degraded", "unhealthy"] = (
                "healthy" if free_mb > min_free_mb else "degraded" if free_mb > (min_free_mb / 2) else "unhealthy"
            )

            return ComponentHealth(
                status=status,
                details={
                    "free_mb": free_mb,
                    "total_mb": total_mb,
                    "used_percent": used_pct,
                    "checked_path": str(target_path),
                },
            )
        except Exception as exc:
            self._logger.warning("Disk check error: %s", exc)
            return ComponentHealth(
                status="degraded",
                error=str(exc),
            )

    async def check_api_latency(self) -> ComponentHealth:
        """Measure API roundtrip latency for configured LLM providers."""
        if not self._router:
            return ComponentHealth(
                status="healthy",
                details={"message": "No LLM router configured"},
                latency_ms=0.0,
            )

        available_providers = self._router.get_available_providers()
        if not available_providers:
            return ComponentHealth(
                status="degraded",
                details={"available_providers": [], "message": "No active LLM providers configured"},
            )

        provider_latencies: dict[str, float | str] = {}
        healthy_count = 0
        overall_start = time.perf_counter()

        for name in available_providers:
            provider = self._router.get_provider(name)
            if not provider:
                continue

            p_start = time.perf_counter()
            try:
                # Perform lightweight ping or 1-token test prompt
                test_msg = [LLMMessage(role="user", content="ping")]
                await provider.generate(test_msg, max_tokens=1, timeout=5.0)
                lat = round((time.perf_counter() - p_start) * 1000, 2)
                provider_latencies[name] = lat
                healthy_count += 1
            except Exception as exc:
                provider_latencies[name] = f"error: {exc}"

        total_elapsed = round((time.perf_counter() - overall_start) * 1000, 2)
        overall_status: Literal["healthy", "degraded", "unhealthy"] = (
            "healthy" if healthy_count > 0 else "unhealthy"
        )

        return ComponentHealth(
            status=overall_status,
            latency_ms=total_elapsed,
            details={"provider_latencies": provider_latencies, "healthy_count": healthy_count},
        )

    async def get_health_status(self) -> SystemHealthReport:
        """Perform comprehensive health check across database, disk, and API services."""
        db_health = await self.check_database_health()
        disk_health = self.check_disk_space()
        api_health = await self.check_api_latency()

        # Derive system status
        statuses = [db_health.status, disk_health.status, api_health.status]
        if "unhealthy" in statuses:
            overall_status: Literal["healthy", "degraded", "unhealthy"] = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        report = SystemHealthReport(
            status=overall_status,
            database=db_health,
            disk=disk_health,
            api=api_health,
            uptime_seconds=round(time.monotonic() - self._start_time, 2),
            metadata={"environment": self._settings.system.environment},
        )
        self._last_report = report
        self._logger.debug("System health check completed: status=%s", overall_status)
        return report

    def schedule_health_checks(self, interval_minutes: float = 15.0) -> None:
        """Schedule periodic health monitoring via the scheduler."""
        if not self._scheduler:
            raise RuntimeError("SchedulerService is required to schedule health monitoring.")

        self._scheduler.add_interval_job(
            self.get_health_status,
            minutes=interval_minutes,
            job_id="health_monitor_job",
            name="Periodic System Health Check",
        )
        self._logger.info("Health monitoring scheduled (every %.1f minutes)", interval_minutes)
