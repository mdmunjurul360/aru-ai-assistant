"""Unit tests for DatabaseMaintenanceService in ARU AI V4."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.services.database_maintenance import DatabaseMaintenanceService
from aru.services.scheduler import SchedulerService


@pytest.fixture
async def test_db(tmp_path: Path) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "test_maint.db")
    runner = MigrationRunner(db)
    await runner.run()
    yield db
    await db.disconnect()


@pytest.mark.asyncio
async def test_database_maintenance_wal_and_vacuum(test_db: DatabaseManager):
    service = DatabaseMaintenanceService(db_manager=test_db)

    # Test WAL checkpoint
    checkpoint = await service.wal_checkpoint(mode="TRUNCATE")
    assert checkpoint["mode"] == "TRUNCATE"
    assert "busy" in checkpoint
    assert "log_pages" in checkpoint
    assert "checkpointed_pages" in checkpoint

    # Test VACUUM
    vacuum_ok = await service.vacuum()
    assert vacuum_ok is True


@pytest.mark.asyncio
async def test_database_maintenance_purge_expired_cooldowns(test_db: DatabaseManager):
    repo = AntiSpamRepository(test_db)

    # 1. Past cooldown (expired)
    past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    await repo.set_cooldown(111, cooldown_until=past_time, reason="Old cooldown")

    # 2. Future cooldown (active)
    future_time = datetime.now(timezone.utc) + timedelta(minutes=10)
    await repo.set_cooldown(222, cooldown_until=future_time, reason="Active cooldown")

    service = DatabaseMaintenanceService(db_manager=test_db)
    purged = await service.purge_expired_cooldowns()

    assert purged == 1
    assert await repo.get_cooldown(111) is None
    assert await repo.get_cooldown(222) is not None


@pytest.mark.asyncio
async def test_database_maintenance_full_run(test_db: DatabaseManager):
    service = DatabaseMaintenanceService(db_manager=test_db)
    report = await service.run_full_maintenance()

    assert report.status == "success"
    assert report.vacuum_success is True
    assert report.duration_ms >= 0.0
    assert "checkpointed_pages" in report.wal_checkpoint


@pytest.mark.asyncio
async def test_database_maintenance_schedule(test_db: DatabaseManager):
    scheduler = SchedulerService()
    scheduler.start()

    service = DatabaseMaintenanceService(db_manager=test_db, scheduler=scheduler)
    service.schedule_maintenance(cron_expr="0 3 * * *")

    jobs = scheduler.list_jobs()
    assert any(j.id == "db_maintenance_job" for j in jobs)

    scheduler.shutdown(wait=False)
