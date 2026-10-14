"""Context model passed through Telegram middleware pipeline in ARU AI V4."""

from __future__ import annotations

import uuid
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TelegramUpdateContext(BaseModel):
    """Normalized context for an incoming Telegram message or event."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event: Any = None
    user_id: int = 0
    chat_id: int = 0
    text: str = ""
    is_boss: bool = False
    correlation_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    is_authorized: bool = False
    is_blocked: bool = False
    block_reason: str = ""
    reply_text: str | None = None
    handled: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
