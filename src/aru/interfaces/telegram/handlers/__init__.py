"""Telegram handlers package for ARU AI V4."""

from __future__ import annotations

from aru.interfaces.telegram.handlers.callback import CallbackHandler
from aru.interfaces.telegram.handlers.command import CommandHandler
from aru.interfaces.telegram.handlers.media import MediaHandler
from aru.interfaces.telegram.handlers.message import MessageHandler
from aru.interfaces.telegram.handlers.voice import VoiceHandler

__all__ = [
    "CallbackHandler",
    "CommandHandler",
    "MediaHandler",
    "MessageHandler",
    "VoiceHandler",
]
