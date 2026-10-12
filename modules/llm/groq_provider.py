"""Groq LLM Provider implementation using async HTTP API with KeyPool and model fallbacks."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from modules.llm.base_provider import BaseLLMProvider
from modules.llm.exceptions import (
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from modules.llm.key_pool import APIKeySlot

logger = logging.getLogger("aru.llm.groq")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = (
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama-3.1-8b-instant",
)


class GroqProvider(BaseLLMProvider):
    """
    Groq Cloud API provider with high-speed LPU inference, KeyPool failover, and internal model failover.
    Direct async HTTP communication with Groq REST endpoint.
    """

    def __init__(
        self,
        api_key: str = "",
        api_keys: list[str] | None = None,
        default_model: str = "qwen/qwen3.8-27b",
        timeout: float = 30.0,
        model_fallbacks: tuple[str, ...] = GROQ_MODELS,
    ) -> None:
        super().__init__(
            name="groq",
            api_key=api_key,
            api_keys=api_keys,
            default_model=default_model,
            timeout=timeout,
        )
        self.model_fallbacks = model_fallbacks
        self._active_model = default_model

    @property
    def active_model(self) -> str:
        return self._active_model

    def _get_headers(self, api_key: str | None = None) -> dict[str, str]:
        key = api_key or self.api_key
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _models_to_try(self, requested_model: str | None = None) -> list[str]:
        ordered: list[str] = []
        candidates = [requested_model, self._active_model, self.default_model, *self.model_fallbacks]
        for c in candidates:
            if c and c not in ordered:
                ordered.append(c)
        return ordered

    def _handle_http_error(self, exc: Exception) -> None:
        if isinstance(exc, httpx.TimeoutException):
            raise ProviderTimeoutError(f"Groq request timed out: {exc}", provider=self.name)
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body = exc.response.text
            if code == 429:
                raise ProviderRateLimitError(f"Groq rate limit exceeded (429): {body}", provider=self.name, status_code=429)
            if code in (401, 403):
                raise ProviderAuthenticationError(f"Groq invalid credentials ({code}): {body}", provider=self.name, status_code=code)
            raise LLMProviderError(f"Groq API error ({code}): {body}", provider=self.name, status_code=code)
        if isinstance(exc, httpx.RequestError):
            raise ProviderUnavailableError(f"Groq connection error: {exc}", provider=self.name)
        raise LLMProviderError(f"Unexpected Groq error: {exc}", provider=self.name)

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
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        content, _ = await self.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            **kwargs,
        )
        return (content or "").strip()

    async def _chat_slot(
        self,
        slot: APIKeySlot,
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
        last_error: Exception | None = None

        for target_model in self._models_to_try(model):
            payload: dict[str, Any] = {
                "model": target_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            if tools:
                payload["tools"] = tools
                if tool_choice:
                    payload["tool_choice"] = tool_choice

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        GROQ_CHAT_URL,
                        headers=self._get_headers(slot.api_key),
                        json=payload,
                    )
                    if resp.status_code == 404 or (resp.status_code >= 400 and "model" in resp.text.lower()):
                        logger.warning("Groq model %s unavailable on %s, trying fallback", target_model, slot.label)
                        continue
                    resp.raise_for_status()
                    data = resp.json()

                self._active_model = target_model
                msg = data["choices"][0]["message"]
                content = (msg.get("content") or "").strip() if msg.get("content") else None
                tool_calls = msg.get("tool_calls")
                return content, tool_calls
            except Exception as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                    continue
                self._handle_http_error(exc)
                raise

        if last_error:
            self._handle_http_error(last_error)
        raise LLMProviderError("All Groq models failed", provider=self.name)

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
        return await self.key_pool.execute_with_key_failover(
            lambda slot: self._chat_slot(
                slot,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
                json_mode=json_mode,
                model=model,
                **kwargs,
            )
        )

    async def _vision_slot(
        self,
        slot: APIKeySlot,
        prompt: str,
        image_bytes_or_b64: bytes | str,
        *,
        max_tokens: int = 1024,
        model: str | None = "llama-3.2-11b-vision-preview",
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> str:
        b64_data = self._encode_image_b64(image_bytes_or_b64)
        image_url = f"data:{mime_type};base64,{b64_data}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]

        payload = {
            "model": model or "llama-3.2-11b-vision-preview",
            "messages": messages,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    GROQ_CHAT_URL,
                    headers=self._get_headers(slot.api_key),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            content = (data["choices"][0]["message"].get("content") or "").strip()
            return content
        except Exception as exc:
            self._handle_http_error(exc)
            raise

    async def vision(
        self,
        prompt: str,
        image_bytes_or_b64: bytes | str,
        *,
        max_tokens: int = 1024,
        model: str | None = "llama-3.2-11b-vision-preview",
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> str:
        self.check_readiness()
        return await self.key_pool.execute_with_key_failover(
            lambda slot: self._vision_slot(
                slot,
                prompt,
                image_bytes_or_b64,
                max_tokens=max_tokens,
                model=model,
                mime_type=mime_type,
                **kwargs,
            )
        )

    async def health_check(self) -> bool:
        if not self.is_enabled:
            return False
        try:
            reply = await self.generate("Reply with exactly: OK", max_tokens=16)
            return bool(reply) and len(reply) < 100
        except Exception as exc:
            logger.warning("Groq health check failed: %s", exc)
            return False
