"""Base LLM Provider abstract interface and health status models."""

from __future__ import annotations

import abc
import base64
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from modules.llm.exceptions import (
    CircuitBreakerOpenError,
    ProviderUnavailableError,
)


class ProviderHealthState(str, Enum):
    """Health status states for an LLM provider."""

    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    COOLDOWN = "Cooldown"
    DISABLED = "Disabled"


@dataclass
class ProviderHealthStatus:
    """Metrics and state tracking for an LLM provider."""

    provider: str
    status: ProviderHealthState = ProviderHealthState.DISABLED
    latency_ms: float = 0.0
    last_success: str | None = None
    last_failure: str | None = None
    failure_count: int = 0
    success_count: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_seconds_remaining": max(0.0, round(self.cooldown_until - time.time(), 1)),
            "last_error": self.last_error,
        }


class BaseLLMProvider(abc.ABC):
    """
    Abstract interface for LLM providers.
    Provides uniform execution, multi-key pooling, health tracking, and circuit breaker functionality.
    """

    def __init__(
        self,
        name: str,
        api_key: str = "",
        api_keys: list[str] | None = None,
        default_model: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.name = name.strip().lower()
        self.default_model = default_model.strip()
        self.timeout = float(timeout)

        # Build keys list supporting both api_key (singular) and api_keys (plural)
        keys_list: list[Any] = []
        if api_keys:
            for k in api_keys:
                if isinstance(k, dict):
                    keys_list.append(k)
                elif k and str(k).strip():
                    keys_list.append(str(k).strip())
        if api_key and str(api_key).strip() and str(api_key).strip() not in keys_list:
            keys_list.insert(0, str(api_key).strip())

        from modules.llm.key_pool import KeyPool

        self.key_pool = KeyPool(provider_name=self.name, keys=keys_list)
        first_k = keys_list[0] if keys_list else ""
        self._primary_key = first_k.get("api_key", "") if isinstance(first_k, dict) else str(first_k)

        self.health = ProviderHealthStatus(
            provider=self.name.capitalize(),
            status=ProviderHealthState.HEALTHY if self.is_enabled else ProviderHealthState.DISABLED,
        )

    @property
    def api_key(self) -> str:
        """First/primary API key for backward compatibility."""
        first = self.key_pool.first_slot()
        return first.api_key if first else self._primary_key

    @api_key.setter
    def api_key(self, val: str) -> None:
        self._primary_key = (val or "").strip()
        if self._primary_key and not self.key_pool.has_keys:
            from modules.llm.key_pool import KeyPool

            self.key_pool = KeyPool(provider_name=self.name, keys=[self._primary_key])

    @property
    def is_enabled(self) -> bool:
        """A provider is enabled if its key pool has at least one configured key."""
        return self.key_pool.has_keys

    def is_in_cooldown(self) -> bool:
        """Returns True if provider or ALL keys in its pool are currently blocked."""
        if not self.is_enabled:
            return False
        if bool(self.health.cooldown_until and time.time() < self.health.cooldown_until):
            return True
        return not self.key_pool.has_available_slot()

    def cooldown_seconds_remaining(self) -> float:
        """Cooldown seconds remaining across provider and cooling keys in the pool."""
        rem_provider = max(0.0, self.health.cooldown_until - time.time()) if self.health.cooldown_until else 0.0
        rem_pool = self.key_pool.min_cooldown_remaining()
        return max(rem_provider, rem_pool)

    def record_success(self, latency_sec: float) -> None:
        """Record a successful API call, clearing cooldown and updating latency."""
        self.health.success_count += 1
        self.health.consecutive_failures = 0
        self.health.latency_ms = latency_sec * 1000.0
        self.health.last_success = datetime.now(timezone.utc).isoformat()
        self.health.cooldown_until = 0.0
        self.health.status = ProviderHealthState.HEALTHY

    def record_failure(self, error: Exception, cooldown_seconds: float = 300.0) -> None:
        """Record an API failure, update metrics, and trigger circuit breaker cooldown."""
        self.health.failure_count += 1
        self.health.consecutive_failures += 1
        self.health.last_failure = datetime.now(timezone.utc).isoformat()
        self.health.last_error = str(error)

        if cooldown_seconds > 0:
            self.health.cooldown_until = time.time() + cooldown_seconds
            self.health.status = ProviderHealthState.COOLDOWN
        else:
            self.health.status = ProviderHealthState.DEGRADED

    def reset_cooldown(self) -> None:
        """Reset the circuit breaker cooldown back to Healthy across provider and key pool."""
        self.health.cooldown_until = 0.0
        self.health.consecutive_failures = 0
        self.key_pool.reset_all_cooldowns()
        if self.is_enabled:
            self.health.status = ProviderHealthState.HEALTHY
        else:
            self.health.status = ProviderHealthState.DISABLED

    def check_readiness(self) -> None:
        """Verify the provider is configured and not in cooldown."""
        if not self.is_enabled:
            raise ProviderUnavailableError(f"Provider '{self.name}' is disabled (missing API key).", provider=self.name)
        if self.is_in_cooldown():
            rem = round(self.cooldown_seconds_remaining(), 1)
            raise CircuitBreakerOpenError(
                f"Provider '{self.name}' is in cooldown ({rem}s remaining).",
                provider=self.name,
            )

    @staticmethod
    def _encode_image_b64(image_bytes_or_b64: bytes | str) -> str:
        """Helper to ensure image data is base64 string."""
        if isinstance(image_bytes_or_b64, bytes):
            return base64.b64encode(image_bytes_or_b64).decode("utf-8")
        return image_bytes_or_b64

    # --- Abstract methods to be implemented by each provider ---

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Generate a single text response for a user prompt."""
        raise NotImplementedError

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        json_mode: bool = False,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str | None, list[Any] | None]:
        """
        Multi-turn chat completion with optional MCP tool calling and JSON mode.
        Returns: (text_content, tool_calls_list)
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def vision(
        self,
        prompt: str,
        image_bytes_or_b64: bytes | str,
        *,
        max_tokens: int = 1024,
        model: str | None = None,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> str:
        """Analyze an image with prompt instructions."""
        raise NotImplementedError

    async def embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """
        Optional embedding generation.
        Default implementation returns lightweight deterministic pseudo-embedding.
        """
        # Fallback sub-word hashing projection if provider embedding endpoint is unused
        from modules.semantic_memory.vector_store import DenseEmbeddingProvider
        return DenseEmbeddingProvider(dimension=128).embed_text(text)

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Lightweight live health verification ping to provider endpoint."""
        raise NotImplementedError
