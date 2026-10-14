"""Asynchronous update dispatcher and middleware pipeline for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from aru.interfaces.telegram.handlers.callback import CallbackHandler
from aru.interfaces.telegram.handlers.command import CommandHandler
from aru.interfaces.telegram.handlers.media import MediaHandler
from aru.interfaces.telegram.handlers.message import MessageHandler
from aru.interfaces.telegram.handlers.voice import VoiceHandler
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

MiddlewareCallable = Callable[[TelegramUpdateContext, Callable[[TelegramUpdateContext], Awaitable[None]]], Awaitable[None]]


class TelegramDispatcher:
    """
    Central event router executing the middleware pipeline and delegating
    requests to command, message, callback, media, or voice handlers.
    """

    def __init__(
        self,
        command_handler: CommandHandler | None = None,
        message_handler: MessageHandler | None = None,
        callback_handler: CallbackHandler | None = None,
        media_handler: MediaHandler | None = None,
        voice_handler: VoiceHandler | None = None,
    ) -> None:
        self._middlewares: list[MiddlewareCallable] = []
        self._command_handler = command_handler or CommandHandler()
        self._message_handler = message_handler or MessageHandler()
        self._callback_handler = callback_handler or CallbackHandler()
        self._media_handler = media_handler or MediaHandler()
        self._voice_handler = voice_handler or VoiceHandler()

    def use(self, middleware: MiddlewareCallable) -> TelegramDispatcher:
        """Register a middleware into the execution pipeline."""
        self._middlewares.append(middleware)
        return self

    async def _terminal_handler(self, ctx: TelegramUpdateContext) -> None:
        """Core router after all middlewares have approved the request."""
        if ctx.is_blocked:
            return

        # 1. Voice
        if ctx.metadata.get("is_voice"):
            if await self._voice_handler.handle_voice(ctx):
                return

        # 2. Media
        if ctx.metadata.get("media_type"):
            if await self._media_handler.handle_media(ctx):
                return

        # 3. Callback
        if ctx.metadata.get("callback_data"):
            if await self._callback_handler.handle_callback(ctx):
                return

        # 4. Command
        if ctx.text.strip().startswith("/"):
            if await self._command_handler.handle_command(ctx):
                return

        # 5. Message
        await self._message_handler.handle_message(ctx)

    async def dispatch(self, ctx: TelegramUpdateContext) -> TelegramUpdateContext:
        """
        Execute middleware onion pipeline and dispatch context to terminal handler.
        """
        async def execute_layer(index: int, current_ctx: TelegramUpdateContext) -> None:
            if index < len(self._middlewares):
                middleware = self._middlewares[index]

                async def next_step(next_ctx: TelegramUpdateContext) -> None:
                    await execute_layer(index + 1, next_ctx)

                await middleware(current_ctx, next_step)
            else:
                await self._terminal_handler(current_ctx)

        await execute_layer(0, ctx)
        return ctx
