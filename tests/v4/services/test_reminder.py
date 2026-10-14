"""Unit tests for ReminderService in ARU AI V4."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.database.repositories.task_repo import TaskRepository
from aru.services.reminder import ReminderService
from aru.services.scheduler import SchedulerService


@pytest.fixture
async def task_repo(tmp_path: Path) -> TaskRepository:
    db = DatabaseManager(tmp_path / "test_reminders.db")
    runner = MigrationRunner(db)
    await runner.run()
    repo = TaskRepository(db)
    yield repo
    await db.disconnect()


@pytest.mark.asyncio
async def test_reminder_one_off():
    scheduler = SchedulerService()
    scheduler.start()

    notified: list[str] = []

    async def notification_handler(msg: str, chat_id: int | None):
        notified.append(msg)

    service = ReminderService(scheduler=scheduler, notifier=notification_handler)

    # Schedule reminder to trigger almost immediately (0.1s in future)
    run_date = datetime.now() + timedelta(milliseconds=150)
    reminder = await service.add_one_off_reminder(
        reminder_id="rem_1",
        title="Check oven",
        run_date=run_date,
        chat_id=123,
    )

    assert reminder.id == "rem_1"
    assert reminder.title == "Check oven"
    assert len(service.list_reminders()) == 1

    await asyncio.sleep(0.3)
    assert any("Check oven" in m for m in notified)
    # Automatically cleaned up from active reminders after firing
    assert len(service.list_reminders()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminder_recurring_and_cancel():
    scheduler = SchedulerService()
    scheduler.start()

    service = ReminderService(scheduler=scheduler)

    reminder = await service.add_recurring_reminder(
        reminder_id="standup",
        title="Daily Standup",
        cron_expr="0 10 * * *",
    )
    assert reminder.is_recurring is True
    assert len(service.list_reminders()) == 1

    cancelled = service.cancel_reminder("standup")
    assert cancelled is True
    assert len(service.list_reminders()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminder_check_due_tasks(task_repo: TaskRepository):
    scheduler = SchedulerService()
    scheduler.start()

    delivered: list[str] = []

    async def notification_handler(msg: str, chat_id: int | None):
        delivered.append(msg)

    service = ReminderService(scheduler=scheduler, task_repo=task_repo, notifier=notification_handler)

    # 1. Past task (due now)
    past_due = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    await task_repo.create(title="Submit invoice", due_date=past_due)

    # 2. Future task (not due yet)
    future_due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    await task_repo.create(title="Doctor appointment", due_date=future_due)

    # 3. Task without due date
    await task_repo.create(title="Read book", due_date=None)

    notified_count = await service.check_due_tasks()
    assert notified_count == 1
    assert any("Submit invoice" in d for d in delivered)
    assert not any("Doctor appointment" in d for d in delivered)

    service.schedule_due_task_scanner(interval_minutes=5.0)
    assert any(j.id == "due_tasks_scanner_job" for j in scheduler.list_jobs())

    scheduler.shutdown(wait=False)
