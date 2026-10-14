"""DeepSeek API provider implementation for ARU AI V4."""

from __future__ import annotations

import time
import httpx

from aru.brain.exceptions import ProviderError
from aru.brain.models import LLMMessage, LLMResponse, TokenUsage
from aru.brain.providers.base import BaseLLMProvider


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek chat provider (deepseek-chat, deepseek-coder)."""

    ENDPOINT = "https://api.deepseek.com/chat/completions"

    def __init__(
        self,
        api_keys: list[str] | None = None,
        default_model: str = "deepseek-chat",
        default_timeout: float = 45.0,
    ) -> None:
        super().__init__(
            name="deepseek",
            api_keys=api_keys,
            default_model=default_model,
            default_timeout=default_timeout,
        )

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Call DeepSeek chat completions endpoint."""
        key = self._get_current_key()
        if not key:
            raise ProviderError(self._name, "No API key configured for DeepSeek.")

        selected_model = model or self._default_model
        payload = {
            "model": selected_model,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        client = await self.get_client()
        start = time.perf_counter()
        req_timeout = timeout or self._default_timeout

        try:
            resp = await client.post(
                self.ENDPOINT,
                json=payload,
                headers=headers,
                timeout=req_timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if resp.status_code != 200:
                self._handle_http_error(Exception(resp.text), status_code=resp.status_code, response_text=resp.text)

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            msg_content = choice.get("message", {}).get("content", "")
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
            self._handle_http_error(err)
            raise
