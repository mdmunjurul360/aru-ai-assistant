"""Tests for Multi-Provider LLM Failover, Retries, and Circuit Breaker."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from modules.ai import AruAI
from modules.llm.base_provider import BaseLLMProvider, ProviderHealthState
from modules.llm.exceptions import (
    AllProvidersFailedError,
    CircuitBreakerOpenError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.gemini_provider import GeminiProvider
from modules.llm.groq_provider import GroqProvider
from modules.llm.openai_provider import OpenAIProvider
from modules.llm.deepseek_provider import DeepSeekProvider
from modules.llm.provider_manager import ProviderManager


class DummyProvider(BaseLLMProvider):
    """Controllable test provider for verifying failover behavior."""

    def __init__(
        self,
        name: str,
        api_key: str = "test-key",
        default_model: str = "mock-model",
        fail_times: int = 0,
        fail_exception: Exception | None = None,
        success_response: str = "mock response",
    ) -> None:
        super().__init__(name=name, api_key=api_key, default_model=default_model)
        self.fail_times = fail_times
        self.fail_exception = fail_exception or RuntimeError(f"{name} failure")
        self.success_response = success_response
        self.call_count = 0

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
        self.check_readiness()
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise self.fail_exception
        return f"[{self.name}] {self.success_response}"

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
        self.check_readiness()
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise self.fail_exception
        tool_calls = [{"id": "call_1", "function": {"name": "test_tool"}}] if tools else None
        return f"[{self.name}] chat response", tool_calls

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
        self.check_readiness()
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise self.fail_exception
        return f"[{self.name}] vision response"

    async def health_check(self) -> bool:
        return self.is_enabled and not self.is_in_cooldown()


@pytest.mark.asyncio
async def test_normal_request():
    """First provider in priority order succeeds on the first attempt."""
    gemini = DummyProvider("gemini", success_response="Hello Boss")
    openai = DummyProvider("openai")
    groq = DummyProvider("groq")
    deepseek = DummyProvider("deepseek")

    manager = ProviderManager(
        priority=["gemini", "openai", "groq", "deepseek"],
        providers={"gemini": gemini, "openai": openai, "groq": groq, "deepseek": deepseek},
        auto_load=False,
    )

    result = await manager.generate("Hi")
    assert result == "[gemini] Hello Boss"
    assert gemini.call_count == 1
    assert openai.call_count == 0
    assert gemini.health.status == ProviderHealthState.HEALTHY
    assert gemini.health.success_count == 1


@pytest.mark.asyncio
async def test_gemini_timeout_failover():
    """Gemini times out and the manager automatically fails over to OpenAI."""
    gemini = DummyProvider("gemini", fail_times=99, fail_exception=ProviderTimeoutError("Gemini timed out", provider="gemini"))
    openai = DummyProvider("openai", success_response="OpenAI response")

    manager = ProviderManager(
        priority=["gemini", "openai"],
        retry=2,
        providers={"gemini": gemini, "openai": openai},
        auto_load=False,
    )

    result = await manager.generate("Summarize roadmap")
    assert result == "[openai] OpenAI response"
    assert gemini.call_count == 2  # 2 attempts
    assert openai.call_count == 1
    assert gemini.health.status == ProviderHealthState.COOLDOWN
    assert openai.health.status == ProviderHealthState.HEALTHY


@pytest.mark.asyncio
async def test_openai_retry_success():
    """Provider fails on attempt 1 with rate limit, succeeds on attempt 2 retry."""
    openai = DummyProvider(
        "openai",
        fail_times=1,
        fail_exception=ProviderRateLimitError("Rate limited (429)", provider="openai", status_code=429),
        success_response="Recovered on retry",
    )

    manager = ProviderManager(
        priority=["openai"],
        retry=2,
        providers={"openai": openai},
        auto_load=False,
    )

    result = await manager.generate("Test prompt")
    assert result == "[openai] Recovered on retry"
    assert openai.call_count == 2
    assert openai.health.status == ProviderHealthState.HEALTHY
    assert openai.health.success_count == 1


@pytest.mark.asyncio
async def test_groq_success_after_gemini_and_openai_failure():
    """Gemini and OpenAI fail completely, Groq succeeds."""
    gemini = DummyProvider("gemini", fail_times=99)
    openai = DummyProvider("openai", fail_times=99)
    groq = DummyProvider("groq", success_response="Groq lightning response")
    deepseek = DummyProvider("deepseek")

    manager = ProviderManager(
        priority=["gemini", "openai", "groq", "deepseek"],
        retry=1,
        providers={"gemini": gemini, "openai": openai, "groq": groq, "deepseek": deepseek},
        auto_load=False,
    )

    result = await manager.generate("Generate quick reply")
    assert result == "[groq] Groq lightning response"
    assert gemini.call_count == 1
    assert openai.call_count == 1
    assert groq.call_count == 1
    assert deepseek.call_count == 0


@pytest.mark.asyncio
async def test_deepseek_fallback_chain():
    """Gemini -> OpenAI -> Groq fail, DeepSeek succeeds as the final fallback."""
    gemini = DummyProvider("gemini", fail_times=99)
    openai = DummyProvider("openai", fail_times=99)
    groq = DummyProvider("groq", fail_times=99)
    deepseek = DummyProvider("deepseek", success_response="DeepSeek deep thought")

    manager = ProviderManager(
        priority=["gemini", "openai", "groq", "deepseek"],
        retry=1,
        providers={"gemini": gemini, "openai": openai, "groq": groq, "deepseek": deepseek},
        auto_load=False,
    )

    result = await manager.generate("Solve logic puzzle")
    assert result == "[deepseek] DeepSeek deep thought"
    assert deepseek.call_count == 1


@pytest.mark.asyncio
async def test_full_failover_chain_gemini_groq_deepseek_openai():
    """
    Test the exact required production priority chain:
    1. Gemini
    2. Groq
    3. DeepSeek
    4. OpenAI (last fallback)
    """
    gemini = DummyProvider("gemini", fail_times=99)
    groq = DummyProvider("groq", fail_times=99)
    deepseek = DummyProvider("deepseek", fail_times=99)
    openai = DummyProvider("openai", success_response="OpenAI final fallback response")

    manager = ProviderManager(
        retry=1,
        providers={"gemini": gemini, "groq": groq, "deepseek": deepseek, "openai": openai},
        auto_load=False,
    )

    # Manager should default to [gemini, groq, deepseek, openai]
    assert manager.priority == ["gemini", "groq", "deepseek", "openai"]

    result = await manager.generate("Test prompt for failover")
    assert result == "[openai] OpenAI final fallback response"
    assert gemini.call_count == 1
    assert groq.call_count == 1
    assert deepseek.call_count == 1
    assert openai.call_count == 1


@pytest.mark.asyncio
async def test_all_providers_failed_and_graceful_error():
    """When all providers fail, generate() raises AllProvidersFailedError and generate_safe() returns fallback."""
    p1 = DummyProvider("gemini", fail_times=99)
    p2 = DummyProvider("openai", fail_times=99)

    manager = ProviderManager(
        priority=["gemini", "openai"],
        retry=1,
        providers={"gemini": p1, "openai": p2},
        auto_load=False,
    )

    with pytest.raises(AllProvidersFailedError):
        await manager.generate("Test prompt")

    safe_reply = await manager.generate_safe("Test prompt")
    assert "দুঃখিত বস" in safe_reply


@pytest.mark.asyncio
async def test_no_providers_configured():
    """When no providers have API keys, ProviderUnavailableError is raised."""
    p1 = DummyProvider("gemini", api_key="")  # disabled
    manager = ProviderManager(
        priority=["gemini"],
        providers={"gemini": p1},
        auto_load=False,
    )

    with pytest.raises(ProviderUnavailableError):
        await manager.generate("Hello")


@pytest.mark.asyncio
async def test_circuit_breaker_and_cooldown():
    """After a provider exhausts retries, it enters cooldown and is skipped."""
    gemini = DummyProvider("gemini", fail_times=99)
    openai = DummyProvider("openai", success_response="OpenAI safe")

    manager = ProviderManager(
        priority=["gemini", "openai"],
        retry=1,
        cooldown_seconds=60.0,
        providers={"gemini": gemini, "openai": openai},
        auto_load=False,
    )

    # First call: gemini fails and enters cooldown, openai succeeds
    res1 = await manager.generate("First call")
    assert res1 == "[openai] OpenAI safe"
    assert gemini.health.status == ProviderHealthState.COOLDOWN
    assert gemini.is_in_cooldown()

    # Second call: gemini is in cooldown and skipped immediately without calling generate
    gemini_calls_before = gemini.call_count
    res2 = await manager.generate("Second call")
    assert res2 == "[openai] OpenAI safe"
    assert gemini.call_count == gemini_calls_before  # Gemini was skipped!


@pytest.mark.asyncio
async def test_automatic_recovery_after_cooldown():
    """Once cooldown expires, manager probes the provider and restores Healthy status on success."""
    gemini = DummyProvider("gemini", fail_times=1, success_response="Recovered Gemini")
    manager = ProviderManager(
        priority=["gemini"],
        retry=1,
        cooldown_seconds=0.05,  # 50ms cooldown
        providers={"gemini": gemini},
        auto_load=False,
    )

    # Fail once and enter cooldown
    with pytest.raises(AllProvidersFailedError):
        await manager.generate("Fail call")
    assert gemini.health.status == ProviderHealthState.COOLDOWN

    # Wait for cooldown expiration
    await asyncio.sleep(0.06)

    # Call again: cooldown expired, probe succeeds and resets to Healthy
    res = await manager.generate("Probe call")
    assert res == "[gemini] Recovered Gemini"
    assert gemini.health.status == ProviderHealthState.HEALTHY


def test_priority_switching():
    """Priority order can be changed at runtime."""
    manager = ProviderManager(
        priority=["gemini", "openai", "groq", "deepseek"],
        providers={
            "gemini": DummyProvider("gemini"),
            "openai": DummyProvider("openai"),
            "groq": DummyProvider("groq"),
            "deepseek": DummyProvider("deepseek"),
        },
        auto_load=False,
    )

    assert manager.priority == ["gemini", "openai", "groq", "deepseek"]
    manager.switch_priority(["deepseek", "groq", "openai", "gemini"])
    assert manager.priority == ["deepseek", "groq", "openai", "gemini"]


def test_environment_loading(monkeypatch):
    """ProviderManager correctly detects enabled and disabled providers from environment."""
    monkeypatch.setenv("GEMINI_API_KEY", "gem-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEYS", raising=False)

    manager = ProviderManager(auto_load=True)
    enabled = manager.get_enabled_providers()

    assert "gemini" in enabled
    assert ("openrouter" in enabled or "openai" in enabled)
    assert "groq" in enabled
    assert "deepseek" not in enabled


def test_status_summary_formatting():
    """format_status_summary outputs clean status lines for /status."""
    gemini = DummyProvider("gemini")
    openrouter = DummyProvider("openrouter")
    groq = DummyProvider("groq")
    deepseek = DummyProvider("deepseek")

    manager = ProviderManager(
        priority=["gemini", "openrouter", "groq", "deepseek"],
        providers={"gemini": gemini, "openrouter": openrouter, "groq": groq, "deepseek": deepseek},
        auto_load=False,
    )

    deepseek.health.status = ProviderHealthState.COOLDOWN

    summary = manager.format_status_summary()
    assert "Gemini: Healthy" in summary
    assert "OpenRouter: Healthy" in summary
    assert "Groq: Healthy" in summary
    assert "DeepSeek: Cooldown" in summary


@pytest.mark.asyncio
async def test_chat_and_tools_failover():
    """chat completion with MCP tools fails over automatically."""
    gemini = DummyProvider("gemini", fail_times=99)
    openai = DummyProvider("openai", success_response="tool answer")

    manager = ProviderManager(
        priority=["gemini", "openai"],
        retry=1,
        providers={"gemini": gemini, "openai": openai},
        auto_load=False,
    )

    messages = [{"role": "user", "content": "Fetch data"}]
    tools = [{"type": "function", "function": {"name": "fetch"}}]

    content, tool_calls = await manager.chat(messages, tools=tools)
    assert content == "[openai] chat response"
    assert tool_calls is not None
    assert tool_calls[0]["function"]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_vision_failover():
    """vision analysis fails over across providers."""
    gemini = DummyProvider("gemini", fail_times=99)
    groq = DummyProvider("groq", success_response="Recognized screenshot")

    manager = ProviderManager(
        priority=["gemini", "groq"],
        retry=1,
        providers={"gemini": gemini, "groq": groq},
        auto_load=False,
    )

    result = await manager.vision("Analyze UI", b"fake_png_data")
    assert result == "[groq] vision response"


@pytest.mark.asyncio
async def test_aru_ai_integration_with_provider_manager():
    """AruAI facade seamlessly delegates to ProviderManager."""
    mock_prov = DummyProvider("gemini", success_response="Integrated AI reply")
    mgr = ProviderManager(
        priority=["gemini"],
        providers={"gemini": mock_prov},
        auto_load=False,
    )

    ai = AruAI(provider_manager=mgr)
    assert ai.is_connected

    reply = await ai.generate("Hello Aru")
    assert reply == "[gemini] Integrated AI reply"
    assert mock_prov.call_count == 1


def test_individual_providers_api_key_checks():
    """Verify that every concrete provider validates its own API key correctly."""
    # 1. Gemini
    gem_disabled = GeminiProvider(api_key="")
    assert not gem_disabled.is_enabled
    assert gem_disabled.health.status == ProviderHealthState.DISABLED
    with pytest.raises(ProviderUnavailableError) as exc_gem:
        gem_disabled.check_readiness()
    assert "missing API key" in str(exc_gem.value)

    gem_enabled = GeminiProvider(api_key="valid-gemini-key")
    assert gem_enabled.is_enabled
    assert gem_enabled.health.status == ProviderHealthState.HEALTHY
    gem_enabled.check_readiness()  # Should not raise

    # 2. OpenAI
    oa_disabled = OpenAIProvider(api_key="")
    assert not oa_disabled.is_enabled
    assert oa_disabled.health.status == ProviderHealthState.DISABLED
    with pytest.raises(ProviderUnavailableError) as exc_oa:
        oa_disabled.check_readiness()
    assert "missing API key" in str(exc_oa.value)

    oa_enabled = OpenAIProvider(api_key="sk-valid-openai-key")
    assert oa_enabled.is_enabled
    assert oa_enabled.health.status == ProviderHealthState.HEALTHY
    oa_enabled.check_readiness()

    # 3. Groq
    groq_disabled = GroqProvider(api_key="")
    assert not groq_disabled.is_enabled
    assert groq_disabled.health.status == ProviderHealthState.DISABLED
    with pytest.raises(ProviderUnavailableError) as exc_groq:
        groq_disabled.check_readiness()
    assert "missing API key" in str(exc_groq.value)

    groq_enabled = GroqProvider(api_key="gsk-valid-groq-key")
    assert groq_enabled.is_enabled
    assert groq_enabled.health.status == ProviderHealthState.HEALTHY
    groq_enabled.check_readiness()

    # 4. DeepSeek
    ds_disabled = DeepSeekProvider(api_key="")
    assert not ds_disabled.is_enabled
    assert ds_disabled.health.status == ProviderHealthState.DISABLED
    with pytest.raises(ProviderUnavailableError) as exc_ds:
        ds_disabled.check_readiness()
    assert "missing API key" in str(exc_ds.value)

    ds_enabled = DeepSeekProvider(api_key="ds-valid-deepseek-key")
    assert ds_enabled.is_enabled
    assert ds_enabled.default_model == "deepseek-flash"
    assert ds_enabled.health.status == ProviderHealthState.HEALTHY
    ds_enabled.check_readiness()


def test_telegram_and_ai_env_variables_in_config(monkeypatch, tmp_path):
    """Verify that config.py reads both legacy and standard Telegram and LLM environment variables."""
    from modules import config

    for var in ("OPENROUTER_API_KEY", "OPENROUTER_API_KEYS", "OPENAI_API_KEY", "OPENAI_API_KEYS"):
        monkeypatch.delenv(var, raising=False)

    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "TELEGRAM_API_ID=123456\n"
        "TELEGRAM_API_HASH=hash_abc\n"
        "TELEGRAM_BOT_TOKEN=123:token_xyz\n"
        "TELEGRAM_BOT_ID=987654\n"
        "TELEGRAM_SECRET=unlock_secret\n"
        "GEMINI_API_KEY=gem_key_1\n"
        "OPENAI_API_KEY=oa_key_2\n"
        "DEEPSEEK_API_KEY=ds_key_3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ENV_PATH", fake_env)
    config.reload_settings()

    assert config.TELEGRAM_API_ID == 123456
    assert config.TG_API_ID == 123456
    assert config.TELEGRAM_API_HASH == "hash_abc"
    assert config.TG_API_HASH == "hash_abc"
    assert config.TELEGRAM_BOT_TOKEN == "123:token_xyz"
    assert config.TELEGRAM_BOT_ID == 987654
    assert config.BOSS_TELEGRAM_ID == 987654
    assert config.TELEGRAM_SECRET == "unlock_secret"
    assert config.SECRET_CODE == "unlock_secret"
    assert config.GEMINI_API_KEY == "gem_key_1"
    assert config.OPENAI_API_KEY == "oa_key_2"
    assert config.OPENROUTER_API_KEY == "oa_key_2"
    assert config.DEEPSEEK_API_KEY == "ds_key_3"

    # Reload from actual environment to restore state
    monkeypatch.undo()
    config.reload_settings()
