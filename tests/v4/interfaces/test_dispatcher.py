"""Unit tests for TelegramDispatcher and middleware pipeline in ARU AI V4."""

from __future__ import annotations

import pytest

from aru.interfaces.telegram.dispatcher import TelegramDispatcher
from aru.interfaces.telegram.handlers.callback import CallbackHandler
from aru.interfaces.telegram.handlers.command import CommandHandler
from aru.interfaces.telegram.handlers.media import MediaHandler
from aru.interfaces.telegram.handlers.message import MessageHandler
from aru.interfaces.telegram.handlers.voice import VoiceHandler
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


@pytest.mark.asyncio
async def test_dispatcher_onion_execution_order():
    trail: list[str] = []

    async def middleware_1(ctx: TelegramUpdateContext, next_step):
        trail.append("m1_in")
        await next_step(ctx)
        trail.append("m1_out")

    async def middleware_2(ctx: TelegramUpdateContext, next_step):
        trail.append("m2_in")
        await next_step(ctx)
        trail.append("m2_out")

    dispatcher = TelegramDispatcher()
    dispatcher.use(middleware_1).use(middleware_2)

    ctx = TelegramUpdateContext(text="/ping")
    await dispatcher.dispatch(ctx)

    assert trail == ["m1_in", "m2_in", "m2_out", "m1_out"]
    assert ctx.handled is True
    assert "Pong!" in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_dispatcher_blocked_short_circuit():
    async def blocking_middleware(ctx: TelegramUpdateContext, next_step):
        ctx.is_blocked = True
        ctx.reply_text = "Blocked at gate"

    dispatcher = TelegramDispatcher()
    dispatcher.use(blocking_middleware)

    ctx = TelegramUpdateContext(text="/ping")
    await dispatcher.dispatch(ctx)

    assert ctx.is_blocked is True
    assert ctx.reply_text == "Blocked at gate"
    assert "Pong!" not in (ctx.reply_text or "")


@pytest.mark.asyncio
async def test_dispatcher_routes_by_priority():
    dispatcher = TelegramDispatcher()

    # Voice update
    ctx_voice = TelegramUpdateContext(metadata={"is_voice": True, "duration": 5})
    await dispatcher.dispatch(ctx_voice)
    assert "voice note" in (ctx_voice.reply_text or "").lower()

    # Media update
    ctx_media = TelegramUpdateContext(metadata={"media_type": "pdf", "filename": "doc.pdf"})
    await dispatcher.dispatch(ctx_media)
    assert "pdf document" in (ctx_media.reply_text or "").lower()

    # Callback update
    ctx_cb = TelegramUpdateContext(metadata={"callback_data": "task_done:1"})
    await dispatcher.dispatch(ctx_cb)
    assert "marked task #1" in (ctx_cb.reply_text or "").lower()

    # Command update
    ctx_cmd = TelegramUpdateContext(text="/status")
    await dispatcher.dispatch(ctx_cmd)
    assert "ARU AI V4 Online" in (ctx_cmd.reply_text or "")

    # Regular message update
    ctx_msg = TelegramUpdateContext(text="Good morning")
    await dispatcher.dispatch(ctx_msg)
    assert "Echo: Good morning" in (ctx_msg.reply_text or "")
