"""Groq-powered AI responses for Aru."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from groq import Groq
from groq import APIConnectionError, APIStatusError, RateLimitError

from modules.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MODEL_FALLBACKS,
    LLM_COOLDOWN_SECONDS,
    LLM_PRIORITY,
    LLM_RETRY,
    LLM_TIMEOUT,
    SYSTEM_PROMPT,
    reload_settings,
)
from modules.llm.provider_manager import ProviderManager

logger = logging.getLogger("aru.ai")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0


class AruAI:
    """Unified AI client coordinating multi-provider failover (Gemini, OpenAI, Groq, DeepSeek)."""

    def __init__(self, provider_manager: ProviderManager | None = None) -> None:
        self._client: Groq | None = None
        self._connected = False
        self._active_model = GROQ_MODEL
        self.provider_manager = provider_manager or ProviderManager(
            priority=LLM_PRIORITY,
            timeout=LLM_TIMEOUT,
            retry=LLM_RETRY,
            cooldown_seconds=LLM_COOLDOWN_SECONDS,
            auto_load=True,
        )

    def connect(self) -> bool:
        reload_settings()
        self.provider_manager.timeout = LLM_TIMEOUT
        self.provider_manager.retry = LLM_RETRY
        self.provider_manager.cooldown_seconds = LLM_COOLDOWN_SECONDS
        self.provider_manager.switch_priority(LLM_PRIORITY)
        self.provider_manager.load_providers_from_env()

        # Connect legacy Groq client if key available
        if GROQ_API_KEY:
            try:
                self._client = Groq(api_key=GROQ_API_KEY)
                self._active_model = GROQ_MODEL
                logger.info("Legacy Groq client initialized (model=%s)", self._active_model)
            except Exception as exc:
                logger.warning("Legacy Groq client init failed: %s", exc)

        else:
            self._client = None

        enabled = self.provider_manager.get_enabled_providers()
        self._connected = bool(enabled) or (self._client is not None)
        if self._connected:
            logger.info("AI connected via ProviderManager (enabled: %s)", ", ".join(enabled) or "Groq legacy")
            return True

        logger.error("No LLM API keys configured (GEMINI_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY)")
        return False

    @property
    def is_connected(self) -> bool:
        if self.provider_manager and self.provider_manager.get_enabled_providers():
            return True
        return self._connected and self._client is not None

    @property
    def active_model(self) -> str:
        if self.provider_manager:
            active_name = self.provider_manager.get_active_provider_name()
            if active_name:
                p = self.provider_manager.get_provider(active_name)
                if p:
                    return getattr(p, "active_model", getattr(p, "default_model", self._active_model))
        return self._active_model

    @property
    def active_provider(self) -> str | None:
        return self.provider_manager.get_active_provider_name() if self.provider_manager else None

    def _models_to_try(self) -> list[str]:
        ordered: list[str] = []
        for name in (self.active_model, GROQ_MODEL, *GROQ_MODEL_FALLBACKS):
            if name and name not in ordered:
                ordered.append(name)
        return ordered

    async def health_check(self) -> bool:
        """Light ping to verify API connectivity across providers."""
        if not self.is_connected:
            return False
        active_p = self.active_provider
        p_label = active_p.capitalize() if active_p else "AI"
        reply = await self.generate("Reply with exactly: OK", max_tokens=16)
        ok = bool(reply) and "দুঃখিত" not in reply and len(reply) < 200
        if ok:
            logger.info("%s health check passed (model=%s)", p_label, self.active_model)
        else:
            logger.warning("%s health check failed: %s", p_label, reply[:120])
        return ok

    async def generate(
        self,
        user_message: str,
        *,
        memory_context: str = "",
        conversation_history: list[dict[str, str]] | None = None,
        max_tokens: int = 2048,
    ) -> str:
        """Generate assistant reply with automatic multi-provider failover."""
        if not self.is_connected:
            return "দুঃখিত বস, AI সিস্টেম এখন সংযুক্ত নয়। একটু পরে আবার চেষ্টা করুন।"

        system = SYSTEM_PROMPT
        if memory_context:
            system += f"\n\nRelevant memories about Boss:\n{memory_context}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if conversation_history:
            messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": user_message})

        # 1. Try unified ProviderManager failover first
        if self.provider_manager and self.provider_manager.get_enabled_providers():
            try:
                if conversation_history:
                    content, _ = await self.provider_manager.chat(messages=messages, max_tokens=max_tokens)
                    if content:
                        return content.strip()
                else:
                    return await self.provider_manager.generate(
                        prompt=user_message,
                        system_prompt=system,
                        max_tokens=max_tokens,
                    )
            except Exception as exc:
                logger.warning("ProviderManager failover exhausted: %s — trying legacy client fallback", exc)

        # 2. Legacy fallback path if client exists
        if self._client:
            last_error: Exception | None = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    response = await asyncio.to_thread(
                        self._call_api,
                        messages,
                        max_tokens,
                    )
                    return response
                except RateLimitError as exc:
                    last_error = exc
                    wait = RETRY_DELAY_SECONDS * attempt
                    logger.warning("Groq rate limit, retry %s/%s in %ss", attempt, MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                except (APIConnectionError, APIStatusError) as exc:
                    last_error = exc
                    wait = RETRY_DELAY_SECONDS * attempt
                    logger.warning("Groq API error: %s — retry %s/%s", exc, attempt, MAX_RETRIES)
                    await asyncio.sleep(wait)
                except Exception as exc:
                    last_error = exc
                    logger.exception("Unexpected Groq error: %s", exc)
                    break
            logger.error("Groq legacy failed after retries: %s", last_error)

        return (
            "দুঃখিত বস, AI উত্তর তৈরি করতে পারছি না। "
            "অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
        )

    async def chat_completion_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 2048,
    ) -> tuple[str | None, list[Any] | None]:
        """
        Execute completion with optional tool definitions and multi-provider failover.
        Returns: (content: str | None, tool_calls: list | None)
        """
        if not self.is_connected:
            return "দুঃখিত বস, AI সিস্টেম এখন সংযুক্ত নয়।", None

        # 1. Try unified ProviderManager failover
        if self.provider_manager and self.provider_manager.get_enabled_providers():
            try:
                return await self.provider_manager.chat(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.warning("ProviderManager chat failover exhausted: %s — trying legacy client fallback", exc)

        # 2. Legacy fallback path
        if not self._client:
            return "দুঃখিত বস, AI প্রভাইডার অনুপলব্ধ।", None

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                content, tool_calls = await asyncio.to_thread(
                    self._call_api_with_tools,
                    messages,
                    tools,
                    tool_choice,
                    max_tokens,
                )
                return content, tool_calls
            except RateLimitError as exc:
                last_error = exc
                wait = RETRY_DELAY_SECONDS * attempt
                logger.warning("Groq rate limit (tools), retry %s/%s in %ss", attempt, MAX_RETRIES, wait)
                await asyncio.sleep(wait)
            except (APIConnectionError, APIStatusError) as exc:
                last_error = exc
                wait = RETRY_DELAY_SECONDS * attempt
                logger.warning("Groq API error (tools): %s — retry %s/%s", exc, attempt, MAX_RETRIES)
                await asyncio.sleep(wait)
            except Exception as exc:
                last_error = exc
                logger.exception("Unexpected Groq error (tools): %s", exc)
                break

        logger.error("Groq chat_completion_with_tools failed after retries: %s", last_error)
        return "দুঃখিত বস, সমস্ত AI সিস্টেম এই মুহূর্তে অনুপলব্ধ। কিছুক্ষণ পর আবার চেষ্টা করুন।", None

    async def vision(
        self,
        prompt: str,
        image_bytes_or_b64: bytes | str,
        *,
        mime_type: str = "image/jpeg",
        max_tokens: int = 1024,
    ) -> str:
        """Analyze image with automatic multi-provider vision failover (Gemini -> Groq -> DeepSeek -> OpenAI)."""
        if not self.is_connected:
            return "দুঃখিত বস, AI ভিশন সিস্টেম এখন সংযুক্ত নয়।"

        if self.provider_manager and self.provider_manager.get_enabled_providers():
            try:
                return await self.provider_manager.vision(
                    prompt=prompt,
                    image_bytes_or_b64=image_bytes_or_b64,
                    mime_type=mime_type,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.warning("ProviderManager vision failover exhausted: %s", exc)

        return "দুঃখিত বস, এই মুহূর্তে ছবিটি বিশ্লেষণ করা সম্ভব হয়নি। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"

    def _call_api(self, messages: list[dict[str, Any]], max_tokens: int) -> str:
        content, _ = self._call_api_with_tools(messages, tools=None, tool_choice=None, max_tokens=max_tokens)
        return (content or "").strip()

    def _call_api_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        max_tokens: int = 2048,
    ) -> tuple[str | None, list[Any] | None]:
        assert self._client is not None
        errors: list[str] = []
        for model in self._models_to_try():
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                }
                if tools:
                    kwargs["tools"] = tools
                    if tool_choice:
                        kwargs["tool_choice"] = tool_choice

                completion = self._client.chat.completions.create(**kwargs)
                self._active_model = model
                choice = completion.choices[0]
                msg = choice.message
                content = (msg.content or "").strip() if msg.content else None
                tool_calls = msg.tool_calls if hasattr(msg, "tool_calls") and msg.tool_calls else None
                return content, tool_calls
            except APIStatusError as exc:
                errors.append(f"{model}: {exc}")
                if exc.status_code == 404 or "model" in str(exc).lower():
                    logger.warning("Groq model unavailable: %s — trying next", model)
                    continue
                raise
        raise RuntimeError(f"All Groq models failed: {'; '.join(errors)}")

