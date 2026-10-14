"""Anti-spam cooldown middleware for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Awaitable, Callable
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

NextHandler = Callable[[TelegramUpdateContext], Awaitable[None]]


class AntiSpamMiddleware:
    """Interceps messages from users currently undergoing active rate-limit cooldowns."""

    def __init__(self, anti_spam_repo: AntiSpamRepository | None = None) -> None:
        self._repo = anti_spam_repo

    async def __call__(self, ctx: TelegramUpdateContext, next_handler: NextHandler) -> None:
        # Boss is immune to spam cooldowns
        if ctx.is_boss:
            await next_handler(ctx)
            return

        if self._repo and await self._repo.is_cooled_down(ctx.user_id):
            ctx.is_blocked = True
            ctx.block_reason = "cooldown"
            ctx.reply_text = "⚠️ You are temporarily on cooldown due to excessive messaging. Please wait a moment."
            ctx.handled = True
            return

        await next_handler(ctx)
