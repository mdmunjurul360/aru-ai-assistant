"""Recurring task and notification reminder service for ARU AI V4."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from pydantic import BaseModel, Field

from aru.core.logging import StructuredLogger
from aru.database.repositories.task_repo import TaskRepository
from aru.services.scheduler import SchedulerService

NotificationCallback = Callable[[str, int | None], Awaitable[None]]


class Reminder(BaseModel):
    """Data transfer object describing an active or pending reminder."""

    id: str
    title: str
    chat_id: int | None = None
    due_time: datetime | None = None
    is_recurring: bool = False
    cron_expr: str | None = None
    interval_seconds: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReminderService:
    """
    Manages one-off and recurring alerts, due task scans, and delivery dispatch.
    """

    def __init__(
        self,
        scheduler: SchedulerService,
        task_repo: TaskRepository | None = None,
        notifier: NotificationCallback | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._tasks = task_repo
        self._notifier = notifier
        self._logger = logger or StructuredLogger("aru.services.reminder")
        self._reminders: dict[str, Reminder] = {}

    def set_notifier(self, notifier: NotificationCallback) -> None:
        """Inject or update the message notification delivery callback."""
        self._notifier = notifier

    async def _notify(self, message: str, chat_id: int | None = None) -> None:
        """Internal delivery dispatcher."""
        self._logger.info("Delivering reminder to chat_id=%s: '%s'", chat_id, message)
        if self._notifier:
            try:
                await self._notifier(message, chat_id)
            except Exception as exc:
                self._logger.error("Failed delivering reminder: %s", exc)
        else:
            self._logger.warning("No notification handler configured for reminder: %s", message)

    async def add_one_off_reminder(
        self,
        reminder_id: str,
        title: str,
        run_date: datetime,
        chat_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Reminder:
        """Schedule a single-fire reminder at a future timestamp."""
        reminder = Reminder(
            id=reminder_id,
            title=title,
            chat_id=chat_id,
            due_time=run_date,
            is_recurring=False,
            metadata=metadata or {},
        )

        async def _run() -> None:
            await self._notify(f"⏰ **Reminder:** {title}", chat_id)
            self._reminders.pop(reminder_id, None)

        self._scheduler.add_date_job(
            _run,
            run_date=run_date,
            job_id=f"reminder_{reminder_id}",
            name=f"Reminder: {title}",
        )
        self._reminders[reminder_id] = reminder
        return reminder

    async def add_recurring_reminder(
        self,
        reminder_id: str,
        title: str,
        interval_seconds: float | None = None,
        cron_expr: str | None = None,
        chat_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Reminder:
        """Schedule a recurring interval or cron reminder."""
        reminder = Reminder(
            id=reminder_id,
            title=title,
            chat_id=chat_id,
            is_recurring=True,
            cron_expr=cron_expr,
            interval_seconds=interval_seconds,
            metadata=metadata or {},
        )

        async def _run() -> None:
            await self._notify(f"🔁 **Recurring Reminder:** {title}", chat_id)

        job_id = f"reminder_{reminder_id}"
        if cron_expr:
            self._scheduler.add_cron_job(
                _run,
                cron_expr=cron_expr,
                job_id=job_id,
                name=f"Recurring Reminder: {title}",
            )
        elif interval_seconds:
            self._scheduler.add_interval_job(
                _run,
                seconds=interval_seconds,
                job_id=job_id,
                name=f"Recurring Reminder: {title}",
            )
        else:
            raise ValueError("Either interval_seconds or cron_expr must be specified")

        self._reminders[reminder_id] = reminder
        return reminder

    def cancel_reminder(self, reminder_id: str) -> bool:
        """Cancel and unschedule a reminder."""
        job_id = f"reminder_{reminder_id}"
        removed = self._scheduler.remove_job(job_id)
        self._reminders.pop(reminder_id, None)
        return removed

    def list_reminders(self) -> list[Reminder]:
        """List active scheduled reminders."""
        return list(self._reminders.values())

    async def check_due_tasks(self) -> int:
        """
        Scan TaskRepository for pending tasks whose due_date has arrived
        and deliver alerts.
        """
        if not self._tasks:
            return 0

        pending_tasks = await self._tasks.list_tasks(status="pending", limit=100)
        now_str = datetime.now(timezone.utc).isoformat()
        notified = 0

        for task in pending_tasks:
            due_date = task.get("due_date")
            if due_date and str(due_date) <= now_str:
                msg = f"📋 **Task Overdue / Due Now:** #{task['id']} — {task['title']}"
                await self._notify(msg)
                notified += 1

        return notified

    def schedule_due_task_scanner(self, interval_minutes: float = 10.0) -> None:
        """Schedule periodic scanning of pending database tasks."""
        self._scheduler.add_interval_job(
            self.check_due_tasks,
            minutes=interval_minutes,
            job_id="due_tasks_scanner_job",
            name="Pending Due Task Scanner",
        )
        self._logger.info("Due tasks scanner scheduled (every %.1f minutes)", interval_minutes)
