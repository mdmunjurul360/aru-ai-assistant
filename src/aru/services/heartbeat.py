"""Periodic system heartbeat service for ARU AI V4."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
from typing import Any, Awaitable, Callable
from pydantic import BaseModel, Field

from aru.core.logging import StructuredLogger
from aru.services.scheduler import SchedulerService

HeartbeatCallback = Callable[["HeartbeatEvent"], Awaitable[None]]


class HeartbeatEvent(BaseModel):
    """Payload emitted during a periodic heartbeat pulse."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pulse_count: int
    uptime_seconds: float
    status: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)


class HeartbeatService:
    """
    Emits regular heartbeat pulses to verify system liveness, compute uptime,
    and trigger registered diagnostic listeners.
    """

    def __init__(
        self,
        scheduler: SchedulerService | None = None,
        interval_seconds: float = 60.0,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._interval = interval_seconds
        self._logger = logger or StructuredLogger("aru.services.heartbeat")
        self._start_time = time.monotonic()
        self._pulse_count = 0
        self._last_event: HeartbeatEvent | None = None
        self._callbacks: list[HeartbeatCallback] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def pulse_count(self) -> int:
        return self._pulse_count

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def last_event(self) -> HeartbeatEvent | None:
        return self._last_event

    def register_callback(self, callback: HeartbeatCallback) -> None:
        """Register an async callback to be invoked on every heartbeat pulse."""
        self._callbacks.append(callback)

    async def emit_pulse(self, metadata: dict[str, Any] | None = None) -> HeartbeatEvent:
        """Execute a single heartbeat pulse and notify registered listeners."""
        self._pulse_count += 1
        event = HeartbeatEvent(
            pulse_count=self._pulse_count,
            uptime_seconds=round(self.uptime_seconds, 2),
            status="ok",
            metadata=metadata or {},
        )
        self._last_event = event

        self._logger.debug(
            "Heartbeat pulse #%d emitted (uptime=%.1fs)",
            event.pulse_count,
            event.uptime_seconds,
        )

        for cb in self._callbacks:
            try:
                await cb(event)
            except Exception as exc:
                self._logger.warning("Error in heartbeat callback: %s", exc)

        return event

    def start_scheduled(self) -> None:
        """Schedule periodic heartbeat pulses using the injected SchedulerService."""
        if not self._scheduler:
            raise RuntimeError("Cannot start_scheduled without an injected SchedulerService")

        self._scheduler.add_interval_job(
            self.emit_pulse,
            seconds=self._interval,
            job_id="heartbeat_service_job",
            name="Periodic System Heartbeat",
        )
        self._running = True
        self._logger.info("HeartbeatService registered with scheduler (every %.1fs)", self._interval)

    async def start(self) -> None:
        """Start standalone asynchronous background loop if scheduler is not used."""
        if self._running:
            return
        self._running = True

        async def _loop() -> None:
            while self._running:
                try:
                    await self.emit_pulse()
                except Exception as exc:
                    self._logger.error("Heartbeat loop error: %s", exc)
                await asyncio.sleep(self._interval)

        self._task = asyncio.create_task(_loop())
        self._logger.info("HeartbeatService started standalone loop (every %.1fs)", self._interval)

    async def stop(self) -> None:
        """Stop heartbeat execution."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._scheduler:
            self._scheduler.remove_job("heartbeat_service_job")
        self._logger.info("HeartbeatService stopped.")
