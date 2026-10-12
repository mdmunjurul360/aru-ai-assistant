"""Google Gemini LLM Provider implementation using async HTTP API with multi-key pool support."""

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

logger = logging.getLogger("aru.llm.gemini")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-3.5-flash",
)


class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini API provider (Gemini 2.5 Flash / 3.5 Flash).
    Async communication via HTTPX with KeyPool failover, error mapping, and circuit breaker support.
    """

    def __init__(
        self,
        api_key: str = "",
        api_keys: list[str] | None = None,
        default_model: str = "gemini-2.5-flash",
        timeout: float = 30.0,
        model_fallbacks: tuple[str, ...] = GEMINI_MODELS,
    ) -> None:
        super().__init__(
            name="gemini",
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

    def _models_to_try(self, model: str | None = None) -> list[str]:
        target = model or self._active_model or self.default_model
        ordered = [target]
        for m in getattr(self, "model_fallbacks", GEMINI_MODELS):
            if m not in ordered:
                ordered.append(m)
        return ordered

    def _get_url(self, model: str | None = None, api_key: str | None = None) -> str:
        target_model = model or self._active_model or self.default_model
        key = api_key or self.api_key
        return f"{GEMINI_API_BASE}/{target_model}:generateContent?key={key}"

    def _handle_http_error(self, exc: Exception) -> None:
        if isinstance(exc, httpx.TimeoutException):
            raise ProviderTimeoutError(f"Gemini request timed out: {exc}", provider=self.name)
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body = exc.response.text
            if code == 429:
                raise ProviderRateLimitError(f"Gemini quota/rate limit exceeded (429): {body}", provider=self.name, status_code=429)
            if code in (401, 403):
                raise ProviderAuthenticationError(f"Gemini invalid credentials ({code}): {body}", provider=self.name, status_code=code)
            raise LLMProviderError(f"Gemini API error ({code}): {body}", provider=self.name, status_code=code)
        if isinstance(exc, httpx.RequestError):
            raise ProviderUnavailableError(f"Gemini network connection error: {exc}", provider=self.name)
        raise LLMProviderError(f"Unexpected Gemini error: {exc}", provider=self.name)

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
        models = self._models_to_try(model)

        gen_config: dict[str, Any] = {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        }
        thinking_budget = kwargs.get("thinking_budget", 0)
        if thinking_budget is not None:
            gen_config["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}

        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        last_exc: Exception | None = None
        for m in models:
            url = self._get_url(m, api_key=slot.api_key)
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                candidates = data.get("candidates") or []
                if not candidates:
                    raise LLMProviderError("Gemini returned empty candidates", provider=self.name)

                parts = candidates[0].get("content", {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
                self._active_model = m
                return text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("Gemini model '%s' not found (404); trying fallback", m)
                    last_exc = exc
                    continue
                self._handle_http_error(exc)
                raise
            except Exception as exc:
                self._handle_http_error(exc)
                raise

        if last_exc:
            self._handle_http_error(last_exc)
        raise LLMProviderError("All Gemini models failed", provider=self.name)

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
        models = self._models_to_try(model)

        system_parts: list[str] = []
        gemini_contents: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(str(content))
            elif role == "assistant":
                gemini_contents.append({"role": "model", "parts": [{"text": str(content)}]})
            else:
                gemini_contents.append({"role": "user", "parts": [{"text": str(content)}]})

        if not gemini_contents:
            gemini_contents.append({"role": "user", "parts": [{"text": "Hello"}]})

        config: dict[str, Any] = {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            config["responseMimeType"] = "application/json"
        thinking_budget = kwargs.get("thinking_budget", 0)
        if thinking_budget is not None:
            config["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}

        payload: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": config,
        }
        if system_parts:
            payload["system_instruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

        last_exc: Exception | None = None
        for m in models:
            url = self._get_url(m, api_key=slot.api_key)
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                candidates = data.get("candidates") or []
                if not candidates:
                    return None, None

                content_obj = candidates[0].get("content") or {}
                parts = content_obj.get("parts") or []
                text = "".join(p.get("text", "") for p in parts if "text" in p).strip() or None

                # Tool calls conversion if any functionCall is present
                tool_calls = []
                for p in parts:
                    if "functionCall" in p:
                        fc = p["functionCall"]
                        tool_calls.append({
                            "id": f"call_{fc.get('name')}",
                            "type": "function",
                            "function": {
                                "name": fc.get("name"),
                                "arguments": fc.get("args") or {},
                            },
                        })

                self._active_model = m
                return text, (tool_calls if tool_calls else None)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("Gemini model '%s' not found (404); trying fallback", m)
                    last_exc = exc
                    continue
                self._handle_http_error(exc)
                raise
            except Exception as exc:
                self._handle_http_error(exc)
                raise

        if last_exc:
            self._handle_http_error(last_exc)
        raise LLMProviderError("All Gemini models failed", provider=self.name)

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
        model: str | None = None,
        mime_type: str = "image/jpeg",
        **kwargs: Any,
    ) -> str:
        models = self._models_to_try(model)
        b64_data = self._encode_image_b64(image_bytes_or_b64)

        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_data,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }

        last_exc: Exception | None = None
        for m in models:
            url = self._get_url(m, api_key=slot.api_key)
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                candidates = data.get("candidates") or []
                parts = candidates[0].get("content", {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
                self._active_model = m
                return text
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("Gemini model '%s' not found (404); trying fallback", m)
                    last_exc = exc
                    continue
                self._handle_http_error(exc)
                raise
            except Exception as exc:
                self._handle_http_error(exc)
                raise

        if last_exc:
            self._handle_http_error(last_exc)
        raise LLMProviderError("All Gemini models failed", provider=self.name)

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
            logger.warning("Gemini health check failed: %s", exc)
            return False
