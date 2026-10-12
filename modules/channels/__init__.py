"""Multi-Channel Connectors package: WhatsApp, Gmail, Discord, Telegram, REST API, Webhooks."""

from __future__ import annotations

from modules.channels.adapters import (
    DiscordChannelAdapter,
    GmailChannelAdapter,
    RestApiChannelAdapter,
    TelegramChannelAdapter,
    WebhookChannelAdapter,
    WhatsAppChannelAdapter,
)
from modules.channels.base import (
    BaseChannelAdapter,
    ChannelMessage,
    ChannelType,
)
from modules.channels.manager import ChannelManager

__all__ = [
    "ChannelType",
    "ChannelMessage",
    "BaseChannelAdapter",
    "TelegramChannelAdapter",
    "WhatsAppChannelAdapter",
    "DiscordChannelAdapter",
    "GmailChannelAdapter",
    "RestApiChannelAdapter",
    "WebhookChannelAdapter",
    "ChannelManager",
]
