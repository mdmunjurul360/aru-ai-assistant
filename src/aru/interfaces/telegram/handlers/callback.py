"""Callback query router for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


class CallbackHandler:
    """Handles inline keyboard callback events."""

    async def handle_callback(self, ctx: TelegramUpdateContext) -> bool:
        """Process callback query data."""
        data = ctx.metadata.get("callback_data", "")
        if not data:
            return False

        if data.startswith("task_done:"):
            task_id = data.split("task_done:", 1)[1]
            ctx.reply_text = f"Marked task #{task_id} as complete."
            ctx.handled = True
            return True

        ctx.reply_text = f"Callback received: {data}"
        ctx.handled = True
        return True
