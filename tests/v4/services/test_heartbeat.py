"""Unit tests for HeartbeatService in ARU AI V4."""

from __future__ import annotations

import asyncio
import pytest

from aru.services.heartbeat import HeartbeatEvent, HeartbeatService
from aru.services.scheduler import SchedulerService


@pytest.mark.asyncio
async def test_heartbeat_pulse_and_callbacks():
    received_events: list[HeartbeatEvent] = []

    async def on_pulse(evt: HeartbeatEvent):
        received_events.append(evt)

    service = HeartbeatService(interval_seconds=0.1)
    service.register_callback(on_pulse)

    assert service.pulse_count == 0
    event1 = await service.emit_pulse({"worker": "main"})

    assert event1.pulse_count == 1
    assert event1.status == "ok"
    assert event1.uptime_seconds >= 0.0
    assert event1.metadata["worker"] == "main"
    assert len(received_events) == 1
    assert service.last_event == event1

    event2 = await service.emit_pulse()
    assert event2.pulse_count == 2
    assert len(received_events) == 2


@pytest.mark.asyncio
async def test_heartbeat_scheduled():
    scheduler = SchedulerService()
    scheduler.start()

    service = HeartbeatService(scheduler=scheduler, interval_seconds=0.2)
    service.start_scheduled()

    assert any(j.id == "heartbeat_service_job" for j in scheduler.list_jobs())

    await service.stop()
    assert not any(j.id == "heartbeat_service_job" for j in scheduler.list_jobs())
    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_heartbeat_standalone_loop():
    service = HeartbeatService(interval_seconds=0.1)
    await service.start()

    await asyncio.sleep(0.25)
    assert service.pulse_count >= 1

    await service.stop()
