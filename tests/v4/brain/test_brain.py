"""Unit tests for Phase 8: Brain Layer and LLM Inference."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from aru.brain import (
    AllProvidersFailedError,
    CloudflareProvider,
    DeepSeekProvider,
    GroqProvider,
    LLMMessage,
    LLMResponse,
    LLMRouter,
    OpenRouterProvider,
    PromptLoader,
    PromptTemplate,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TokenBudgetManager,
    TokenUsage,
)


def test_token_budget_manager_and_message_fitting() -> None:
    """Verify TokenBudgetManager estimates tokens and preserves system prompt on fit."""
    sys_msg = LLMMessage(role="system", content="You are Aru, helpful assistant.")
    u1 = LLMMessage(role="user", content="Turn 1: Very long question about life and everything in it.")
    a1 = LLMMessage(role="assistant", content="Turn 1 answer: 42.")
    u2 = LLMMessage(role="user", content="Turn 2: Followup question.")
    a2 = LLMMessage(role="assistant", content="Turn 2 answer: Here it is.")

    messages = [sys_msg, u1, a1, u2, a2]

    # Full cost
    total_tokens = TokenBudgetManager.estimate_messages_tokens(messages)
    assert total_tokens > 20

    # Fit with restrictive budget: must retain sys_msg and latest turns
    fitted = TokenBudgetManager.fit_messages(messages, max_tokens=30)
    assert fitted[0].role == "system"
    assert fitted[-1].content == "Turn 2 answer: Here it is."
    assert len(fitted) < len(messages)


def test_prompt_template_and_loader() -> None:
    """Verify PromptTemplate safe variable rendering and PromptLoader context assembly."""
    tmpl = PromptTemplate("Hello ${boss_name}, system status is ${status}.")
    rendered = tmpl.render(boss_name="Manjurul", status="operational")
    assert rendered == "Hello Manjurul, system status is operational."

    loader = PromptLoader()
    sys_msg = loader.build_system_message(
        boss_name="Manjurul",
        relevant_memories=["Prefers black coffee", "Working on V4 migration"],
        extra_directives=["Be concise"],
    )
    assert sys_msg.role == "system"
    assert "Prefers black coffee" in sys_msg.content
    assert "Be concise" in sys_msg.content
    assert "Manjurul" in sys_msg.content


@pytest.mark.asyncio
async def test_groq_provider_generation() -> None:
    """Verify GroqProvider parses successful OpenAI-compatible chat response."""
    provider = GroqProvider(api_keys=["gsk_mock_key_1", "gsk_mock_key_2"])

    mock_response = httpx.Response(
        status_code=200,
        json={
            "model": "qwen/qwen3.8-27b",
            "choices": [{"message": {"content": "Hello from Groq!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        },
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        messages = [LLMMessage(role="user", content="Hi")]
        res = await provider.generate(messages)

        assert res.content == "Hello from Groq!"
        assert res.provider == "groq"
        assert res.model == "qwen/qwen3.8-27b"
        assert res.token_usage.total_tokens == 17
    await provider.close()


@pytest.mark.asyncio
async def test_cloudflare_provider_generation() -> None:
    """Verify CloudflareProvider endpoint building and response extraction."""
    accounts = [{"account_id": "cf_acc_123", "api_key": "cf_key_456"}]
    provider = CloudflareProvider(accounts=accounts)
    assert provider.is_available is True

    mock_response = httpx.Response(
        status_code=200,
        json={
            "result": {"response": "Hello from Cloudflare Workers AI!"},
            "usage": {"total_tokens": 8},
        },
        request=httpx.Request("POST", "https://api.cloudflare.com"),
    )

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        messages = [LLMMessage(role="user", content="Hi")]
        res = await provider.generate(messages)

        assert res.content == "Hello from Cloudflare Workers AI!"
        assert res.provider == "cloudflare"
    await provider.close()


@pytest.mark.asyncio
async def test_router_automatic_failover() -> None:
    """Verify LLMRouter automatically fails over when primary provider fails."""
    router = LLMRouter(priority=["groq", "deepseek"], max_retries=1, cooldown_seconds=60.0)

    # Provider 1 (groq): Fails with rate limit (429)
    p_groq = MagicMock()
    p_groq.name = "groq"
    p_groq.is_available = True
    p_groq.generate = AsyncMock(
        side_effect=ProviderRateLimitError("groq", "Rate limit hit", status_code=429)
    )

    # Provider 2 (deepseek): Succeeds
    p_deepseek = MagicMock()
    p_deepseek.name = "deepseek"
    p_deepseek.is_available = True
    p_deepseek.generate = AsyncMock(
        return_value=LLMResponse(
            content="Failover success from DeepSeek!",
            model="deepseek-chat",
            provider="deepseek",
            token_usage=TokenUsage(total_tokens=10),
        )
    )

    router.register_provider(p_groq)
    router.register_provider(p_deepseek)

    messages = [LLMMessage(role="user", content="Hello")]
    res = await router.generate(messages)

    assert res.content == "Failover success from DeepSeek!"
    assert res.provider == "deepseek"
    # Verify groq was placed in cooldown
    assert router.is_in_cooldown("groq") is True
    assert router.is_in_cooldown("deepseek") is False


@pytest.mark.asyncio
async def test_router_all_providers_failed_error() -> None:
    """Verify router raises AllProvidersFailedError when all providers fail."""
    router = LLMRouter(priority=["groq"], max_retries=0, cooldown_seconds=60.0)

    p_groq = MagicMock()
    p_groq.name = "groq"
    p_groq.is_available = True
    p_groq.generate = AsyncMock(
        side_effect=ProviderTimeoutError("groq", "Gateway timeout")
    )
    router.register_provider(p_groq)

    with pytest.raises(AllProvidersFailedError):
        await router.generate([LLMMessage(role="user", content="Hello")])
