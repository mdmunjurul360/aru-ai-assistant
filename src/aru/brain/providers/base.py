"""Base class for all LLM providers in ARU AI V4."""

from __future__ import annotations

import abc
import time
from typing import Any
import httpx

from aru.brain.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from aru.brain.interfaces import ILLMProvider
from aru.brain.models import LLMMessage, LLMResponse, TokenUsage
from aru.core.logging import StructuredLogger


class BaseLLMProvider(abc.ABC, ILLMProvider):
    """
    Abstract base provider managing API key rotation, HTTP client lifecycles,
    metrics recording, and normalized exception mapping.
    """

    def __init__(
        self,
        name: str,
        api_keys: list[str] | None = None,
        default_model: str = "",
        default_timeout: float = 30.0,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._name = name.strip().lower()
        self._api_keys = [k.strip() for k in (api_keys or []) if k and k.strip()]
        self._default_model = default_model
        self._default_timeout = default_timeout
        self._key_index = 0
        self._logger = logger or StructuredLogger(f"aru.brain.{self._name}")
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def is_available(self) -> bool:
        """Returns True if provider has at least one configured API key."""
        return len(self._api_keys) > 0

    def _get_current_key(self) -> str:
        """Retrieve current active API key from pool."""
        if not self._api_keys:
            return ""
        return self._api_keys[self._key_index % len(self._api_keys)]

    def _rotate_key(self) -> str:
        """Advance to next API key in pool."""
        if len(self._api_keys) > 1:
            self._key_index = (self._key_index + 1) % len(self._api_keys)
            self._logger.info("Rotated to API key index %d for %s", self._key_index, self._name)
        return self._get_current_key()

    async def get_client(self) -> httpx.AsyncClient:
        """Return or instantiate persistent async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._default_timeout)
        return self._client

    async def close(self) -> None:
        """Close HTTP client session."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Execute chat completion request."""
        raise NotImplementedError

    def _handle_http_error(self, err: Exception, status_code: int | None = None, response_text: str = "") -> None:
        """Translate HTTP and network errors into standard Brain exceptions."""
        if isinstance(err, httpx.TimeoutException):
            raise ProviderTimeoutError(
                provider=self._name,
                message=f"Request timed out: {err}",
            ) from err

        if status_code == 429:
            self._rotate_key()
            raise ProviderRateLimitError(
                provider=self._name,
                message=f"Rate limit exceeded (429): {response_text or err}",
                status_code=429,
            )

        if status_code in (401, 403):
            raise ProviderAuthenticationError(
                provider=self._name,
                message=f"Authentication failed ({status_code}): {response_text or err}",
                status_code=status_code,
            )

        raise ProviderError(
            provider=self._name,
            message=f"HTTP request error ({status_code}): {response_text or err}",
            status_code=status_code,
        )
