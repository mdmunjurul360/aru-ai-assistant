"""Contextual structured logging middleware for Telegram in ARU AI V4."""

from __future__ import annotations

import time
from typing import Awaitable, Callable
from aru.core.logging import StructuredLogger, correlation_scope
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

NextHandler = Callable[[TelegramUpdateContext], Awaitable[None]]


class LoggingMiddleware:
    """Attaches correlation scopes and records execution telemetry for Telegram events."""

    def __init__(self, logger: StructuredLogger | None = None) -> None:
        self._logger = logger or StructuredLogger("aru.telegram.middleware")

    async def __call__(self, ctx: TelegramUpdateContext, next_handler: NextHandler) -> None:
        with correlation_scope(ctx.correlation_id):
            start = time.perf_counter()
            self._logger.info(
                "Incoming Telegram message from user=%d chat=%d (text: '%s...')",
                ctx.user_id,
                ctx.chat_id,
                ctx.text[:30].replace("\n", " "),
            )
            try:
                await next_handler(ctx)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                self._logger.info(
                    "Telegram update completed in %.2fms (handled=%s, blocked=%s)",
                    elapsed_ms,
                    ctx.handled,
                    ctx.is_blocked,
                )
