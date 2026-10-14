"""Voice message handler scaffold for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


class VoiceHandler:
    """Scaffold for processing voice notes and audio messages."""

    async def handle_voice(self, ctx: TelegramUpdateContext) -> bool:
        """Process incoming voice message."""
        is_voice = ctx.metadata.get("is_voice", False)
        if not is_voice:
            return False

        duration = ctx.metadata.get("duration", 0)
        ctx.reply_text = f"🎙️ Received voice note ({duration}s). Voice transcription scaffold active."
        ctx.handled = True
        return True
