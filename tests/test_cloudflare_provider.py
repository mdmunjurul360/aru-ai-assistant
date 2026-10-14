"""Tests for Cloudflare Workers AI provider with KeyPool, model fallback, and failover."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from modules.llm.base_provider import ProviderHealthState
from modules.llm.cloudflare_provider import (
    CLOUDFLARE_CHAT_URL_TEMPLATE,
    CLOUDFLARE_MODELS,
    CLOUDFLARE_VISION_MODEL,
    CloudflareProvider,
)
from modules.llm.exceptions import (
    CircuitBreakerOpenError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.provider_manager import ProviderManager


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", "https://api.cloudflare.com/client/v4/accounts/acc123/ai/v1/chat/completions")
    return httpx.Response(
        status_code=status_code,
        json=json_data if json_data is not None else {"choices": [{"message": {"content": "ok"}}]},
        text=text or (json.dumps(json_data) if json_data else "ok"),
        request=request,
    )


def test_cloudflare_provider_initialization():
    """Verify single and multiple key initialization."""
    # Single key
    p1 = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")
    assert p1.is_enabled is True
    assert p1.key_pool.total_keys == 1
    assert p1.account_id == "acc-1"

    # Multiple keys
    p2 = CloudflareProvider(api_keys=["cf-key-1", "cf-key-2"], account_id="acc-2")
    assert p2.is_enabled is True
    assert p2.key_pool.total_keys == 2
    assert p2.account_id == "acc-2"

    # Missing account_id or key disables provider
    p3 = CloudflareProvider(api_key="cf-key-1", account_id="")
    assert p3.is_enabled is False

    p4 = CloudflareProvider(api_key="", account_id="acc-1")
    assert p4.is_enabled is False


@pytest.mark.asyncio
async def test_cloudflare_generate_success():
    """Test standard generate call using mock HTTP response."""
    provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    chat_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello from Cloudflare Workers AI!",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_response(200, json_data=chat_response)

        reply = await provider.generate("Hello")
        assert reply == "Hello from Cloudflare Workers AI!"
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        assert "Bearer cf-key-1" in call_kwargs["headers"]["Authorization"]
        assert call_kwargs["json"]["messages"][-1]["content"] == "Hello"


@pytest.mark.asyncio
async def test_cloudflare_chat_with_tools():
    """Test chat() with tool_calls and json mode."""
    provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    chat_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"location": "Dhaka"}'},
                        }
                    ],
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_response(200, json_data=chat_response)

        messages = [{"role": "user", "content": "What's the weather?"}]
        content, tool_calls = await provider.chat(
            messages=messages,
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )
        assert content is None
        assert tool_calls is not None
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "get_weather"


@pytest.mark.asyncio
async def test_cloudflare_multiple_keys_failover():
    """When key 1 hits a 429 rate limit, provider automatically fails over to key 2."""
    provider = CloudflareProvider(api_keys=["cf-key-1", "cf-key-2"], account_id="acc-1")

    rate_limit_resp = httpx.Response(
        status_code=429,
        text="Rate limit exceeded",
        request=httpx.Request("POST", provider.chat_url),
    )
    success_resp = _mock_response(
        200,
        json_data={"choices": [{"message": {"role": "assistant", "content": "Success on Key 2"}}]},
    )

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        auth_header = kwargs["headers"]["Authorization"]
        if "cf-key-1" in auth_header:
            raise httpx.HTTPStatusError("429", request=rate_limit_resp.request, response=rate_limit_resp)
        return success_resp

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await provider.generate("Test failover across keys")
        assert result == "Success on Key 2"
        # Key 1 is now cooling down
        assert provider.key_pool.slots[0].is_in_cooldown() is True
        assert provider.key_pool.slots[1].is_in_cooldown() is False


@pytest.mark.asyncio
async def test_cloudflare_model_fallback():
    """If default model returns 404, provider falls back to next model in chain."""
    provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    resp_404 = httpx.Response(
        status_code=404,
        text="Model not found",
        request=httpx.Request("POST", provider.chat_url),
    )
    resp_success = _mock_response(
        200,
        json_data={"choices": [{"message": {"role": "assistant", "content": "Fallback model response"}}]},
    )

    calls: list[str] = []

    async def mock_post(*args, **kwargs):
        model_sent = kwargs["json"]["model"]
        calls.append(model_sent)
        if len(calls) == 1:
            return resp_404
        return resp_success

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await provider.generate("Hello")
        assert result == "Fallback model response"
        assert len(calls) >= 2


@pytest.mark.asyncio
async def test_cloudflare_vision():
    """Test vision analysis via multimodal endpoint."""
    provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    vision_resp = {
        "result": {
            "response": "A financial chart showing 25% revenue growth in Q3.",
        }
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _mock_response(200, json_data=vision_resp)

        dummy_image = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        result = await provider.vision(
            prompt="Analyze this chart",
            image_bytes_or_b64=dummy_image,
            mime_type="image/png",
        )
        assert "revenue growth" in result
        assert mock_post.called


def test_cloudflare_error_handling():
    """Test translation of HTTP errors to Aru AI exception hierarchy."""
    provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    # 401 Authentication Error
    resp_401 = httpx.Response(
        status_code=401,
        text="Invalid API Token",
        request=httpx.Request("POST", provider.chat_url),
    )
    with pytest.raises(ProviderAuthenticationError):
        provider._handle_http_error(
            httpx.HTTPStatusError("401", request=resp_401.request, response=resp_401)
        )

    # 429 Rate Limit Error
    resp_429 = httpx.Response(
        status_code=429,
        text="Rate limited",
        request=httpx.Request("POST", provider.chat_url),
    )
    with pytest.raises(ProviderRateLimitError):
        provider._handle_http_error(
            httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429)
        )

    # Timeout
    with pytest.raises(ProviderTimeoutError):
        provider._handle_http_error(httpx.TimeoutException("Timed out"))

    # Connection error
    with pytest.raises(ProviderUnavailableError):
        provider._handle_http_error(httpx.RequestError("Connection dropped"))


@pytest.mark.asyncio
async def test_cloudflare_in_provider_manager_failover():
    """Verify Cloudflare integrates smoothly in ProviderManager failover chain."""
    cf_provider = CloudflareProvider(api_key="cf-key-1", account_id="acc-1")

    pm = ProviderManager(
        priority=["groq", "gemini", "cloudflare", "deepseek", "openai"],
        auto_load=False,
    )

    from modules.llm.base_provider import BaseLLMProvider

    class MockFailingProvider(BaseLLMProvider):
        async def generate(self, *args, **kwargs) -> str:
            raise ProviderRateLimitError(f"{self.name} 429", provider=self.name)
        async def chat(self, *args, **kwargs):
            raise NotImplementedError
        async def vision(self, *args, **kwargs) -> str:
            raise NotImplementedError
        async def health_check(self) -> bool:
            return False

    pm.register_provider(MockFailingProvider("groq", api_key="k1"))
    pm.register_provider(MockFailingProvider("gemini", api_key="k2"))
    pm.register_provider(cf_provider)

    success_resp = _mock_response(
        200,
        json_data={"choices": [{"message": {"role": "assistant", "content": "Cloudflare handled the failover"}}]},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = success_resp
        res = await pm.generate("Test failover to Cloudflare")
        assert res == "Cloudflare handled the failover"


def test_cloudflare_env_detection_and_activation(monkeypatch):
    """Verify that configuring Cloudflare credentials makes Cloudflare enabled in ProviderManager."""
    provider = CloudflareProvider(api_key="cf-test-token", account_id="cf-test-account-id")
    assert provider.is_enabled is True
    assert provider.key_pool.total_keys == 1

    pm = ProviderManager(auto_load=False)
    pm.register_provider(provider)
    assert "cloudflare" in pm.get_enabled_providers()
    summary = pm.format_status_summary()
    assert "Cloudflare: Healthy (1 account)" in summary


def test_cloudflare_multi_account_numbered_env_parsing(monkeypatch):
    """Verify parse_cloudflare_credentials parses _2, _3, unlimited accounts with pairing."""
    from modules.config import parse_cloudflare_credentials

    test_env = {
        "CLOUDFLARE_ACCOUNT_ID": "acc_primary",
        "CLOUDFLARE_API_KEY": "key_primary",
        "CLOUDFLARE_ACCOUNT_ID_2": "acc_second",
        "CLOUDFLARE_API_KEY_2": "key_second",
        "CLOUDFLARE_ACCOUNT_ID_3": "acc_third",
        "CLOUDFLARE_API_KEY_3": "key_third",
    }
    accounts = parse_cloudflare_credentials(test_env)
    assert len(accounts) == 3
    assert accounts[0] == {"account_id": "acc_primary", "api_key": "key_primary"}
    assert accounts[1] == {"account_id": "acc_second", "api_key": "key_second"}
    assert accounts[2] == {"account_id": "acc_third", "api_key": "key_third"}

    # Provider initialization with parsed accounts
    provider = CloudflareProvider(accounts=accounts)
    assert provider.is_enabled is True
    assert provider.key_pool.total_keys == 3
    assert provider.key_pool.slots[0].account_id == "acc_primary"
    assert provider.key_pool.slots[0].api_key == "key_primary"
    assert provider.key_pool.slots[1].account_id == "acc_second"
    assert provider.key_pool.slots[1].api_key == "key_second"
    assert provider.key_pool.slots[2].account_id == "acc_third"
    assert provider.key_pool.slots[2].api_key == "key_third"


@pytest.mark.asyncio
async def test_cloudflare_multi_account_automatic_failover():
    """Verify that failing Account 1 switches URL account_id AND Bearer token to Account 2."""
    accounts = [
        {"account_id": "acc_111", "api_key": "token_111"},
        {"account_id": "acc_222", "api_key": "token_222"},
    ]
    provider = CloudflareProvider(accounts=accounts)
    assert provider.key_pool.total_keys == 2

    recorded_calls: list[dict[str, str]] = []

    async def mock_post(url, *args, **kwargs):
        headers = kwargs.get("headers", {})
        recorded_calls.append({
            "url": str(url),
            "auth": headers.get("Authorization", ""),
        })
        # Account 1 fails with 429 rate limit
        if "acc_111" in str(url):
            rate_limit_resp = httpx.Response(
                status_code=429,
                text="Rate limit exceeded on Account 1",
                request=httpx.Request("POST", str(url)),
            )
            raise httpx.HTTPStatusError("429", request=rate_limit_resp.request, response=rate_limit_resp)

        # Account 2 succeeds
        return _mock_response(
            200,
            json_data={"choices": [{"message": {"role": "assistant", "content": "Success from Account 2!"}}]},
        )

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        reply = await provider.generate("Test multi-account failover")
        assert reply == "Success from Account 2!"

    # Verify call history
    assert len(recorded_calls) == 2
    # First call: Account 1 URL and Token
    assert "accounts/acc_111/ai" in recorded_calls[0]["url"]
    assert recorded_calls[0]["auth"] == "Bearer token_111"
    # Second call: Account 2 URL and Token
    assert "accounts/acc_222/ai" in recorded_calls[1]["url"]
    assert recorded_calls[1]["auth"] == "Bearer token_222"

    # Slot 1 is cooling down, Slot 2 is active
    assert provider.key_pool.slots[0].is_in_cooldown() is True
    assert provider.key_pool.slots[1].is_in_cooldown() is False


@pytest.mark.asyncio
async def test_cloudflare_multi_account_vision_failover():
    """Verify vision requests switch account_id in run_url and token during failover."""
    accounts = [
        {"account_id": "acc_aaa", "api_key": "token_aaa"},
        {"account_id": "acc_bbb", "api_key": "token_bbb"},
    ]
    provider = CloudflareProvider(accounts=accounts)

    recorded_calls: list[dict[str, str]] = []

    async def mock_post(url, *args, **kwargs):
        headers = kwargs.get("headers", {})
        recorded_calls.append({
            "url": str(url),
            "auth": headers.get("Authorization", ""),
        })
        if "acc_aaa" in str(url):
            resp_429 = httpx.Response(
                status_code=429,
                text="Account AAA exhausted",
                request=httpx.Request("POST", str(url)),
            )
            raise httpx.HTTPStatusError("429", request=resp_429.request, response=resp_429)

        return _mock_response(
            200,
            json_data={"result": {"response": "Vision processed by Account BBB"}},
        )

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        result = await provider.vision("Analyze", b"fake_bytes")
        assert result == "Vision processed by Account BBB"

    assert len(recorded_calls) == 2
    assert "accounts/acc_aaa/ai/run" in recorded_calls[0]["url"]
    assert recorded_calls[0]["auth"] == "Bearer token_aaa"
    assert "accounts/acc_bbb/ai/run" in recorded_calls[1]["url"]
    assert recorded_calls[1]["auth"] == "Bearer token_bbb"


