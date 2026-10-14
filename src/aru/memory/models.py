"""Memory domain models for ARU AI V4."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ConversationMessage(BaseModel):
    """A single turn in conversational memory."""

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="Message author role: user, assistant, system, tool")
    content: str = Field(description="Textual payload of message")
    timestamp: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def estimated_tokens(self) -> int:
        """Heuristic token estimate (approx 4 characters per token + 4 overhead)."""
        return max(1, (len(self.content) // 4) + 4)


class MemoryFact(BaseModel):
    """An episodic long-term knowledge item or user preference."""

    model_config = ConfigDict(frozen=True)

    id: int | None = None
    key: str | None = None
    content: str
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
