"""OpenAI provider backward-compatibility module redirected to OpenRouterProvider."""

from __future__ import annotations

from modules.llm.openrouter_provider import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_MODELS,
    OpenRouterProvider,
    OpenAIProvider,
)

OPENAI_CHAT_URL = OPENROUTER_CHAT_URL

__all__ = [
    "OpenRouterProvider",
    "OpenAIProvider",
    "OPENAI_CHAT_URL",
    "OPENROUTER_CHAT_URL",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_MODELS",
]
