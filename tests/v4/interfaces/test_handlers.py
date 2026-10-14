"""Unit tests for Telegram update handlers in ARU AI V4."""

from __future__ import annotations

from pathlib import Path
import pytest

from aru.database.connection import DatabaseManager
from aru.database.migrations.runner import MigrationRunner
from aru.database.repositories.task_repo import TaskRepository
from aru.interfaces.telegram.handlers.callback import CallbackHandler
from aru.interfaces.telegram.handlers.command import CommandHandler
from aru.interfaces.telegram.handlers.media import MediaHandler
from aru.interfaces.telegram.handlers.message import MessageHandler
from aru.interfaces.telegram.handlers.voice import VoiceHandler
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext
from aru.memory.service import MemoryService
from aru.memory.working_memory import WorkingMemory


@pytest.fixture
async def task_repo(tmp_path: Path) -> TaskRepository:
    db = DatabaseManager(tmp_path / "test_handlers.db")
    runner = MigrationRunner(db)
    await runner.run()
    repo = TaskRepository(db)
    yield repo
    await db.disconnect()


@pytest.mark.asyncio
async def test_command_handler_help():
    handler = CommandHandler()
    ctx = TelegramUpdateContext(text="/help")
    handled = await handler.handle_command(ctx)

    assert handled is True
    assert ctx.handled is True
    assert "• `/start`" in (ctx.reply_text or "")
    assert "• `/status`" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_command_handler_ping():
    handler = CommandHandler()
    ctx = TelegramUpdateContext(text="/ping")
    handled = await handler.handle_command(ctx)

    assert handled is True
    assert "Pong!" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_command_handler_clear():
    working = WorkingMemory()
    working.add_message("100", "user", "Hello")
    memory_service = MemoryService(working_memory=working)

    handler = CommandHandler(memory_service=memory_service)
    ctx = TelegramUpdateContext(chat_id=100, text="/clear")
    handled = await handler.handle_command(ctx)

    assert handled is True
    assert "cleared" in (ctx.reply_text or "")
    assert working.get_messages("100") == []


@pytest.mark.asyncio
async def test_command_handler_tasks(task_repo: TaskRepository):
    await task_repo.create(title="Buy milk", priority="high")
    handler = CommandHandler(task_repo=task_repo)

    ctx = TelegramUpdateContext(text="/tasks")
    handled = await handler.handle_command(ctx)

    assert handled is True
    assert "Buy milk" in (ctx.reply_text or "")
    assert "[HIGH]" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_callback_handler():
    handler = CallbackHandler()
    ctx = TelegramUpdateContext(metadata={"callback_data": "task_done:42"})
    handled = await handler.handle_callback(ctx)

    assert handled is True
    assert "Marked task #42 as complete" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_media_handler():
    handler = MediaHandler()

    ctx_pdf = TelegramUpdateContext(metadata={"media_type": "pdf", "filename": "report.pdf"})
    assert await handler.handle_media(ctx_pdf) is True
    assert "report.pdf" in (ctx_pdf.reply_text or "")

    ctx_img = TelegramUpdateContext(metadata={"media_type": "image"})
    assert await handler.handle_media(ctx_img) is True
    assert "image attachment" in (ctx_img.reply_text or "")


@pytest.mark.asyncio
async def test_voice_handler():
    handler = VoiceHandler()
    ctx = TelegramUpdateContext(metadata={"is_voice": True, "duration": 15})
    assert await handler.handle_voice(ctx) is True
    assert "15s" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_message_handler_fallback():
    handler = MessageHandler()
    ctx = TelegramUpdateContext(chat_id=123, user_id=456, text="Hello Aru")
    assert await handler.handle_message(ctx) is True
    assert ctx.handled is True
    assert "Echo: Hello Aru" in (ctx.reply_text or "")
