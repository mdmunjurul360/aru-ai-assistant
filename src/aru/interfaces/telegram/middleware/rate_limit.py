"""Sliding-window rate limiting middleware for Telegram in ARU AI V4."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from aru.database.repositories.anti_spam_repo import AntiSpamRepository
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

NextHandler = Callable[[TelegramUpdateContext], Awaitable[None]]


class RateLimitMiddleware:
    """Detects message floods using a sliding time window and triggers cooldowns."""

    def __init__(
        self,
        anti_spam_repo: AntiSpamRepository | None = None,
        max_messages: int = 5,
        time_window_seconds: float = 3.0,
        cooldown_duration_minutes: int = 5,
    ) -> None:
        self._repo = anti_spam_repo
        self._max_messages = max_messages
        self._window = time_window_seconds
        self._cooldown_duration = cooldown_duration_minutes
        self._message_times: dict[int, list[float]] = defaultdict(list)

    async def __call__(self, ctx: TelegramUpdateContext, next_handler: NextHandler) -> None:
        # Boss is never rate-limited
        if ctx.is_boss:
            await next_handler(ctx)
            return

        now = time.time()
        user_times = self._message_times[ctx.user_id]

        # Prune timestamps outside window
        user_times = [t for t in user_times if now - t <= self._window]
        user_times.append(now)
        self._message_times[ctx.user_id] = user_times

        if len(user_times) > self._max_messages:
            # Trigger cooldown
            cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self._cooldown_duration)
            if self._repo:
                await self._repo.set_cooldown(
                    user_id=ctx.user_id,
                    cooldown_until=cooldown_until,
                    reason=f"Exceeded {self._max_messages} msgs in {self._window}s",
                )
                await self._repo.record_spam_event(
                    user_id=ctx.user_id,
                    event_type="rate_limit_exceeded",
                    details=f"Flood detected: {len(user_times)} messages",
                )

            ctx.is_blocked = True
            ctx.block_reason = "rate_limit_triggered"
            ctx.reply_text = f"🚨 Rate limit exceeded. You have been placed on cooldown for {self._cooldown_duration} minutes."
            ctx.handled = True
            return

        await next_handler(ctx)
