"""LLM Provider interfaces and protocols for ARU AI V4."""

from __future__ import annotations

from typing import Protocol
from aru.brain.models import LLMMessage, LLMResponse


class ILLMProvider(Protocol):
    """Protocol for LLM inference providers."""

    @property
    def name(self) -> str: ...

    @property
    def is_available(self) -> bool: ...

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResponse: ...
