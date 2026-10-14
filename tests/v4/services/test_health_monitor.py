"""Unit tests for HealthMonitorService in ARU AI V4."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from aru.brain.models import LLMResponse
from aru.brain.router import LLMRouter
from aru.core.config.models import AppSettings, SystemSettings
from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.services.health_monitor import HealthMonitorService
from aru.services.scheduler import SchedulerService


@pytest.fixture
async def test_env(tmp_path: Path) -> tuple[DatabaseManager, AppSettings]:
    db = DatabaseManager(tmp_path / "test_health.db")
    runner = MigrationRunner(db)
    await runner.run()

    sys_settings = SystemSettings.create_default(tmp_path)
    settings = AppSettings(system=sys_settings)
    yield db, settings
    await db.disconnect()


@pytest.mark.asyncio
async def test_health_monitor_checks(test_env: tuple[DatabaseManager, AppSettings]):
    db, settings = test_env

    # Mock provider and router
    mock_provider = MagicMock()
    mock_provider.name = "groq"
    mock_provider.is_available = True
    mock_provider.generate = AsyncMock(return_value=LLMResponse(content="pong", provider="groq", model="qwen"))

    router = LLMRouter(settings=settings)
    router.register_provider(mock_provider)

    monitor = HealthMonitorService(db_manager=db, settings=settings, router=router)

    # 1. DB check
    db_health = await monitor.check_database_health()
    assert db_health.status == "healthy"
    assert db_health.latency_ms is not None
    assert db_health.latency_ms >= 0.0

    # 2. Disk check
    disk_health = monitor.check_disk_space()
    assert disk_health.status in ("healthy", "degraded")
    assert disk_health.details["free_mb"] > 0

    # 3. API check
    api_health = await monitor.check_api_latency()
    assert api_health.status == "healthy"
    assert api_health.latency_ms is not None
    assert "groq" in api_health.details["provider_latencies"]

    # 4. Overall health report
    report = await monitor.get_health_status()
    assert report.status == "healthy"
    assert report.uptime_seconds >= 0.0
    assert monitor.last_report == report


@pytest.mark.asyncio
async def test_health_monitor_unhealthy_db(test_env: tuple[DatabaseManager, AppSettings]):
    db, settings = test_env
    await db.disconnect()  # Disconnect to simulate failure

    # Point to nonexistent or closed connection
    mock_broken_db = MagicMock()
    mock_broken_db.check_health = AsyncMock(side_effect=RuntimeError("Database unavailable"))

    monitor = HealthMonitorService(db_manager=mock_broken_db, settings=settings)
    report = await monitor.get_health_status()

    assert report.status == "unhealthy"
    assert report.database.status == "unhealthy"
    assert "Database unavailable" in str(report.database.error)


@pytest.mark.asyncio
async def test_health_monitor_schedule(test_env: tuple[DatabaseManager, AppSettings]):
    db, settings = test_env
    scheduler = SchedulerService()
    scheduler.start()

    monitor = HealthMonitorService(db_manager=db, settings=settings, scheduler=scheduler)
    monitor.schedule_health_checks(interval_minutes=10.0)

    jobs = scheduler.list_jobs()
    assert any(j.id == "health_monitor_job" for j in jobs)

    scheduler.shutdown(wait=False)
