"""Asynchronous background scheduler service for ARU AI V4."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Coroutine
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, Field

from aru.core.logging import StructuredLogger


class ScheduledJobInfo(BaseModel):
    """Metadata describing a currently registered background job."""

    id: str
    name: str
    next_run_time: datetime | None = None
    trigger_type: str = "unknown"


class SchedulerService:
    """
    Robust wrapper around APScheduler AsyncIOScheduler providing lifecycle management,
    async job registration, and inspection.
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._scheduler = scheduler or AsyncIOScheduler()
        self._logger = logger or StructuredLogger("aru.services.scheduler")
        self._is_started = False

    @property
    def is_running(self) -> bool:
        """Return True if the scheduler is active and running."""
        return self._is_started and self._scheduler.running

    def start(self) -> None:
        """Start the async scheduler if not already running."""
        if not self._scheduler.running:
            self._logger.info("Starting background AsyncIOScheduler...")
            self._scheduler.start()
            self._is_started = True

    def shutdown(self, wait: bool = False) -> None:
        """Shutdown the scheduler and stop all scheduled tasks."""
        if self._scheduler.running:
            self._logger.info("Shutting down AsyncIOScheduler (wait=%s)...", wait)
            self._scheduler.shutdown(wait=wait)
            self._is_started = False

    def add_interval_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        seconds: float = 0,
        minutes: float = 0,
        hours: float = 0,
        job_id: str | None = None,
        name: str | None = None,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Job:
        """Schedule an asynchronous recurring interval job."""
        trigger = IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours)
        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or func.__name__,
            replace_existing=replace_existing,
            **kwargs,
        )
        self._logger.debug("Scheduled interval job id=%s name=%s", job.id, job.name)
        return job

    def add_cron_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        cron_expr: str | None = None,
        hour: int | str = "*",
        minute: int | str = "*",
        day_of_week: int | str = "*",
        job_id: str | None = None,
        name: str | None = None,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Job:
        """Schedule an asynchronous recurring cron job."""
        if cron_expr:
            trigger = CronTrigger.from_crontab(cron_expr)
        else:
            trigger = CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week)

        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or func.__name__,
            replace_existing=replace_existing,
            **kwargs,
        )
        self._logger.debug("Scheduled cron job id=%s name=%s", job.id, job.name)
        return job

    def add_date_job(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        run_date: datetime,
        job_id: str | None = None,
        name: str | None = None,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Job:
        """Schedule a one-off asynchronous job to run at a specific timestamp."""
        trigger = DateTrigger(run_date=run_date)
        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or func.__name__,
            replace_existing=replace_existing,
            **kwargs,
        )
        self._logger.debug("Scheduled date job id=%s name=%s for %s", job.id, job.name, run_date)
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by its identifier."""
        try:
            self._scheduler.remove_job(job_id)
            self._logger.debug("Removed scheduled job id=%s", job_id)
            return True
        except Exception as exc:
            self._logger.warning("Failed to remove job id=%s: %s", job_id, exc)
            return False

    def get_job(self, job_id: str) -> Job | None:
        """Retrieve a scheduled job by its identifier."""
        return self._scheduler.get_job(job_id)

    def list_jobs(self) -> list[ScheduledJobInfo]:
        """List all currently active scheduled jobs."""
        results: list[ScheduledJobInfo] = []
        for job in self._scheduler.get_jobs():
            results.append(
                ScheduledJobInfo(
                    id=str(job.id),
                    name=str(job.name),
                    next_run_time=job.next_run_time,
                    trigger_type=job.trigger.__class__.__name__,
                )
            )
        return results
