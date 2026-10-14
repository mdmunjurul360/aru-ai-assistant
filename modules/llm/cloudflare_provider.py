"""Cloudflare Workers AI LLM Provider with KeyPool, model fallbacks, and vision support."""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger("aru.llm.cloudflare")

# OpenAI-compatible chat completions endpoint (account_id injected at runtime)
CLOUDFLARE_CHAT_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
)

# Native vision endpoint (for LLaVA and other multimodal models)
CLOUDFLARE_RUN_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
)

CLOUDFLARE_MODELS = (
    "@cf/meta/llama-3.1-8b-instruct",
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "@cf/meta/llama-3.1-70b-instruct",
    "@cf/qwen/qwen1.5-14b-chat-awq",
    "@cf/mistral/mistral-7b-instruct-v0.2",
)

CLOUDFLARE_VISION_MODEL = "@cf/llava-hf/llava-1.5-7b-hf"


class CloudflareProvider(BaseLLMProvider):
    """
    Cloudflare Workers AI provider with:
    - OpenAI-compatible chat completions API
    - Native multimodal vision via LLaVA
    - KeyPool multi-key failover
    - Internal model fallback chain
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | list[dict[str, str]] | None = None,
        account_id: str | None = None,
        accounts: list[dict[str, str]] | None = None,
        default_model: str = "@cf/meta/llama-3.1-8b-instruct",
        timeout: float = 30.0,
        model_fallbacks: tuple[str, ...] = CLOUDFLARE_MODELS,
    ) -> None:
        from modules.config import parse_cloudflare_credentials

        resolved_keys: list[Any] = []
        resolved_account_id = account_id.strip() if account_id is not None else ""

        if accounts is not None:
            resolved_keys = list(accounts)
            if not resolved_account_id and resolved_keys:
                resolved_account_id = resolved_keys[0].get("account_id", "")
        elif api_key is not None or api_keys is not None:
            raw_keys = list(api_keys) if api_keys is not None else ([api_key] if api_key else [])
            for item in raw_keys:
                if isinstance(item, dict):
                    resolved_keys.append(item)
                elif item and str(item).strip():
                    resolved_keys.append({"account_id": resolved_account_id, "api_key": str(item).strip()})
        elif account_id is not None:
            # Explicit account_id provided without keys -> disabled
            resolved_keys = []
        else:
            # No credentials supplied at all -> read from environment
            env_accounts = parse_cloudflare_credentials()
            if env_accounts:
                resolved_keys = env_accounts
                resolved_account_id = env_accounts[0].get("account_id", "")
            else:
                resolved_account_id = (os.getenv("CLOUDFLARE_ACCOUNT_ID", "")).strip()

        self.account_id = resolved_account_id
        self.model_fallbacks = model_fallbacks
        self._active_model = default_model
        super().__init__(
            name="cloudflare",
            api_keys=resolved_keys,
            default_model=default_model,
            timeout=timeout,
        )

    @property
    def is_enabled(self) -> bool:
        """Cloudflare requires both API key(s) and account_id to be usable."""
        if not self.key_pool.has_keys:
            return False
        return any(bool(s.api_key and (s.account_id or self.account_id)) for s in self.key_pool.slots)

    @property
    def active_model(self) -> str:
        return self._active_model

    @property
    def chat_url(self) -> str:
        acc = self.account_id
        if not acc and self.key_pool.slots:
            acc = self.key_pool.slots[0].account_id
        return CLOUDFLARE_CHAT_URL_TEMPLATE.format(account_id=acc)

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
            raise ProviderTimeoutError(f"Cloudflare request timed out: {exc}", provider=self.name)
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body = exc.response.text
            if code == 429:
                raise ProviderRateLimitError(
                    f"Cloudflare rate limit exceeded (429): {body}", provider=self.name, status_code=429
                )
            if code in (401, 403):
                raise ProviderAuthenticationError(
                    f"Cloudflare invalid credentials ({code}): {body}", provider=self.name, status_code=code
                )
            raise LLMProviderError(f"Cloudflare API error ({code}): {body}", provider=self.name, status_code=code)
        if isinstance(exc, httpx.RequestError):
            raise ProviderUnavailableError(f"Cloudflare connection error: {exc}", provider=self.name)
        raise LLMProviderError(f"Unexpected Cloudflare error: {exc}", provider=self.name)

    # --- generate() ---

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

    # --- chat() with model fallback ---

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

        target_account = (slot.account_id or self.account_id).strip()
        if not target_account:
            raise ProviderAuthenticationError(
                f"Missing Cloudflare Account ID for {slot.label}",
                provider=self.name,
            )
        chat_url = CLOUDFLARE_CHAT_URL_TEMPLATE.format(account_id=target_account)

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
                        chat_url,
                        headers=self._get_headers(slot.api_key),
                        json=payload,
                    )
                    # Model not found → try next model
                    if resp.status_code == 404 or (
                        resp.status_code >= 400 and "model" in resp.text.lower()
                    ):
                        logger.warning(
                            "Cloudflare model %s unavailable on %s, trying fallback",
                            target_model,
                            slot.label,
                        )
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
        raise LLMProviderError("All Cloudflare models failed", provider=self.name)

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

    # --- vision() via native Workers AI endpoint ---

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
        vision_model = model or CLOUDFLARE_VISION_MODEL
        target_account = (slot.account_id or self.account_id).strip()
        if not target_account:
            raise ProviderAuthenticationError(
                f"Missing Cloudflare Account ID for {slot.label}",
                provider=self.name,
            )
        run_url = CLOUDFLARE_RUN_URL_TEMPLATE.format(
            account_id=target_account,
            model=vision_model,
        )

        # Convert image to base64 data URL for Cloudflare vision
        b64_data = self._encode_image_b64(image_bytes_or_b64)
        image_url = f"data:{mime_type};base64,{b64_data}"

        # Use OpenAI-compatible multimodal message format
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    run_url,
                    headers=self._get_headers(slot.api_key),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Cloudflare native /ai/run/ wraps result in {"result": {...}}
            result = data.get("result", data)
            if isinstance(result, dict):
                content = (result.get("response") or result.get("description") or "").strip()
            elif isinstance(result, str):
                content = result.strip()
            else:
                content = str(result)
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

    # --- health_check() ---

    async def health_check(self) -> bool:
        if not self.is_enabled:
            return False
        try:
            reply = await self.generate("Reply with exactly: OK", max_tokens=16)
            return bool(reply) and len(reply) < 100
        except Exception as exc:
            logger.warning("Cloudflare health check failed: %s", exc)
            return False
