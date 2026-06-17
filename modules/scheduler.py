"""APScheduler jobs: morning reports, night summaries, reminders."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from modules.config import (
    MORNING_REPORT_HOUR,
    MORNING_REPORT_MINUTE,
    NIGHT_SUMMARY_HOUR,
    NIGHT_SUMMARY_MINUTE,
    SCHEDULER_TIMEZONE,
)

if TYPE_CHECKING:
    from modules.tasks import TaskManager
    from modules.memory import MemoryStore

logger = logging.getLogger("aru.scheduler")

SendMessageFn = Callable[[str], Awaitable[None]]


class AruScheduler:
    """Scheduled notifications to Boss via Telegram."""

    def __init__(
        self,
        send_to_boss: SendMessageFn,
        task_manager: "TaskManager",
        memory_store: "MemoryStore",
    ) -> None:
        self._send = send_to_boss
        self._tasks = task_manager
        self._memory = memory_store
        self._scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)

    def start(self) -> None:
        self._scheduler.add_job(
            self._morning_report,
            CronTrigger(
                hour=MORNING_REPORT_HOUR,
                minute=MORNING_REPORT_MINUTE,
                timezone=SCHEDULER_TIMEZONE,
            ),
            id="morning_report",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._night_summary,
            CronTrigger(
                hour=NIGHT_SUMMARY_HOUR,
                minute=NIGHT_SUMMARY_MINUTE,
                timezone=SCHEDULER_TIMEZONE,
            ),
            id="night_summary",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started (tz=%s, morning=%02d:%02d, night=%02d:%02d)",
            SCHEDULER_TIMEZONE,
            MORNING_REPORT_HOUR,
            MORNING_REPORT_MINUTE,
            NIGHT_SUMMARY_HOUR,
            NIGHT_SUMMARY_MINUTE,
        )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def _morning_report(self) -> None:
        try:
            pending = self._tasks.list_tasks()
            count = len(pending)
            preview = self._tasks.format_list(pending[:5]) if pending else "কোনো pending টাস্ক নেই।"
            goals = self._memory.list_all(category="goal", limit=3)
            goal_lines = "\n".join(f"• {g.title}" for g in goals) if goals else "—"

            msg = (
                "🌅 **সকালের রিপোর্ট — Aru**\n\n"
                f"📅 {datetime.now().strftime('%A, %d %B %Y')}\n\n"
                f"📋 Pending টাস্ক: **{count}**\n{preview}\n\n"
                f"🎯 সক্রিয় লক্ষ্য:\n{goal_lines}\n\n"
                "ভালো দিন কাটুক, বস! 💪"
            )
            await self._send(msg)
            logger.info("Morning report sent")
        except Exception as exc:
            logger.exception("Morning report failed: %s", exc)

    async def _night_summary(self) -> None:
        try:
            all_tasks = self._tasks.list_tasks(include_done=True)
            done_today = [
                t for t in all_tasks
                if t.status == "done" and t.completed_at
                and t.completed_at[:10] == datetime.utcnow().strftime("%Y-%m-%d")
            ]
            pending = self._tasks.pending_count()
            done_lines = "\n".join(f"✅ {t.title}" for t in done_today) if done_today else "আজ কিছু mark done হয়নি।"

            msg = (
                "🌙 **রাতের সারাংশ — Aru**\n\n"
                f"আজ সম্পন্ন: **{len(done_today)}**\n{done_lines}\n\n"
                f"আগামীকালের জন্য pending: **{pending}**\n\n"
                "বিশ্রাম নিন, বস। আগামীকাল আবার শুরু করব। 🌟"
            )
            await self._send(msg)
            logger.info("Night summary sent")
        except Exception as exc:
            logger.exception("Night summary failed: %s", exc)

    def schedule_reminder(
        self,
        reminder_id: str,
        run_at: datetime,
        message: str,
    ) -> bool:
        """Schedule a one-shot reminder."""
        try:
            self._scheduler.add_job(
                self._send_reminder,
                DateTrigger(run_date=run_at, timezone=SCHEDULER_TIMEZONE),
                args=[message],
                id=reminder_id,
                replace_existing=True,
            )
            logger.info("Reminder scheduled: %s at %s", reminder_id, run_at)
            return True
        except Exception as exc:
            logger.exception("Failed to schedule reminder: %s", exc)
            return False

    async def _send_reminder(self, message: str) -> None:
        try:
            await self._send(f"⏰ **রিমাইন্ডার**\n\n{message}")
            logger.info("Reminder sent")
        except Exception as exc:
            logger.exception("Reminder send failed: %s", exc)

    def parse_reminder_command(self, text: str) -> tuple[datetime, str] | None:
        """
        /remind 2026-06-03 14:30 Meeting with team
        Returns (run_at, message) or None.
        """
        stripped = text.strip()
        if not stripped.lower().startswith("/remind"):
            return None
        parts = stripped.split(maxsplit=3)
        if len(parts) < 4:
            return None
        try:
            date_part, time_part = parts[1], parts[2]
            run_at = datetime.strptime(
                f"{date_part} {time_part}",
                "%Y-%m-%d %H:%M",
            )
            message = parts[3]
            return run_at, message
        except ValueError:
            return None
