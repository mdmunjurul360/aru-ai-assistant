"""Tests for dynamic startup banner generation, provider-driven health checks, and Groq skipping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from main import build_startup_banner
from modules.ai import AruAI
from modules.llm.base_provider import BaseLLMProvider
from modules.llm.provider_manager import ProviderManager


def test_build_startup_banner_without_groq():
    """When Groq is absent, banner must display only enabled/healthy providers."""
    banner = build_startup_banner(
        telegram_connected=True,
        connected_providers=["Gemini", "Cloudflare", "OpenAI", "DeepSeek"],
        memory_active=True,
        voice_ready=False,
        research_ready=True,
        boss_verified=True,
    )

    assert "ARU AI v2 ONLINE" in banner
    assert "Telegram Connected" in banner
    assert "Gemini Connected" in banner
    assert "Cloudflare Connected" in banner
    assert "OpenAI Connected" in banner
    assert "DeepSeek Connected" in banner
    assert "Groq Connected" not in banner
    assert "Voice Assistant Ready" not in banner
    assert "Memory System Active" in banner


def test_build_startup_banner_with_groq():
    """When Groq is enabled and healthy, Groq Connected is included."""
    banner = build_startup_banner(
        telegram_connected=True,
        connected_providers=["Groq", "Gemini"],
        voice_ready=True,
    )

    assert "Groq Connected" in banner
    assert "Gemini Connected" in banner
    assert "Voice Assistant Ready" in banner


def test_build_startup_banner_unhealthy_provider_omitted():
    """Providers that failed health checks must not appear as Connected."""
    # Suppose Gemini passed but Cloudflare failed
    banner = build_startup_banner(
        telegram_connected=True,
        connected_providers=["Gemini"],
    )

    assert "Gemini Connected" in banner
    assert "Cloudflare Connected" not in banner
    assert "Groq Connected" not in banner


@pytest.mark.asyncio
async def test_health_check_all_skips_disabled_groq():
    """ProviderManager.health_check_all must skip any disabled provider without calling health_check."""
    class DummyProvider(BaseLLMProvider):
        def __init__(self, name: str, is_en: bool):
            self._force_enabled = is_en
            self.health_check_called = False
            super().__init__(name=name, api_key="test_key" if is_en else "")

        @property
        def is_enabled(self) -> bool:
            return self._force_enabled

        async def health_check(self) -> bool:
            self.health_check_called = True
            return True

        async def generate(self, *args, **kwargs) -> str:
            return "OK"

        async def chat(self, *args, **kwargs):
            return "OK", None

        async def vision(self, *args, **kwargs) -> str:
            return "OK"

    groq_mock = DummyProvider("groq", is_en=False)
    gemini_mock = DummyProvider("gemini", is_en=True)

    pm = ProviderManager(
        providers={"groq": groq_mock, "gemini": gemini_mock},
        auto_load=False,
    )

    results = await pm.health_check_all()

    assert results["groq"] is False
    assert results["gemini"] is True
    # Groq's health check method was never called
    assert groq_mock.health_check_called is False
    assert gemini_mock.health_check_called is True


@pytest.mark.asyncio
async def test_aru_ai_active_model_and_health_check_reflects_active_provider():
    """AruAI.active_model and health_check log dynamic active provider, not hardcoded Groq."""
    class DummyGemini(BaseLLMProvider):
        def __init__(self):
            super().__init__(name="gemini", api_key="test_gemini", default_model="gemini-2.5-flash")

        @property
        def is_enabled(self) -> bool:
            return True

        async def generate(self, *args, **kwargs) -> str:
            return "OK"

        async def chat(self, *args, **kwargs):
            return "OK", None

        async def vision(self, *args, **kwargs) -> str:
            return "OK"

        async def health_check(self) -> bool:
            return True

    pm = ProviderManager(
        priority=["gemini"],
        providers={"gemini": DummyGemini()},
        auto_load=False,
    )

    ai = AruAI(provider_manager=pm)
    assert ai.active_provider == "gemini"
    assert ai.active_model == "gemini-2.5-flash"

    # Running health check
    ok = await ai.health_check()
    assert ok is True
