"""Comprehensive tests for Multi-API-Key Pooling, Failover, Circuit Breaking, and Concurrency."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from modules.config import parse_api_keys
from modules.llm.base_provider import BaseLLMProvider, ProviderHealthState
from modules.llm.exceptions import (
    AllProvidersFailedError,
    CircuitBreakerOpenError,
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderPoolExhaustedError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from modules.llm.gemini_provider import GeminiProvider
from modules.llm.groq_provider import GroqProvider
from modules.llm.key_pool import APIKeySlot, KeyHealthStatus, KeyPool, mask_key
from modules.llm.openai_provider import OpenAIProvider
from modules.llm.provider_manager import ProviderManager


# ==============================================================================
# 1. Configuration Parsing & Delimiter Handling Tests
# ==============================================================================

def test_parse_api_keys_comma_separated():
    result = parse_api_keys("key1, key2, key3")
    assert result == ["key1", "key2", "key3"]


def test_parse_api_keys_semicolon_separated():
    result = parse_api_keys("keyA; keyB; keyC")
    assert result == ["keyA", "keyB", "keyC"]


def test_parse_api_keys_newline_separated():
    raw = "keyAlpha\nkeyBeta\r\nkeyGamma"
    result = parse_api_keys(raw)
    assert result == ["keyAlpha", "keyBeta", "keyGamma"]


def test_parse_api_keys_whitespace_quotes_and_empty_values():
    raw = " 'key1' , \"key2\" ; ; \n\n key3 , , 'key4' "
    result = parse_api_keys(raw)
    assert result == ["key1", "key2", "key3", "key4"]


def test_parse_api_keys_merging_singular_and_plural_with_deduplication():
    singular = "primary_key"
    plural = "second_key, primary_key, third_key"
    result = parse_api_keys(plural, singular)
    # Singular comes first if provided, duplicates removed, order preserved
    assert result == ["primary_key", "second_key", "third_key"]


def test_parse_api_keys_singular_only():
    result = parse_api_keys(None, "only_key")
    assert result == ["only_key"]


def test_parse_api_keys_none_or_empty():
    assert parse_api_keys(None, None) == []
    assert parse_api_keys("", "  ") == []


# ==============================================================================
# 2. Key Masking & Confidentiality Tests
# ==============================================================================

def test_key_masking_standard_keys():
    masked = mask_key("AIzaSyD-1234567890abcdef8kQ")
    assert masked.startswith("AIza")
    assert masked.endswith("8kQ")
    assert "..." in masked
    assert "1234567890abcdef" not in masked


def test_key_masking_short_or_empty_keys():
    assert mask_key("short") == "***"
    assert mask_key("") == "<none>"
    assert mask_key(None) == "<none>"


# ==============================================================================
# 3. Key Slot Health & Metrics Tracking
# ==============================================================================

def test_key_slot_initial_state():
    slot = APIKeySlot(api_key="secret-api-key-12345", index=1, provider_name="gemini")
    assert slot.status == KeyHealthStatus.HEALTHY
    assert slot.is_available
    assert slot.request_count == 0
    assert slot.success_count == 0
    assert slot.failure_count == 0
    assert slot.average_latency == 0.0
    assert slot.display_name == "Gemini Key #1"
    assert "secret-api-key-12345" not in repr(slot)


def test_key_slot_record_success():
    slot = APIKeySlot(api_key="test-key-1", index=1, provider_name="groq")
    slot.record_success(0.5)
    slot.record_success(0.3)
    assert slot.request_count == 2
    assert slot.success_count == 2
    assert slot.failure_count == 0
    assert round(slot.average_latency, 2) == 0.40
    assert slot.status == KeyHealthStatus.HEALTHY
    assert slot.consecutive_failures == 0


def test_key_slot_circuit_breaker_classification():
    # 429 -> short cooldown
    slot_429 = APIKeySlot(api_key="test-key-429", index=1, provider_name="gemini")
    slot_429.record_failure(RuntimeError("HTTP 429 Too Many Requests"))
    assert slot_429.status == KeyHealthStatus.COOLDOWN
    assert not slot_429.is_available
    assert slot_429.cooldown_remaining > 0

    # Quota exhausted -> long cooldown (1800s)
    slot_quota = APIKeySlot(api_key="test-key-quota", index=2, provider_name="gemini")
    slot_quota.record_failure(RuntimeError("Resource has been exhausted: quota limit"))
    assert slot_quota.status == KeyHealthStatus.COOLDOWN
    assert slot_quota.cooldown_remaining > 500  # Default 1800s

    # 401/403 -> disabled
    slot_auth = APIKeySlot(api_key="test-key-auth", index=3, provider_name="openai")
    slot_auth.record_failure(ProviderAuthenticationError("401 Unauthorized"))
    assert slot_auth.status == KeyHealthStatus.DISABLED
    assert not slot_auth.is_available


# ==============================================================================
# 4. Intra-Provider Key Pool Rotation & Failover
# ==============================================================================

@pytest.mark.asyncio
async def test_key_pool_rotates_on_failure():
    """Key #1 fails with 429 -> automatically switches to Key #2."""
    pool = KeyPool(provider_name="gemini", keys=["key-1", "key-2", "key-3"])
    assert pool.total_keys == 3

    attempted_keys = []

    async def mock_call(slot: APIKeySlot) -> str:
        attempted_keys.append(slot.api_key)
        if slot.api_key == "key-1":
            raise RuntimeError("429 Rate limit exceeded")
        return f"success with {slot.api_key}"

    result = await pool.execute_with_key_failover("test_op", mock_call)
    assert result == "success with key-2"
    assert attempted_keys == ["key-1", "key-2"]

    # Slot 1 in cooldown, Slot 2 healthy
    assert pool.slots[0].status == KeyHealthStatus.COOLDOWN
    assert pool.slots[1].status == KeyHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_key_pool_exhaustion_raises_provider_pool_exhausted_error():
    """When all keys in pool fail, raises ProviderPoolExhaustedError."""
    pool = KeyPool(provider_name="groq", keys=["key-A", "key-B"])

    async def failing_call(slot: APIKeySlot) -> str:
        raise ProviderRateLimitError("429 Too many requests", provider="groq")

    with pytest.raises(ProviderPoolExhaustedError) as exc_info:
        await pool.execute_with_key_failover("test_op", failing_call)

    assert "All 2 API keys for provider 'groq' are currently exhausted" in str(exc_info.value)
    assert pool.slots[0].status == KeyHealthStatus.COOLDOWN
    assert pool.slots[1].status == KeyHealthStatus.COOLDOWN


@pytest.mark.asyncio
async def test_non_retryable_request_error_does_not_cycle_keys():
    """Client request errors (400, context length, content block) fail immediately."""
    pool = KeyPool(provider_name="openai", keys=["key-1", "key-2", "key-3"])

    calls = 0

    async def invalid_request_call(slot: APIKeySlot) -> str:
        nonlocal calls
        calls += 1
        raise ValueError("Invalid argument: maximum context length is 4096 tokens")

    with pytest.raises(ValueError) as exc_info:
        await pool.execute_with_key_failover("test_op", invalid_request_call)

    assert "maximum context length" in str(exc_info.value)
    # Must NOT rotate to key-2 or key-3
    assert calls == 1
    # Keys should NOT be penalized into cooldown for user payload errors
    assert pool.slots[0].status == KeyHealthStatus.HEALTHY


# ==============================================================================
# 5. Half-Open Probing & Cooldown Recovery
# ==============================================================================

@pytest.mark.asyncio
async def test_half_open_probe_recovers_key_to_healthy():
    """A cooling key whose timer expires enters PROBING and recovers on success."""
    pool = KeyPool(provider_name="gemini", keys=["key-1"])
    slot = pool.slots[0]

    # Force slot into cooldown with expired timer
    slot.status = KeyHealthStatus.COOLDOWN
    slot.cooldown_until = time.time() - 1.0

    async def probe_call(s: APIKeySlot) -> str:
        assert s.status == KeyHealthStatus.PROBING
        return "probe_success"

    res = await pool.execute_with_key_failover("probe_op", probe_call)
    assert res == "probe_success"
    assert slot.status == KeyHealthStatus.HEALTHY
    assert slot.is_probing is False


@pytest.mark.asyncio
async def test_half_open_probe_single_flight_gatekeeper():
    """When a key is probing, concurrent callers must skip it."""
    pool = KeyPool(provider_name="gemini", keys=["key-probe", "key-fallback"])
    slot1 = pool.slots[0]
    slot2 = pool.slots[1]

    # slot1 cooldown expired
    slot1.status = KeyHealthStatus.COOLDOWN
    slot1.cooldown_until = time.time() - 1.0

    # Acquire slot1 for probing manually
    selected1 = await pool.select_slot()
    assert selected1 is slot1
    assert slot1.is_probing is True
    assert slot1.status == KeyHealthStatus.PROBING

    # Second caller tries to get a slot while slot1 is probing
    selected2 = await pool.select_slot()
    # Must skip slot1 and select slot2
    assert selected2 is slot2

    # Clean up
    await pool.release_slot(slot1, success=True, latency_sec=0.1)
    await pool.release_slot(slot2, success=True, latency_sec=0.1)


# ==============================================================================
# 6. Concurrency & Race Condition Safety
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_requests_pool_safety():
    """Multiple concurrent coroutines safely utilize keys without collision."""
    pool = KeyPool(provider_name="groq", keys=["key-conc-1", "key-conc-2", "key-conc-3"])

    async def worker(worker_id: int) -> str:
        async def _call(slot: APIKeySlot) -> str:
            await asyncio.sleep(0.01)
            return f"worker-{worker_id}-using-{slot.display_name}"

        return await pool.execute_with_key_failover(f"worker_{worker_id}", _call)

    # Launch 20 concurrent requests
    results = await asyncio.gather(*(worker(i) for i in range(20)))

    assert len(results) == 20
    assert all("worker-" in r for r in results)
    # Total successful requests across all slots equals 20
    total_success = sum(s.success_count for s in pool.slots)
    assert total_success == 20


# ==============================================================================
# 7. End-to-End Hierarchical Failover (Intra-Key -> Inter-Provider)
# ==============================================================================

class MockMultiKeyProvider(BaseLLMProvider):
    def __init__(
        self,
        name: str,
        api_keys: list[str],
        fail_keys: dict[str, Exception] | None = None,
        success_response: str = "ok",
    ) -> None:
        super().__init__(name=name, api_keys=api_keys)
        self.fail_keys = fail_keys or {}
        self.success_response = success_response

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        self.check_readiness()

        async def _run(slot: APIKeySlot) -> str:
            if slot.api_key in self.fail_keys:
                raise self.fail_keys[slot.api_key]
            return f"[{self.name}][{slot.display_name}] {self.success_response}"

        return await self.key_pool.execute_with_key_failover("generate", _run)

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> tuple[str | None, list[Any] | None]:
        res = await self.generate("chat", **kwargs)
        return res, None

    async def vision(self, prompt: str, image_bytes_or_b64: bytes | str, **kwargs: Any) -> str:
        return await self.generate(prompt, **kwargs)

    async def health_check(self) -> bool:
        return self.is_enabled and not self.is_in_cooldown()


@pytest.mark.asyncio
async def test_hierarchical_failover_gemini_keys_exhaust_then_groq_succeeds():
    """
    Gemini has 2 keys: Key #1 fails (429), Key #2 fails (quota).
    Gemini pool exhausted -> ProviderManager immediately fails over to Groq.
    Groq Key #1 succeeds.
    """
    gemini = MockMultiKeyProvider(
        name="gemini",
        api_keys=["gem-k1", "gem-k2"],
        fail_keys={
            "gem-k1": ProviderRateLimitError("429 rate limit", provider="gemini"),
            "gem-k2": ProviderRateLimitError("Quota limit reached", provider="gemini"),
        },
    )

    groq = MockMultiKeyProvider(
        name="groq",
        api_keys=["groq-k1"],
        success_response="Groq came to the rescue",
    )

    manager = ProviderManager(
        priority=["gemini", "groq", "deepseek", "openai"],
        providers={"gemini": gemini, "groq": groq},
        auto_load=False,
        retry=1,
    )

    result = await manager.generate("Hello world")
    assert "[groq]" in result
    assert "Groq came to the rescue" in result

    # Check key statuses
    assert gemini.key_pool.slots[0].status == KeyHealthStatus.COOLDOWN
    assert gemini.key_pool.slots[1].status == KeyHealthStatus.COOLDOWN
    assert groq.key_pool.slots[0].status == KeyHealthStatus.HEALTHY
    assert groq.key_pool.slots[0].success_count == 1


# ==============================================================================
# 8. Backward Compatibility: Single Key String Support
# ==============================================================================

def test_concrete_providers_backward_compatible_with_singular_key():
    gem = GeminiProvider(api_key="single-gemini-key")
    assert gem.is_enabled
    assert gem.key_pool.total_keys == 1
    assert gem.api_key == "single-gemini-key"

    groq = GroqProvider(api_key="single-groq-key")
    assert groq.is_enabled
    assert groq.key_pool.total_keys == 1

    oa = OpenAIProvider(api_key="single-oa-key")
    assert oa.is_enabled
    assert oa.key_pool.total_keys == 1


def test_empty_or_none_api_key_initializes_cleanly_as_disabled():
    gem = GeminiProvider(api_key=None)
    assert not gem.is_enabled
    assert gem.key_pool.total_keys == 0
    with pytest.raises(ProviderUnavailableError):
        gem.check_readiness()
