"""Tests for OpenRouter provider with KeyPool, model fallback, vision, and provider failover."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from modules.llm.base_provider import BaseLLMProvider, ProviderHealthState
from modules.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.openrouter_provider import (
    OPENROUTER_BASE_URL,
    OPENROUTER_CHAT_URL,
    OPENROUTER_DEFAULT_MODEL,
    OpenRouterProvider,
    OpenAIProvider,
)
from modules.llm.provider_manager import ProviderManager


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", OPENROUTER_CHAT_URL)
    return httpx.Response(
        status_code=status_code,
        json=json_data if json_data is not None else {"choices": [{"message": {"content": "ok"}}]},
        text=text or (json.dumps(json_data) if json_data else "ok"),
        request=request,
    )


def test_openrouter_initialization_and_backward_compatibility():
    """Verify single/multiple key init and backward-compatible OpenAIProvider alias."""
    p1 = OpenRouterProvider(api_key="sk-or-v1-test-1")
    assert p1.is_enabled is True
    assert p1.key_pool.total_keys == 1
    assert p1.name == "openrouter"
    assert p1.base_url == OPENROUTER_BASE_URL
    assert p1.chat_url == OPENROUTER_CHAT_URL
    assert p1.default_model == OPENROUTER_DEFAULT_MODEL

    p2 = OpenRouterProvider(api_keys=["sk-or-v1-test-1", "sk-or-v1-test-2"])
    assert p2.is_enabled is True
    assert p2.key_pool.total_keys == 2

    # OpenAIProvider alias
    legacy = OpenAIProvider(api_key="sk-or-v1-legacy")
    assert legacy.name == "openrouter"
    assert legacy.chat_url == OPENROUTER_CHAT_URL


def test_openrouter_headers():
    """Verify OpenRouter headers include Authorization, HTTP-Referer, and X-Title."""
    p = OpenRouterProvider(api_key="sk-or-v1-header-test")
    headers = p._get_headers()
    assert headers["Authorization"] == "Bearer sk-or-v1-header-test"
    assert "HTTP-Referer" in headers
    assert headers["X-Title"] == "Aru AI"


@pytest.mark.asyncio
async def test_openrouter_generate_success():
    """Test standard generate call using mock OpenRouter HTTP response."""
    provider = OpenRouterProvider(api_key="sk-or-v1-test")

    chat_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello from OpenRouter!",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_response(200, json_data=chat_response)

        reply = await provider.generate("Hello")
        assert reply == "Hello from OpenRouter!"
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert mock_post.call_args[0][0] == OPENROUTER_CHAT_URL
        assert "Bearer sk-or-v1-test" in call_kwargs["headers"]["Authorization"]
        assert call_kwargs["json"]["messages"][-1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_openrouter_multiple_keys_failover():
    """When key 1 hits a 429 rate limit, provider automatically fails over to key 2."""
    provider = OpenRouterProvider(api_keys=["sk-or-v1-key1", "sk-or-v1-key2"])

    rate_limit_resp = httpx.Response(
        status_code=429,
        text="OpenRouter Rate limit exceeded",
        request=httpx.Request("POST", OPENROUTER_CHAT_URL),
    )
    success_resp = _mock_response(
        200,
        json_data={"choices": [{"message": {"role": "assistant", "content": "Success on Key 2"}}]},
    )

    async def mock_post(*args, **kwargs):
        auth_header = kwargs["headers"]["Authorization"]
        if "sk-or-v1-key1" in auth_header:
            raise httpx.HTTPStatusError("429", request=rate_limit_resp.request, response=rate_limit_resp)
        return success_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await provider.generate("Test failover across keys")
        assert result == "Success on Key 2"
        assert provider.key_pool.slots[0].is_in_cooldown() is True
        assert provider.key_pool.slots[1].is_in_cooldown() is False


@pytest.mark.asyncio
async def test_openrouter_vision():
    """Test vision analysis via OpenRouter multimodal format."""
    provider = OpenRouterProvider(api_key="sk-or-v1-test")

    vision_resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "A high-resolution image of a diagram.",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_response(200, json_data=vision_resp)

        dummy_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        result = await provider.vision(
            prompt="Analyze this diagram",
            image_bytes_or_b64=dummy_image,
            mime_type="image/png",
        )
        assert "diagram" in result
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert mock_post.call_args[0][0] == OPENROUTER_CHAT_URL


def test_openrouter_error_handling():
    """Test translation of HTTP errors to Aru AI exception hierarchy."""
    provider = OpenRouterProvider(api_key="sk-or-v1-test")

    resp_401 = httpx.Response(
        status_code=401,
        text="Invalid OpenRouter Key",
        request=httpx.Request("POST", OPENROUTER_CHAT_URL),
    )
    with pytest.raises(ProviderAuthenticationError):
        provider._handle_http_error(
            httpx.HTTPStatusError("401", request=resp_401.request, response=resp_401)
        )

    resp_429 = httpx.Response(
        status_code=429,
        text="Credits exhausted or rate limited",
        request=httpx.Request("POST", OPENROUTER_CHAT_URL),
    )
    with pytest.raises(ProviderRateLimitError):
        provider._handle_http_error(
            httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429)
        )


@pytest.mark.asyncio
async def test_provider_manager_default_priority_and_failover_chain():
    """
    Verify complete failover chain in default priority:
    OpenRouter -> Groq -> Gemini -> Cloudflare -> DeepSeek
    """
    class MockFailingProvider(BaseLLMProvider):
        async def generate(self, *args, **kwargs) -> str:
            raise ProviderRateLimitError(f"{self.name} failed", provider=self.name)
        async def chat(self, *args, **kwargs):
            raise NotImplementedError
        async def vision(self, *args, **kwargs) -> str:
            raise NotImplementedError
        async def health_check(self) -> bool:
            return False

    class MockSuccessProvider(BaseLLMProvider):
        async def generate(self, *args, **kwargs) -> str:
            return f"Success from {self.name}"
        async def chat(self, *args, **kwargs):
            raise NotImplementedError
        async def vision(self, *args, **kwargs) -> str:
            raise NotImplementedError
        async def health_check(self) -> bool:
            return True

    # 1. When OpenRouter fails, it falls over to Groq
    pm1 = ProviderManager(auto_load=False)
    pm1.register_provider(MockFailingProvider("openrouter", api_key="k_or"))
    pm1.register_provider(MockSuccessProvider("groq", api_key="k_groq"))
    pm1.switch_priority(["openrouter", "groq", "gemini", "cloudflare", "deepseek"])
    res1 = await pm1.generate("Hello")
    assert res1 == "Success from groq"

    # 2. When OpenRouter and Groq fail, falls over to Gemini
    pm2 = ProviderManager(auto_load=False)
    pm2.register_provider(MockFailingProvider("openrouter", api_key="k_or"))
    pm2.register_provider(MockFailingProvider("groq", api_key="k_groq"))
    pm2.register_provider(MockSuccessProvider("gemini", api_key="k_gemini"))
    pm2.switch_priority(["openrouter", "groq", "gemini", "cloudflare", "deepseek"])
    res2 = await pm2.generate("Hello")
    assert res2 == "Success from gemini"

    # 3. When OpenRouter, Groq, and Gemini fail, falls over to Cloudflare
    pm3 = ProviderManager(auto_load=False)
    pm3.register_provider(MockFailingProvider("openrouter", api_key="k_or"))
    pm3.register_provider(MockFailingProvider("groq", api_key="k_groq"))
    pm3.register_provider(MockFailingProvider("gemini", api_key="k_gemini"))
    pm3.register_provider(MockSuccessProvider("cloudflare", api_key="k_cf"))
    pm3.switch_priority(["openrouter", "groq", "gemini", "cloudflare", "deepseek"])
    res3 = await pm3.generate("Hello")
    assert res3 == "Success from cloudflare"

    # 4. When all four fail, falls over to DeepSeek
    pm4 = ProviderManager(auto_load=False)
    pm4.register_provider(MockFailingProvider("openrouter", api_key="k_or"))
    pm4.register_provider(MockFailingProvider("groq", api_key="k_groq"))
    pm4.register_provider(MockFailingProvider("gemini", api_key="k_gemini"))
    pm4.register_provider(MockFailingProvider("cloudflare", api_key="k_cf"))
    pm4.register_provider(MockSuccessProvider("deepseek", api_key="k_ds"))
    pm4.switch_priority(["openrouter", "groq", "gemini", "cloudflare", "deepseek"])
    res4 = await pm4.generate("Hello")
    assert res4 == "Success from deepseek"
