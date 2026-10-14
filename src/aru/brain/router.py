"""Multi-provider LLM router with automatic failover and circuit breaking for ARU AI V4."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from aru.brain.exceptions import AllProvidersFailedError, ProviderError
from aru.brain.interfaces import ILLMProvider
from aru.brain.models import LLMMessage, LLMResponse
from aru.core.config.models import AppSettings
from aru.core.logging import StructuredLogger


class LLMRouter:
    """
    Intelligent LLM gateway managing provider failover chains, cooldown timers,
    per-provider retry policies, and health telemetry.
    """

    def __init__(
        self,
        settings: AppSettings | None = None,
        logger: StructuredLogger | None = None,
        priority: list[str] | None = None,
        max_retries: int = 2,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self._logger = logger or StructuredLogger("aru.brain.router")
        self._providers: dict[str, ILLMProvider] = {}
        self._cooldowns: dict[str, float] = {}
        self._consecutive_failures: dict[str, int] = {}

        if settings:
            self._priority = [p.lower() for p in settings.llm.priority]
            self._max_retries = settings.llm.retry
            self._cooldown_seconds = settings.llm.cooldown_seconds
            self._default_timeout = settings.llm.timeout
        else:
            self._priority = [p.lower() for p in (priority or ["openrouter", "groq", "gemini", "cloudflare", "deepseek"])]
            self._max_retries = max_retries
            self._cooldown_seconds = cooldown_seconds
            self._default_timeout = 30.0

    @property
    def priority(self) -> list[str]:
        return list(self._priority)

    def register_provider(self, provider: ILLMProvider) -> None:
        """Register an active LLM provider adapter."""
        self._providers[provider.name.lower()] = provider

    def get_provider(self, name: str) -> ILLMProvider | None:
        """Retrieve provider by name."""
        return self._providers.get(name.lower())

    def is_in_cooldown(self, name: str) -> bool:
        """Check whether provider is currently in rate-limit cooldown."""
        until = self._cooldowns.get(name.lower(), 0.0)
        return time.time() < until

    def set_cooldown(self, name: str, seconds: float | None = None) -> None:
        """Put provider on cooldown."""
        cd = seconds if seconds is not None else self._cooldown_seconds
        self._cooldowns[name.lower()] = time.time() + cd
        failures = self._consecutive_failures.get(name.lower(), 0) + 1
        self._consecutive_failures[name.lower()] = failures
        self._logger.warning(
            "Provider '%s' placed in cooldown for %.1fs (consecutive failures: %d)",
            name,
            cd,
            failures,
        )

    def clear_cooldown(self, name: str) -> None:
        """Clear cooldown for a provider."""
        self._cooldowns.pop(name.lower(), None)
        self._consecutive_failures[name.lower()] = 0

    def get_available_providers(self) -> list[str]:
        """Return list of registered and available provider names in priority order."""
        available: list[str] = []
        for name in self._priority:
            p = self._providers.get(name)
            if p and p.is_available:
                available.append(name)
        # Append any registered providers not explicitly in priority list
        for name, p in self._providers.items():
            if name not in available and p.is_available:
                available.append(name)
        return available

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float | None = None,
        preferred_provider: str | None = None,
    ) -> LLMResponse:
        """
        Execute completion with automatic fallback and retry across providers.
        """
        candidate_names = self.get_available_providers()
        if preferred_provider and preferred_provider.lower() in candidate_names:
            # Move preferred provider to the front
            candidate_names.remove(preferred_provider.lower())
            candidate_names.insert(0, preferred_provider.lower())

        if not candidate_names:
            raise AllProvidersFailedError("No LLM providers are configured and available.")

        # Check if all candidate providers are in cooldown
        all_in_cooldown = all(self.is_in_cooldown(name) for name in candidate_names)

        errors: dict[str, str] = {}

        for name in candidate_names:
            if not all_in_cooldown and self.is_in_cooldown(name):
                self._logger.debug("Skipping provider '%s' (in cooldown)", name)
                continue

            provider = self._providers[name]

            # Attempt provider execution with retry loop
            for attempt in range(self._max_retries + 1):
                try:
                    self._logger.info(
                        "Dispatching to LLM provider '%s' (attempt %d/%d)",
                        name,
                        attempt + 1,
                        self._max_retries + 1,
                    )
                    req_timeout = timeout or self._default_timeout
                    response = await provider.generate(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout=req_timeout,
                    )
                    # Successful completion
                    self.clear_cooldown(name)
                    return response
                except Exception as err:
                    self._logger.warning(
                        "Provider '%s' failed on attempt %d: %s",
                        name,
                        attempt + 1,
                        err,
                    )
                    errors[f"{name}_attempt_{attempt + 1}"] = str(err)
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.2 * (2**attempt))
                    else:
                        # Max retries exhausted for this provider; set cooldown and fall over
                        self.set_cooldown(name)

        # If loop finishes without returning, all providers failed
        error_summary = "; ".join(f"{k}: {v}" for k, v in errors.items())
        self._logger.error("All LLM providers failed. Summary: %s", error_summary)
        raise AllProvidersFailedError(f"All configured LLM providers failed: {error_summary}")
