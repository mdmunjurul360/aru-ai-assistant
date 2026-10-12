"""Multi-Provider LLM Failover System for Aru AI Personal OS."""

from __future__ import annotations

from modules.llm.base_provider import (
    BaseLLMProvider,
    ProviderHealthState,
    ProviderHealthStatus,
)
from modules.llm.cloudflare_provider import CloudflareProvider
from modules.llm.deepseek_provider import DeepSeekProvider
from modules.llm.exceptions import (
    AllProvidersFailedError,
    CircuitBreakerOpenError,
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.gemini_provider import GeminiProvider
from modules.llm.groq_provider import GroqProvider
from modules.llm.openrouter_provider import OpenRouterProvider, OpenAIProvider
from modules.llm.provider_manager import ProviderManager

__all__ = [
    "BaseLLMProvider",
    "ProviderHealthState",
    "ProviderHealthStatus",
    "CloudflareProvider",
    "GeminiProvider",
    "OpenRouterProvider",
    "OpenAIProvider",
    "GroqProvider",
    "DeepSeekProvider",
    "ProviderManager",
    "LLMProviderError",
    "ProviderUnavailableError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderAuthenticationError",
    "CircuitBreakerOpenError",
    "AllProvidersFailedError",
]
