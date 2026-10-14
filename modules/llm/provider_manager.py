"""ProviderManager coordinating multi-provider LLM failover, retries, and circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine

from modules.llm.base_provider import BaseLLMProvider, ProviderHealthState
from modules.llm.cloudflare_provider import CloudflareProvider
from modules.llm.deepseek_provider import DeepSeekProvider
from modules.llm.exceptions import (
    AllProvidersFailedError,
    CircuitBreakerOpenError,
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderPoolExhaustedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.gemini_provider import GeminiProvider
from modules.llm.groq_provider import GroqProvider
from modules.llm.openrouter_provider import OPENROUTER_DEFAULT_MODEL, OpenRouterProvider
from modules.token_optimizer import estimate_tokens, get_optimal_max_tokens

logger = logging.getLogger("aru.llm.manager")

DEFAULT_PRIORITY = ["openrouter", "groq", "gemini", "cloudflare", "deepseek"]


class ProviderManager:
    """
    Central LLM Orchestration Hub.
    Manages automatic failover, retries with exponential backoff, circuit breaking,
    and runtime health monitoring across Gemini, OpenAI, Groq, Cloudflare, and DeepSeek.
    """

    def __init__(
        self,
        priority: list[str] | None = None,
        timeout: float = 30.0,
        retry: int = 2,
        cooldown_seconds: float = 300.0,
        providers: dict[str, BaseLLMProvider] | None = None,
        auto_load: bool = True,
    ) -> None:
        self.timeout = float(timeout)
        self.retry = max(1, int(retry))
        self.cooldown_seconds = float(cooldown_seconds)
        self._providers: dict[str, BaseLLMProvider] = providers or {}
        if priority is not None:
            self._priority = [p.lower() for p in priority]
        elif providers is not None:
            self._priority = [p.lower() for p in providers.keys()]
        else:
            self._priority = [p.lower() for p in DEFAULT_PRIORITY]

        if auto_load and not self._providers:
            self.load_providers_from_env()

    def load_providers_from_env(self) -> None:
        """Instantiate providers using environment variables."""
        from modules.config import parse_api_keys, parse_cloudflare_credentials

        gemini_keys = parse_api_keys(os.getenv("GEMINI_API_KEYS"), os.getenv("GEMINI_API_KEY"))
        openrouter_keys = parse_api_keys(
            os.getenv("OPENROUTER_API_KEYS"),
            os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEYS") or os.getenv("OPENAI_API_KEY"),
        )
        openrouter_model = (os.getenv("OPENROUTER_MODEL") or "").strip()
        groq_keys = parse_api_keys(os.getenv("GROQ_API_KEYS"), os.getenv("GROQ_API_KEY"))
        deepseek_keys = parse_api_keys(os.getenv("DEEPSEEK_API_KEYS"), os.getenv("DEEPSEEK_API_KEY"))
        cloudflare_accounts = parse_cloudflare_credentials()

        self._providers["openrouter"] = OpenRouterProvider(
            api_keys=openrouter_keys,
            default_model=openrouter_model or OPENROUTER_DEFAULT_MODEL,
            timeout=self.timeout,
        )
        # Backward-compatibility alias
        self._providers["openai"] = self._providers["openrouter"]
        self._providers["gemini"] = GeminiProvider(
            api_keys=gemini_keys,
            timeout=self.timeout,
        )
        self._providers["groq"] = GroqProvider(
            api_keys=groq_keys,
            timeout=self.timeout,
        )
        self._providers["deepseek"] = DeepSeekProvider(
            api_keys=deepseek_keys,
            timeout=self.timeout,
        )
        self._providers["cloudflare"] = CloudflareProvider(
            accounts=cloudflare_accounts,
            timeout=self.timeout,
        )

        enabled = [k for k, p in self._providers.items() if p.is_enabled]
        logger.info(
            "Loaded %d LLM providers (enabled: %s) with priority: %s",
            len(self._providers),
            ", ".join(enabled) or "None",
            " -> ".join(self._priority),
        )

    def register_provider(self, provider: BaseLLMProvider) -> None:
        """Register or override a provider instance."""
        name = provider.name.lower()
        self._providers[name] = provider
        if name not in self._priority:
            self._priority.append(name)
        logger.info("Registered provider '%s' (enabled=%s)", name, provider.is_enabled)

    def get_provider(self, name: str) -> BaseLLMProvider | None:
        """Retrieve provider by name."""
        return self._providers.get(name.lower())

    @property
    def priority(self) -> list[str]:
        return list(self._priority)

    def switch_priority(self, new_priority: list[str]) -> None:
        """Update provider priority order dynamically."""
        cleaned = [p.strip().lower() for p in new_priority if p.strip()]
        for p in self._priority:
            if p not in cleaned:
                cleaned.append(p)
        self._priority = cleaned
        logger.info("Updated provider priority order: %s", " -> ".join(self._priority))

    def get_enabled_providers(self) -> list[str]:
        """Return names of all configured providers."""
        return [name for name in self._priority if name in self._providers and self._providers[name].is_enabled]

    def get_active_provider_name(self) -> str | None:
        """Return the first healthy enabled provider according to priority."""
        for name in self._priority:
            provider = self._providers.get(name)
            if provider and provider.is_enabled and not provider.is_in_cooldown():
                return name
        return None

    def set_provider_cooldown(self, provider_name: str, seconds: float) -> None:
        """Manually trigger circuit breaker cooldown for a provider."""
        provider = self.get_provider(provider_name)
        if provider:
            provider.record_failure(RuntimeError("Manual cooldown trigger"), cooldown_seconds=seconds)
            logger.warning("Provider '%s' manually placed into cooldown for %ss", provider_name, seconds)

    def reset_all_cooldowns(self) -> None:
        """Reset circuit breaker cooldown on all providers."""
        for provider in self._providers.values():
            provider.reset_cooldown()
        logger.info("All provider circuit breakers reset to healthy.")

    async def _execute_with_failover(
        self,
        operation_name: str,
        runner_fn: Callable[[BaseLLMProvider], Coroutine[Any, Any, Any]],
    ) -> Any:
        """
        Executes an operation across providers in priority order with:
        - Circuit breaker bypass if cooldown expired (automatic recovery)
        - Per-provider retry with exponential backoff
        - Seamless automatic failover to the next provider on failure
        """
        enabled_names = [name for name in self._priority if name in self._providers and self._providers[name].is_enabled]

        if not enabled_names:
            raise ProviderUnavailableError("No LLM providers are configured with valid API keys.")

        attempts_record: list[dict[str, Any]] = []

        for idx, provider_name in enumerate(self._priority):
            provider = self._providers.get(provider_name)
            if not provider or not provider.is_enabled:
                continue

            # Circuit breaker check: automatic recovery if cooldown expired
            if provider.is_in_cooldown():
                if provider.cooldown_seconds_remaining() <= 0:
                    logger.info("Circuit breaker cooldown expired for '%s'; allowing probe request.", provider_name)
                    provider.reset_cooldown()
                else:
                    rem = round(provider.cooldown_seconds_remaining(), 1)
                    logger.debug("Skipping '%s' (in cooldown, %ss remaining)", provider_name, rem)
                    attempts_record.append({
                        "provider": provider_name,
                        "status": "skipped_cooldown",
                        "error": f"In cooldown ({rem}s left)",
                    })
                    continue

            # Determine next fallback candidates for production visibility
            fallback_candidates = [
                p for p in self._priority[idx + 1 :]
                if p in self._providers and self._providers[p].is_enabled and not self._providers[p].is_in_cooldown()
            ]
            next_fallback_label = fallback_candidates[0] if fallback_candidates else "None"

            # Provider attempt loop with retries and exponential backoff
            for attempt in range(1, self.retry + 1):
                if attempt > 1:
                    backoff = 1.0 * (2 ** (attempt - 2))
                    logger.info("Retrying '%s' (attempt %d/%d) in %.1fs...", provider_name, attempt, self.retry, backoff)
                    await asyncio.sleep(backoff)

                start_time = time.perf_counter()
                try:
                    logger.info("Selected provider '%s' for %s (attempt %d/%d)", provider_name, operation_name, attempt, self.retry)
                    result = await runner_fn(provider)
                    latency = time.perf_counter() - start_time
                    provider.record_success(latency)
                    logger.info(
                        "Provider '%s' succeeded for %s (latency=%.3fs, attempt=%d/%d)",
                        provider_name,
                        operation_name,
                        latency,
                        attempt,
                        self.retry,
                    )
                    return result
                except Exception as exc:
                    latency = time.perf_counter() - start_time
                    err_str = str(exc)
                    logger.warning(
                        "Provider '%s' failed attempt %d/%d on %s (latency=%.3fs, error=%s)",
                        provider_name,
                        attempt,
                        self.retry,
                        operation_name,
                        latency,
                        err_str,
                    )
                    attempts_record.append({
                        "provider": provider_name,
                        "attempt": attempt,
                        "latency_sec": round(latency, 3),
                        "error": err_str,
                    })

                    # Fast-failover on non-retryable errors (pool exhausted, rate limits, quotas, auth, context length)
                    is_pool_exhausted = isinstance(exc, ProviderPoolExhaustedError)
                    is_rate_or_quota = isinstance(exc, ProviderRateLimitError) or any(
                        kw in err_str.lower() for kw in ("429", "402", "quota", "balance", "rate limit", "credit")
                    )
                    is_auth = isinstance(exc, ProviderAuthenticationError) or any(
                        kw in err_str.lower() for kw in ("401", "403", "api key", "credentials")
                    )
                    is_context_or_invalid = any(
                        kw in err_str.lower() for kw in ("context limit", "token limit", "400", "404", "model not found")
                    )
                    should_fast_failover = is_pool_exhausted or (
                        bool(fallback_candidates) and (is_rate_or_quota or is_auth or is_context_or_invalid)
                    )

                    if attempt == self.retry or should_fast_failover:
                        # Mark unhealthy and trip circuit breaker for this provider
                        provider.record_failure(exc, cooldown_seconds=self.cooldown_seconds)
                        logger.warning(
                            "Provider '%s' marked UNHEALTHY (cooldown=%ds). Immediately failing over to fallback provider '%s'...",
                            provider_name,
                            self.cooldown_seconds,
                            next_fallback_label,
                        )
                        break

        # All providers failed
        logger.error("All enabled LLM providers failed for %s. Attempts: %s", operation_name, attempts_record)
        raise AllProvidersFailedError(
            f"All configured LLM providers failed for {operation_name}.",
            attempts=attempts_record,
        )

    # --- Public Uniform API ---

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
        """Generate response with automatic multi-provider failover."""
        optimal_tokens = get_optimal_max_tokens(prompt, requested_tokens=max_tokens)

        async def _run(p: BaseLLMProvider) -> str:
            p_tokens = get_optimal_max_tokens(prompt, provider=p.name, requested_tokens=optimal_tokens)
            return await p.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=p_tokens,
                temperature=temperature,
                model=model,
                **kwargs,
            )

        return await self._execute_with_failover("generate", _run)

    async def generate_safe(
        self,
        prompt: str,
        *,
        fallback_message: str = "দুঃখিত বস, সমস্ত AI প্রভাইডার এই মুহূর্তে অনুপলব্ধ। কিছুক্ষণ পর আবার চেষ্টা করুন।",
        **kwargs: Any,
    ) -> str:
        """Generate response with automatic failover, returning graceful message if all fail."""
        try:
            return await self.generate(prompt, **kwargs)
        except AllProvidersFailedError as exc:
            logger.error("Failover exhausted in generate_safe: %s", exc)
            return fallback_message
        except Exception as exc:
            logger.exception("Unexpected error in generate_safe: %s", exc)
            return fallback_message

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
        """Multi-turn chat completion with optional tool calls and automatic failover."""
        user_text = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)),
            "",
        )
        optimal_tokens = get_optimal_max_tokens(user_text, requested_tokens=max_tokens)

        async def _run(p: BaseLLMProvider) -> tuple[str | None, list[Any] | None]:
            p_tokens = get_optimal_max_tokens(user_text, provider=p.name, requested_tokens=optimal_tokens)
            return await p.chat(
                messages=messages,
                max_tokens=p_tokens,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
                json_mode=json_mode,
                model=model,
                **kwargs,
            )

        return await self._execute_with_failover("chat", _run)

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
        """Analyze an image with automatic multi-provider failover."""
        async def _run(p: BaseLLMProvider) -> str:
            p_tokens = get_optimal_max_tokens(prompt, task_type="vision", provider=p.name, requested_tokens=max_tokens)
            return await p.vision(
                prompt=prompt,
                image_bytes_or_b64=image_bytes_or_b64,
                max_tokens=p_tokens,
                model=model,
                mime_type=mime_type,
                **kwargs,
            )

        return await self._execute_with_failover("vision", _run)

    async def embedding(
        self,
        text: str,
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[float]:
        """Generate text embedding with automatic failover."""
        async def _run(p: BaseLLMProvider) -> list[float]:
            return await p.embedding(text=text, model=model, **kwargs)

        return await self._execute_with_failover("embedding", _run)

    async def health_check_all(self) -> dict[str, bool]:
        """Perform concurrent ping checks across all enabled providers."""
        results: dict[str, bool] = {}
        names: list[str] = []
        tasks: list[Coroutine[Any, Any, bool]] = []
        for name, provider in self._providers.items():
            if not provider.is_enabled:
                results[name] = False
                continue
            names.append(name)
            tasks.append(provider.health_check())

        if tasks:
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for name, outcome in zip(names, outcomes):
                if isinstance(outcome, Exception):
                    logger.warning("Health check exception for '%s': %s", name, outcome)
                    results[name] = False
                else:
                    results[name] = bool(outcome)
        return results

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """Return structured metrics and status for all registered providers."""
        return {
            name: provider.health.to_dict()
            for name, provider in self._providers.items()
        }

    def format_status_summary(self) -> str:
        """
        Format provider statuses for display in `/status`.
        Example output:
            Gemini: Healthy
            OpenAI: Healthy
            Groq: Healthy
            DeepSeek: Cooldown
        """
        display_names = {
            "openrouter": "OpenRouter",
            "openai": "OpenRouter",
            "gemini": "Gemini",
            "groq": "Groq",
            "deepseek": "DeepSeek",
            "cloudflare": "Cloudflare",
        }
        lines: list[str] = []
        # Display in priority order
        displayed = set()
        for name in self._priority:
            provider = self._providers.get(name)
            if provider:
                displayed.add(name)
                state_str = provider.health.status.value
                d_name = display_names.get(provider.name.lower(), provider.name.capitalize())
                num_keys = provider.key_pool.total_keys if hasattr(provider, "key_pool") else (1 if provider.is_enabled else 0)
                unit = ("accounts" if num_keys != 1 else "account") if provider.name.lower() == "cloudflare" else ("keys" if num_keys != 1 else "key")
                key_info = f" ({num_keys} {unit})" if num_keys > 0 else ""
                lines.append(f"{d_name}: {state_str}{key_info}")

        # Any remaining registered providers
        for name, provider in self._providers.items():
            if name not in displayed and name != "openai":
                d_name = display_names.get(provider.name.lower(), provider.name.capitalize())
                num_keys = provider.key_pool.total_keys if hasattr(provider, "key_pool") else (1 if provider.is_enabled else 0)
                unit = ("accounts" if num_keys != 1 else "account") if provider.name.lower() == "cloudflare" else ("keys" if num_keys != 1 else "key")
                key_info = f" ({num_keys} {unit})" if num_keys > 0 else ""
                lines.append(f"{d_name}: {provider.health.status.value}{key_info}")

        return "\n".join(lines)
