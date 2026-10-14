"""Unit tests for CleanupService in ARU AI V4."""

from __future__ import annotations

import os
import time
from pathlib import Path
import pytest

from aru.core.config.models import AppSettings, SystemSettings
from aru.services.cleanup import CleanupService
from aru.services.scheduler import SchedulerService


@pytest.fixture
def cleanup_env(tmp_path: Path) -> tuple[AppSettings, Path, Path]:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    sys_settings = SystemSettings.create_default(tmp_path)
    settings = AppSettings(system=sys_settings)
    return settings, logs_dir, temp_dir


@pytest.mark.asyncio
async def test_cleanup_logs_retention(cleanup_env: tuple[AppSettings, Path, Path]):
    settings, logs_dir, _ = cleanup_env
    service = CleanupService(settings=settings)

    # 1. Active log file (must NEVER be deleted)
    active_log = Path(settings.system.log_file)
    active_log.write_text("active logging data")

    # 2. Fresh rotated log file (age: 2 days, should NOT be deleted with retention=7)
    fresh_log = logs_dir / "aru_v4.log.2026-10-12"
    fresh_log.write_text("recent rotated data")
    fresh_mtime = time.time() - (2 * 86400)
    os.utime(fresh_log, (fresh_mtime, fresh_mtime))

    # 3. Old rotated log file (age: 15 days, SHOULD be deleted with retention=7)
    old_log = logs_dir / "aru_v4.log.2026-09-20"
    old_log.write_text("ancient rotated data")
    old_mtime = time.time() - (15 * 86400)
    os.utime(old_log, (old_mtime, old_mtime))

    # 4. Non-log file (should be ignored)
    txt_file = logs_dir / "readme.txt"
    txt_file.write_text("info")
    os.utime(txt_file, (old_mtime, old_mtime))

    report = await service.clean_logs(retention_days=7)

    assert report.status == "success"
    assert report.files_deleted == 1
    assert not old_log.exists()
    assert fresh_log.exists()
    assert active_log.exists()
    assert txt_file.exists()


@pytest.mark.asyncio
async def test_cleanup_temp_directory(cleanup_env: tuple[AppSettings, Path, Path]):
    settings, _, temp_dir = cleanup_env
    service = CleanupService(settings=settings)

    stale_file = temp_dir / "scratch.tmp"
    stale_file.write_text("temp data")
    old_mtime = time.time() - (48 * 3600)  # 48 hours old
    os.utime(stale_file, (old_mtime, old_mtime))

    fresh_file = temp_dir / "fresh.tmp"
    fresh_file.write_text("new temp data")

    report = await service.clean_temp_directory(temp_dir=temp_dir, max_age_hours=24.0)

    assert report.files_deleted == 1
    assert not stale_file.exists()
    assert fresh_file.exists()


@pytest.mark.asyncio
async def test_cleanup_scheduling(cleanup_env: tuple[AppSettings, Path, Path]):
    settings, _, _ = cleanup_env
    scheduler = SchedulerService()
    scheduler.start()

    service = CleanupService(settings=settings, scheduler=scheduler)
    service.schedule_nightly_cleanup(cron_expr="0 4 * * *", retention_days=14)

    assert any(j.id == "nightly_cleanup_job" for j in scheduler.list_jobs())
    scheduler.shutdown(wait=False)
