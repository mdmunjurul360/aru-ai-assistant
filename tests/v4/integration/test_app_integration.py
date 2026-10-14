"""End-to-end integration tests for ARU AI V4 Application Bootstrap and Pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import SecretStr

from aru.app import AruApplication
from aru.brain.models import LLMResponse
from aru.core.config.models import AppSettings, SystemSettings, TelegramSettings
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext
from aru.planner.models import Goal
from aru.tools.models import ExecutionContext


@pytest.fixture
def integration_app(tmp_path: Path) -> AruApplication:
    root_dir = tmp_path / "aru_root"
    root_dir.mkdir(parents=True, exist_ok=True)
    sys_settings = SystemSettings.create_default(root_dir)
    tg_settings = TelegramSettings(
        boss_telegram_id=999888,
        secret_code=SecretStr("supersecretcode"),
        unauthorized_reply="Unauthorized Access.",
        session_path=str(root_dir / "sessions" / "test_session"),
    )
    settings = AppSettings(telegram=tg_settings, system=sys_settings)
    app = AruApplication.create(settings)
    return app


@pytest.mark.asyncio
async def test_full_application_startup_and_shutdown(integration_app: AruApplication):
    app = integration_app

    assert not app.is_running
    assert not app.db_manager.is_connected
    assert not app.scheduler.is_running

    # Startup
    await app.startup(start_telegram=False, start_scheduler=True)

    assert app.is_running is True
    assert app.db_manager.is_connected is True
    assert app.scheduler.is_running is True

    # Verify background services registered with scheduler
    jobs = app.scheduler.list_jobs()
    job_ids = {j.id for j in jobs}
    assert "heartbeat_service_job" in job_ids
    assert "db_maintenance_job" in job_ids
    assert "nightly_cleanup_job" in job_ids
    assert "health_monitor_job" in job_ids
    assert "due_tasks_scanner_job" in job_ids

    # Verify migrations applied tables in sqlite
    async with app.db_manager.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = [row[0] for row in await cursor.fetchall()]
        assert "_v4_migrations" in tables
        assert "conversations" in tables
        assert "memories" in tables
        assert "tasks" in tables
        assert "anti_spam_cooldowns" in tables

    # Graceful shutdown
    await app.shutdown()

    assert app.is_running is False
    assert app.db_manager.is_connected is False
    assert app.scheduler.is_running is False


@pytest.mark.asyncio
async def test_telegram_message_flow_and_middleware(integration_app: AruApplication):
    app = integration_app
    await app.startup(start_telegram=False, start_scheduler=False)

    try:
        # 1. Unauthorized user blocked by AuthMiddleware
        unauth_ctx = TelegramUpdateContext(
            user_id=111,
            chat_id=111,
            text="/ping",
        )
        await app.dispatcher.dispatch(unauth_ctx)
        assert unauth_ctx.is_blocked is True
        assert unauth_ctx.block_reason == "unauthorized"
        assert unauth_ctx.reply_text == "Unauthorized Access."

        # 2. Boss user passes AuthMiddleware -> CommandHandler -> /ping -> Pong!
        boss_ctx = TelegramUpdateContext(
            user_id=999888,
            chat_id=999888,
            text="/ping",
        )
        await app.dispatcher.dispatch(boss_ctx)
        assert boss_ctx.is_blocked is False
        assert boss_ctx.is_authorized is True
        assert boss_ctx.handled is True
        assert "Pong!" in (boss_ctx.reply_text or "")

        # 3. Boss command /status
        status_ctx = TelegramUpdateContext(
            user_id=999888,
            chat_id=999888,
            text="/status",
        )
        await app.dispatcher.dispatch(status_ctx)
        assert "ARU AI V4 Online" in (status_ctx.reply_text or "")

    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_memory_persistence_flow(integration_app: AruApplication):
    app = integration_app
    await app.startup(start_telegram=False, start_scheduler=False)

    try:
        session_id = "test_chat_100"

        # 1. Add working memory via chat
        await app.memory_service.add_user_message(session_id, user_id=999888, content="My favorite color is Blue.")
        await app.memory_service.add_assistant_message(session_id, content="Noted that your favorite color is Blue.")

        history = app.memory_service.working_memory.get_messages(session_id)
        assert len(history) == 2
        assert history[0].content == "My favorite color is Blue."
        assert history[1].content == "Noted that your favorite color is Blue."

        # 2. Add persistent fact to SQLite
        fact_id = await app.memory_service.remember(
            content="Boss prefers responses in concise markdown format.",
            category="preferences",
        )
        assert fact_id > 0

        # 3. Search persistent memory
        results = await app.memory_service.recall("markdown")
        assert len(results) >= 1
        assert "concise markdown" in results[0].content

    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_planner_and_tool_execution_integration(integration_app: AruApplication):
    app = integration_app
    await app.startup(start_telegram=False, start_scheduler=False)

    try:
        # Message asking for math calculation
        math_ctx = TelegramUpdateContext(
            user_id=999888,
            chat_id=999888,
            text="calculate (15 * 4) + 40",
            is_boss=True,
        )

        # Dispatch through complete Telegram -> Middleware -> MessageHandler -> Decomposer -> Executor pipeline
        await app.dispatcher.dispatch(math_ctx)

        assert math_ctx.handled is True
        assert math_ctx.reply_text is not None
        assert "100" in math_ctx.reply_text
        assert "Result" in math_ctx.reply_text

    finally:
        await app.shutdown()


@pytest.mark.asyncio
async def test_background_services_integration(integration_app: AruApplication):
    app = integration_app
    await app.startup(start_telegram=False, start_scheduler=False)

    try:
        # 1. Heartbeat
        pulse = await app.heartbeat.emit_pulse()
        assert pulse.pulse_count == 1
        assert pulse.status == "ok"

        # 2. Database Maintenance
        report = await app.maintenance.run_full_maintenance()
        assert report.status == "success"
        assert report.vacuum_success is True

        # 3. Health Monitor
        health = await app.health_monitor.get_health_status()
        assert health.status in ("healthy", "degraded")
        assert health.database.status == "healthy"

        # 4. Reminders & Tasks
        # Create an overdue task in repository
        await app.task_repo.create(title="Urgent security review", due_date="2020-01-01T00:00:00")
        overdue_notified = await app.reminder.check_due_tasks()
        assert overdue_notified == 1

        # 5. Cleanup
        cleanup_report = await app.cleanup.run_nightly_cleanup()
        assert cleanup_report.status == "success"

    finally:
        await app.shutdown()


def test_dependency_injection_resolution(integration_app: AruApplication):
    app = integration_app
    container = app.container

    # Verify every major component can be resolved independently from DI container
    from aru.brain.router import LLMRouter
    from aru.core.config.models import AppSettings
    from aru.database.connection import DatabaseManager
    from aru.executor.engine import PlanExecutor
    from aru.interfaces.telegram.client import TelegramClientManager
    from aru.interfaces.telegram.dispatcher import TelegramDispatcher
    from aru.memory.service import MemoryService
    from aru.planner.decomposer import GoalDecomposer
    from aru.services.health_monitor import HealthMonitorService
    from aru.services.scheduler import SchedulerService
    from aru.tools.registry import ToolRegistry

    assert isinstance(container.resolve(AppSettings), AppSettings)
    assert isinstance(container.resolve(DatabaseManager), DatabaseManager)
    assert isinstance(container.resolve(MemoryService), MemoryService)
    assert isinstance(container.resolve(ToolRegistry), ToolRegistry)
    assert isinstance(container.resolve(LLMRouter), LLMRouter)
    assert isinstance(container.resolve(GoalDecomposer), GoalDecomposer)
    assert isinstance(container.resolve(PlanExecutor), PlanExecutor)
    assert isinstance(container.resolve(SchedulerService), SchedulerService)
    assert isinstance(container.resolve(HealthMonitorService), HealthMonitorService)
    assert isinstance(container.resolve(TelegramDispatcher), TelegramDispatcher)
    assert isinstance(container.resolve(TelegramClientManager), TelegramClientManager)
