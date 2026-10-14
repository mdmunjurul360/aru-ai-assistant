"""Base Channel Adapter and unified ChannelMessage contract."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger("aru.channels.base")


class ChannelType(str, Enum):
    """Supported communication channels."""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    GMAIL = "gmail"
    REST_API = "rest_api"
    WEBHOOK = "webhook"


@dataclass
class ChannelMessage:
    """Normalized cross-channel message envelope."""
    message_id: str
    channel: ChannelType
    sender_id: str
    recipient_id: str
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def create(
        cls,
        channel: ChannelType,
        sender_id: str,
        text: str,
        recipient_id: str = "",
        raw_payload: dict[str, Any] | None = None,
    ) -> ChannelMessage:
        return cls(
            message_id=str(uuid.uuid4())[:8],
            channel=channel,
            sender_id=str(sender_id),
            recipient_id=str(recipient_id),
            text=text,
            raw_payload=raw_payload or {},
        )


class BaseChannelAdapter(ABC):
    """Abstract interface for all external communication channels."""
    channel_type: ChannelType
    name: str

    def __init__(self) -> None:
        self._connected = False
        self._message_handler: Callable[[ChannelMessage], Awaitable[Any]] | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_message_handler(self, handler: Callable[[ChannelMessage], Awaitable[Any]]) -> None:
        self._message_handler = handler

    @abstractmethod
    async def connect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_message(self, recipient_id: str, text: str, **kwargs: Any) -> bool:
        raise NotImplementedError

    async def dispatch_inbound(self, message: ChannelMessage) -> Any:
        """Route received external message to Aru's core handler."""
        if self._message_handler:
            return await self._message_handler(message)
        logger.warning("[%s] No message handler registered for inbound message", self.name)
        return None
