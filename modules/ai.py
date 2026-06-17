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
    SYSTEM_PROMPT,
    reload_settings,
)

logger = logging.getLogger("aru.ai")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0


class AruAI:
    """Groq chat client with retries and memory context injection."""

    def __init__(self) -> None:
        self._client: Groq | None = None
        self._connected = False
        self._active_model = GROQ_MODEL

    def connect(self) -> bool:
        reload_settings()
        if not GROQ_API_KEY:
            logger.error("GROQ_API_KEY is not set")
            return False
        try:
            self._client = Groq(api_key=GROQ_API_KEY)
            self._connected = True
            self._active_model = GROQ_MODEL
            logger.info("Groq client initialized (model=%s)", self._active_model)
            return True
        except Exception as exc:
            logger.exception("Failed to initialize Groq: %s", exc)
            self._connected = False
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    @property
    def active_model(self) -> str:
        return self._active_model

    def _models_to_try(self) -> list[str]:
        ordered: list[str] = []
        for name in (GROQ_MODEL, *GROQ_MODEL_FALLBACKS):
            if name and name not in ordered:
                ordered.append(name)
        return ordered

    async def health_check(self) -> bool:
        """Light ping to verify API connectivity."""
        if not self.is_connected:
            return False
        reply = await self.generate("Reply with exactly: OK", max_tokens=16)
        ok = bool(reply) and "দুঃখিত" not in reply and len(reply) < 200
        if ok:
            logger.info("Groq health check passed (model=%s)", self._active_model)
        else:
            logger.warning("Groq health check failed: %s", reply[:120])
        return ok

    async def generate(
        self,
        user_message: str,
        *,
        memory_context: str = "",
        conversation_history: list[dict[str, str]] | None = None,
        max_tokens: int = 2048,
    ) -> str:
        """Generate assistant reply with optional memory and history."""
        if not self.is_connected or self._client is None:
            return "দুঃখিত বস, AI সিস্টেম এখন সংযুক্ত নয়। একটু পরে আবার চেষ্টা করুন।"

        system = SYSTEM_PROMPT
        if memory_context:
            system += f"\n\nRelevant memories about Boss:\n{memory_context}"

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        if conversation_history:
            messages.extend(conversation_history[-10:])
        messages.append({"role": "user", "content": user_message})

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

        logger.error("Groq failed after retries: %s", last_error)
        return (
            "দুঃখিত বস, AI উত্তর তৈরি করতে পারছি না। "
            "অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
        )

    def _call_api(self, messages: list[dict[str, Any]], max_tokens: int) -> str:
        assert self._client is not None
        errors: list[str] = []
        for model in self._models_to_try():
            try:
                completion = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                )
                self._active_model = model
                choice = completion.choices[0]
                content = choice.message.content
                return (content or "").strip()
            except APIStatusError as exc:
                errors.append(f"{model}: {exc}")
                if exc.status_code == 404 or "model" in str(exc).lower():
                    logger.warning("Groq model unavailable: %s — trying next", model)
                    continue
                raise
        raise RuntimeError(f"All Groq models failed: {'; '.join(errors)}")
