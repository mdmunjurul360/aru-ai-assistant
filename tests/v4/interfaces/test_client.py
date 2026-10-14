"""Unit tests for TelegramClientManager lifecycle and message splitting in ARU AI V4."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from pydantic import SecretStr

from aru.core.config.models import AppSettings, SystemSettings, TelegramSettings
from aru.interfaces.telegram.client import TelegramClientManager
from aru.interfaces.telegram.dispatcher import TelegramDispatcher
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


@pytest.fixture
def mock_telethon():
    client = MagicMock()
    client.is_connected = MagicMock(return_value=True)
    client.is_user_authorized = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_me = AsyncMock(return_value=MagicMock(username="arubot", id=111))
    client.send_message = AsyncMock(return_value=MagicMock(id=999))
    client.on = MagicMock(return_value=lambda f: f)
    return client


@pytest.fixture
def test_settings(tmp_path: Path) -> AppSettings:
    sys_settings = SystemSettings.create_default(tmp_path)
    tg_settings = TelegramSettings(
        tg_api_id=12345,
        tg_api_hash=SecretStr("hashsecret"),
        boss_telegram_id=8888,
        session_path=str(tmp_path / "sessions" / "test_aru"),
    )
    return AppSettings(telegram=tg_settings, system=sys_settings)


@pytest.mark.asyncio
async def test_client_lifecycle_authorized(test_settings: AppSettings, mock_telethon):
    manager = TelegramClientManager(settings=test_settings, client=mock_telethon)

    assert manager.is_connected is True
    started = await manager.start(interactive=False)
    assert started is True
    assert await manager.is_authorized() is True

    await manager.stop()
    mock_telethon.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_lifecycle_unauthorized(test_settings: AppSettings, mock_telethon):
    mock_telethon.is_user_authorized = AsyncMock(return_value=False)
    manager = TelegramClientManager(settings=test_settings, client=mock_telethon)

    started = await manager.start(interactive=False)
    assert started is False


@pytest.mark.asyncio
async def test_client_send_split_message(test_settings: AppSettings, mock_telethon):
    manager = TelegramClientManager(settings=test_settings, client=mock_telethon)

    # Short message
    await manager.send_message(chat_id=123, text="Hello there")
    mock_telethon.send_message.assert_awaited_once_with(
        entity=123,
        message="Hello there",
        reply_to=None,
        parse_mode="md",
    )

    mock_telethon.send_message.reset_mock()

    # Long message requiring split (>4096 chars)
    long_msg = "A" * 5000
    sent = await manager.send_split_message(chat_id=123, text=long_msg, reply_to=456)
    assert len(sent) >= 2
    assert mock_telethon.send_message.await_count >= 2


@pytest.mark.asyncio
async def test_client_send_to_boss(test_settings: AppSettings, mock_telethon):
    manager = TelegramClientManager(settings=test_settings, client=mock_telethon)

    await manager.send_to_boss("Alert for Boss")
    mock_telethon.send_message.assert_awaited_once_with(
        entity=8888,
        message="Alert for Boss",
        reply_to=None,
        parse_mode="md",
    )


@pytest.mark.asyncio
async def test_client_handle_new_message(test_settings: AppSettings, mock_telethon):
    dispatcher = TelegramDispatcher()
    manager = TelegramClientManager(settings=test_settings, dispatcher=dispatcher, client=mock_telethon)

    event = MagicMock()
    event.id = 55
    event.sender_id = 123
    event.chat_id = 123
    event.text = "/ping"
    event.voice = None
    event.photo = None
    event.document = None

    await manager._handle_new_message(event)

    # Verifies that response to /ping was sent via mock_telethon
    mock_telethon.send_message.assert_awaited()
    args, kwargs = mock_telethon.send_message.call_args
    assert "Pong!" in kwargs["message"]
    assert kwargs["reply_to"] == 55


@pytest.mark.asyncio
async def test_client_handle_callback_query(test_settings: AppSettings, mock_telethon):
    dispatcher = TelegramDispatcher()
    manager = TelegramClientManager(settings=test_settings, dispatcher=dispatcher, client=mock_telethon)

    event = MagicMock()
    event.sender_id = 123
    event.chat_id = 123
    event.data = b"task_done:9"
    event.answer = AsyncMock()

    await manager._handle_callback_query(event)

    event.answer.assert_awaited_once_with("Marked task #9 as complete.")
