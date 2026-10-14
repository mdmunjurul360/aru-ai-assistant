"""Exceptions for ARU AI V4 Brain and LLM providers."""

from __future__ import annotations


class BrainError(Exception):
    """Base exception for all Brain layer errors."""


class ProviderError(BrainError):
    """Base exception for LLM provider execution failures."""

    def __init__(self, provider: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.message = message
        self.status_code = status_code


class ProviderRateLimitError(ProviderError):
    """Raised when provider returns HTTP 429 rate limit error."""


class ProviderTimeoutError(ProviderError):
    """Raised when an inference call exceeds configured timeout."""


class ProviderAuthenticationError(ProviderError):
    """Raised on HTTP 401 or 403 invalid API credentials."""


class AllProvidersFailedError(BrainError):
    """Raised when all configured providers in the fallback chain fail."""
