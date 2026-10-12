"""DeepSeek LLM Provider implementation using async HTTP API with KeyPool support."""

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

logger = logging.getLogger("aru.llm.deepseek")

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"

DEEPSEEK_MODELS = (
    "deepseek-flash",
    "deepseek-v4-pro",
)


class DeepSeekProvider(BaseLLMProvider):
    """
    DeepSeek API provider (deepseek-flash, deepseek-v4-pro).
    High efficiency reasoning and general intelligence via async HTTP with KeyPool failover.
    """

    def __init__(
        self,
        api_key: str = "",
        api_keys: list[str] | None = None,
        default_model: str = "deepseek-flash",
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            name="deepseek",
            api_key=api_key,
            api_keys=api_keys,
            default_model=default_model,
            timeout=timeout,
        )

    def _get_headers(self, api_key: str | None = None) -> dict[str, str]:
        key = api_key or self.api_key
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _handle_http_error(self, exc: Exception) -> None:
        if isinstance(exc, httpx.TimeoutException):
            raise ProviderTimeoutError(f"DeepSeek request timed out: {exc}", provider=self.name)
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body = exc.response.text
            if code == 429:
                raise ProviderRateLimitError(f"DeepSeek rate limit exceeded (429): {body}", provider=self.name, status_code=429)
            if code == 402:
                raise ProviderRateLimitError(f"DeepSeek insufficient balance (402): {body}", provider=self.name, status_code=402)
            if code in (401, 403):
                raise ProviderAuthenticationError(f"DeepSeek invalid credentials ({code}): {body}", provider=self.name, status_code=code)
            raise LLMProviderError(f"DeepSeek API error ({code}): {body}", provider=self.name, status_code=code)
        if isinstance(exc, httpx.RequestError):
            raise ProviderUnavailableError(f"DeepSeek connection error: {exc}", provider=self.name)
        raise LLMProviderError(f"Unexpected DeepSeek error: {exc}", provider=self.name)

    async def _generate_slot(
        self,
        slot: APIKeySlot,
        prompt: str,
        *,
        system_prompt: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        effective_model = self.default_model if (not model or model == "deepseek-chat") else model
        payload = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    DEEPSEEK_CHAT_URL,
                    headers=self._get_headers(slot.api_key),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            choice = data["choices"][0]["message"]
            text = (choice.get("content") or "").strip()
            return text
        except Exception as exc:
            self._handle_http_error(exc)
            raise

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
        return await self.key_pool.execute_with_key_failover(
            lambda slot: self._generate_slot(
                slot,
                prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                **kwargs,
            )
        )

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
        effective_model = self.default_model if (not model or model == "deepseek-chat") else model
        payload: dict[str, Any] = {
            "model": effective_model,
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
                    DEEPSEEK_CHAT_URL,
                    headers=self._get_headers(slot.api_key),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip() if msg.get("content") else None
            tool_calls = msg.get("tool_calls")
            return content, tool_calls
        except Exception as exc:
            self._handle_http_error(exc)
            raise

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
        return await self.generate(
            f"[Image attachment: {mime_type}] {prompt}",
            max_tokens=max_tokens,
            model=model,
        )

    async def health_check(self) -> bool:
        if not self.is_enabled:
            return False
        try:
            reply = await self.generate("Reply with exactly: OK", max_tokens=16)
            return bool(reply) and len(reply) < 100
        except Exception as exc:
            logger.warning("DeepSeek health check failed: %s", exc)
            return False
