"""Exceptions for Multi-Provider LLM Failover System."""

from __future__ import annotations

from typing import Any


class LLMProviderError(Exception):
    """Base exception for all LLM provider errors."""

    def __init__(
        self,
        message: str,
        provider: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code

    def __str__(self) -> str:
        prefix = f"[{self.provider.upper()}] " if self.provider else ""
        code_str = f" (status={self.status_code})" if self.status_code else ""
        return f"{prefix}{self.message}{code_str}"


class ProviderUnavailableError(LLMProviderError):
    """Raised when a provider is not configured, disabled, or network unreachable."""


class ProviderRateLimitError(LLMProviderError):
    """Raised when an API responds with HTTP 429 Too Many Requests."""


class ProviderTimeoutError(LLMProviderError):
    """Raised when an API request exceeds the configured timeout."""


class ProviderAuthenticationError(LLMProviderError):
    """Raised when API credentials are rejected (HTTP 401 / 403)."""


class CircuitBreakerOpenError(LLMProviderError):
    """Raised when an operation is requested on a provider currently in cooldown."""


class AllProvidersFailedError(LLMProviderError):
    """Raised when all active providers have failed."""

    def __init__(
        self,
        message: str = "All configured LLM providers failed or are unavailable.",
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ProviderPoolExhaustedError(LLMProviderError):
    """Raised when all API keys in a provider's key pool have failed or are in cooldown."""

    def __init__(
        self,
        message: str = "All API keys in provider pool failed or in cooldown.",
        provider: str = "",
        key_attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.key_attempts = key_attempts or []
