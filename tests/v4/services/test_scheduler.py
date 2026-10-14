"""Unit tests for SchedulerService in ARU AI V4."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from aru.services.scheduler import SchedulerService


@pytest.mark.asyncio
async def test_scheduler_lifecycle():
    scheduler = SchedulerService()
    assert not scheduler.is_running

    scheduler.start()
    assert scheduler.is_running

    scheduler.shutdown(wait=False)
    assert not scheduler.is_running


@pytest.mark.asyncio
async def test_scheduler_job_management():
    scheduler = SchedulerService()
    scheduler.start()

    run_count = 0

    async def sample_job():
        nonlocal run_count
        run_count += 1

    # Add interval job
    job = scheduler.add_interval_job(
        sample_job,
        seconds=0.2,
        job_id="test_interval_job",
        name="Sample Interval Job",
    )
    assert job.id == "test_interval_job"

    # List jobs
    jobs = scheduler.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "test_interval_job"
    assert jobs[0].name == "Sample Interval Job"

    # Let interval job trigger
    await asyncio.sleep(0.5)
    assert run_count >= 1

    # Remove job
    removed = scheduler.remove_job("test_interval_job")
    assert removed is True
    assert len(scheduler.list_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_scheduler_date_and_cron_jobs():
    scheduler = SchedulerService()
    scheduler.start()

    async def noop():
        pass

    run_time = datetime.now() + timedelta(hours=1)
    date_job = scheduler.add_date_job(noop, run_date=run_time, job_id="date_job")
    assert date_job.id == "date_job"

    cron_job = scheduler.add_cron_job(noop, cron_expr="0 3 * * *", job_id="cron_job")
    assert cron_job.id == "cron_job"

    assert len(scheduler.list_jobs()) == 2
    scheduler.shutdown(wait=False)
