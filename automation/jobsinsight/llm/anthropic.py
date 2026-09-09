"""Provider for the Anthropic Messages API."""

from __future__ import annotations

from typing import Any

from .base import ChatMessage, LLMProvider, LLMRequest, LLMResponse, LLMTransportError, Usage
from .transport import JsonTransport, post_json

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_API_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        api_version: str = DEFAULT_API_VERSION,
        extra_headers: dict[str, str] | None = None,
        transport: JsonTransport = post_json,
    ) -> None:
        super().__init__(model=model, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version
        self.extra_headers = dict(extra_headers or {})
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/messages"

    def _headers(self) -> dict[str, str]:
        headers = {"anthropic-version": self.api_version, **self.extra_headers}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @staticmethod
    def _split_system(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
        system_parts = [m.content for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        return "\n\n".join(system_parts), rest

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        system_prompt, conversation = self._split_system(list(request.messages))
        if request.json_mode:
            system_prompt = (system_prompt + "\n\n只输出一个合法的 JSON 对象，不要包含解释或代码块标记。").strip()

        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": m.role, "content": m.content} for m in conversation],
        }
        if system_prompt:
            payload["system"] = system_prompt
        if request.stop:
            payload["stop_sequences"] = list(request.stop)
        payload.update(request.extra_body)
        return payload

    def complete(self, request: LLMRequest) -> LLMResponse:
        data = self._transport(self.endpoint, self._headers(), self._payload(request), self.timeout)

        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise LLMTransportError(f"no content in response: {str(data)[:400]}", retryable=False)
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage_data = data.get("usage") or {}

        return LLMResponse(
            text=text,
            model=str(data.get("model") or request.model or self.model),
            usage=Usage(
                prompt_tokens=int(usage_data.get("input_tokens") or 0),
                completion_tokens=int(usage_data.get("output_tokens") or 0),
            ),
            finish_reason=data.get("stop_reason"),
            raw=data,
        )

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "base_url": self.base_url, "authenticated": bool(self.api_key)}
