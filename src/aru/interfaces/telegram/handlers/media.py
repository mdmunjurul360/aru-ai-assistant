"""Media attachment handler for Telegram in ARU AI V4."""

from __future__ import annotations

from typing import Any
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext


class MediaHandler:
    """Processes document, PDF, and image payloads attached to Telegram messages."""

    async def handle_media(self, ctx: TelegramUpdateContext) -> bool:
        """Route media updates."""
        media_type = ctx.metadata.get("media_type")
        if not media_type:
            return False

        if media_type == "pdf":
            filename = ctx.metadata.get("filename", "document.pdf")
            ctx.reply_text = f"📄 Received PDF document: '{filename}'. Ready for processing."
            ctx.handled = True
            return True

        if media_type == "image":
            ctx.reply_text = "🖼️ Received image attachment. Vision processing active."
            ctx.handled = True
            return True

        ctx.reply_text = f"📎 Received media payload of type: '{media_type}'."
        ctx.handled = True
        return True
