"""Cloudflare Workers AI provider implementation for ARU AI V4."""

from __future__ import annotations

import time
import httpx

from aru.brain.exceptions import ProviderError
from aru.brain.models import LLMMessage, LLMResponse, TokenUsage
from aru.brain.providers.base import BaseLLMProvider


class CloudflareProvider(BaseLLMProvider):
    """Cloudflare Workers AI chat provider with multi-account rotation."""

    def __init__(
        self,
        accounts: list[dict[str, str]] | None = None,
        default_model: str = "@cf/meta/llama-3.1-8b-instruct",
        default_timeout: float = 30.0,
    ) -> None:
        self._accounts = accounts or []
        self._account_index = 0
        api_keys = [a.get("api_key", "") for a in self._accounts if a.get("api_key")]
        super().__init__(
            name="cloudflare",
            api_keys=api_keys,
            default_model=default_model,
            default_timeout=default_timeout,
        )

    @property
    def is_available(self) -> bool:
        return len(self._accounts) > 0 and bool(self._accounts[0].get("account_id"))

    def _get_current_account(self) -> dict[str, str]:
        if not self._accounts:
            return {}
        return self._accounts[self._account_index % len(self._accounts)]

    def _rotate_account(self) -> dict[str, str]:
        if len(self._accounts) > 1:
            self._account_index = (self._account_index + 1) % len(self._accounts)
        return self._get_current_account()

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Call Cloudflare Workers AI chat completions endpoint."""
        account = self._get_current_account()
        acc_id = account.get("account_id")
        api_key = account.get("api_key")

        if not acc_id or not api_key:
            raise ProviderError(self._name, "No valid account_id/api_key for Cloudflare.")

        selected_model = model or self._default_model
        endpoint = f"https://api.cloudflare.com/client/v4/accounts/{acc_id}/ai/v1/chat/completions"

        payload = {
            "model": selected_model,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        client = await self.get_client()
        start = time.perf_counter()
        req_timeout = timeout or self._default_timeout

        try:
            resp = await client.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=req_timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if resp.status_code != 200:
                self._rotate_account()
                self._handle_http_error(Exception(resp.text), status_code=resp.status_code, response_text=resp.text)

            data = resp.json()
            # Cloudflare returns choices or result
            choice = data.get("choices", [{}])[0] if data.get("choices") else data.get("result", {})
            msg_content = choice.get("message", {}).get("content", "") or choice.get("response", "")
            finish_reason = choice.get("finish_reason", "stop")

            usage_data = data.get("usage", {})
            token_usage = TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            return LLMResponse(
                content=msg_content,
                model=data.get("model", selected_model),
                provider=self._name,
                token_usage=token_usage,
                finish_reason=finish_reason,
                latency_ms=elapsed_ms,
                raw_response=data,
            )
        except httpx.HTTPError as err:
            self._rotate_account()
            self._handle_http_error(err)
            raise
