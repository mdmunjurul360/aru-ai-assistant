"""ChannelManager coordinating multi-channel adapters and message routing."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from modules.channels.base import BaseChannelAdapter, ChannelMessage, ChannelType

logger = logging.getLogger("aru.channels.manager")


class ChannelManager:
    """
    Central orchestration hub for all communication channels.
    Registers adapters, routes inbound messages to AruBot / ReAct / Multi-Agent,
    and broadcasts responses back.
    """

    def __init__(self) -> None:
        self._adapters: dict[ChannelType, BaseChannelAdapter] = {}
        self._global_handler: Callable[[ChannelMessage], Awaitable[Any]] | None = None

    @property
    def adapters(self) -> dict[ChannelType, BaseChannelAdapter]:
        return dict(self._adapters)

    def register_adapter(self, adapter: BaseChannelAdapter) -> None:
        self._adapters[adapter.channel_type] = adapter
        adapter.set_message_handler(self._on_adapter_message)
        logger.info("Channel adapter registered: %s (%s)", adapter.name, adapter.channel_type.value)

    def get_adapter(self, channel_type: ChannelType | str) -> BaseChannelAdapter | None:
        key = ChannelType(channel_type) if isinstance(channel_type, str) else channel_type
        return self._adapters.get(key)

    def set_global_message_handler(self, handler: Callable[[ChannelMessage], Awaitable[Any]]) -> None:
        self._global_handler = handler

    async def _on_adapter_message(self, message: ChannelMessage) -> Any:
        logger.info("Inbound message from [%s] user=%s len=%d", message.channel.value, message.sender_id, len(message.text))
        if self._global_handler:
            return await self._global_handler(message)
        return f"Echo from Aru: {message.text}"

    async def send_to_channel(
        self,
        channel_type: ChannelType | str,
        recipient_id: str,
        text: str,
        **kwargs: Any,
    ) -> bool:
        adapter = self.get_adapter(channel_type)
        if not adapter:
            logger.error("No adapter registered for channel: %s", channel_type)
            return False
        return await adapter.send_message(recipient_id, text, **kwargs)

    def list_channels(self) -> list[dict[str, Any]]:
        return [
            {
                "channel": a.channel_type.value,
                "name": a.name,
                "connected": a.is_connected,
            }
            for a in self._adapters.values()
        ]
