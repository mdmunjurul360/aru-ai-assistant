"""Telegram interface module for ARU AI V4."""

from aru.interfaces.telegram.client import TelegramClientManager
from aru.interfaces.telegram.dispatcher import TelegramDispatcher
from aru.interfaces.telegram.formatter import (
    escape_markdown,
    format_command_help,
    split_message,
)
from aru.interfaces.telegram.middleware.context import TelegramUpdateContext

__all__ = [
    "TelegramClientManager",
    "TelegramDispatcher",
    "TelegramUpdateContext",
    "split_message",
    "escape_markdown",
    "format_command_help",
]
