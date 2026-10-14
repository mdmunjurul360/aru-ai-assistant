"""Authentication and authorization middleware for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Awaitable, Callable
from aru.core.config.models import AppSettings
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

NextHandler = Callable[[TelegramUpdateContext], Awaitable[None]]


class AuthMiddleware:
    """Verifies sender identity against Boss ID, whitelist, or unlock secret code."""

    def __init__(
        self,
        settings: AppSettings,
        anti_spam_repo: AntiSpamRepository | None = None,
    ) -> None:
        self._boss_id = settings.telegram.boss_telegram_id
        self._secret_code = settings.telegram.secret_code.get_secret_value()
        self._unauthorized_reply = settings.telegram.unauthorized_reply
        self._anti_spam_repo = anti_spam_repo

    async def __call__(self, ctx: TelegramUpdateContext, next_handler: NextHandler) -> None:
        # Check if sender is the Boss
        if ctx.user_id != 0 and ctx.user_id == self._boss_id:
            ctx.is_boss = True
            ctx.is_authorized = True
            await next_handler(ctx)
            return

        # Check /unlock command with secret code
        if self._secret_code and ctx.text.startswith("/unlock"):
            parts = ctx.text.split(maxsplit=1)
            code_provided = parts[1].strip() if len(parts) > 1 else ""
            if code_provided == self._secret_code:
                ctx.is_authorized = True
                if self._anti_spam_repo:
                    await self._anti_spam_repo.add_to_whitelist(ctx.user_id, notes="Unlocked via secret code")
                ctx.reply_text = "Authentication successful. You have been added to the whitelist."
                ctx.handled = True
                return

        # Check whitelist
        if self._anti_spam_repo and await self._anti_spam_repo.is_whitelisted(ctx.user_id):
            ctx.is_authorized = True
            await next_handler(ctx)
            return

        # Unauthorized access
        ctx.is_authorized = False
        ctx.is_blocked = True
        ctx.block_reason = "unauthorized"
        ctx.reply_text = self._unauthorized_reply
        ctx.handled = True
