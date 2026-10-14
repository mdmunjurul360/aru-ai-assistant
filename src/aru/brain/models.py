"""Domain models for ARU AI V4 Brain and LLM inference."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    """Normalized chat completion message representation."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant", "tool"] = Field(
        description="Message author role"
    )
    content: str = Field(description="Message text payload")
    name: str | None = Field(default=None, description="Optional name identifier")
    tool_call_id: str | None = Field(default=None, description="Tool call identifier")

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible dictionary."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


class TokenUsage(BaseModel):
    """Token consumption metrics for a completion."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """Normalized response payload from an LLM inference call."""

    model_config = ConfigDict(frozen=True)

    content: str
    model: str
    provider: str
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    raw_response: dict[str, Any] | None = None
