"""Provider for every service that speaks the OpenAI ``/chat/completions`` shape.

That covers OpenAI, DeepSeek, Moonshot/Kimi, 通义千问 (DashScope compatible mode),
智谱 GLM, SiliconFlow, Groq, vLLM, Ollama and LM Studio. Users only change
``base_url`` and ``model`` in the config file.
"""

from __future__ import annotations

from typing import Any

from .base import LLMConfigError, LLMProvider, LLMRequest, LLMResponse, LLMTransportError, Usage
from .transport import JsonTransport, post_json

#: Convenience aliases so users can write ``provider = "deepseek"`` instead of a URL.
KNOWN_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str = "",
        base_url: str = KNOWN_BASE_URLS["openai"],
        timeout: float = 60.0,
        organization: str | None = None,
        extra_headers: dict[str, str] | None = None,
        transport: JsonTransport = post_json,
    ) -> None:
        super().__init__(model=model, timeout=timeout)
        if not base_url:
            raise LLMConfigError("base_url is required for an OpenAI-compatible provider")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.organization = organization
        self.extra_headers = dict(extra_headers or {})
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        return headers

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [message.as_dict() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(request.extra_body)
        return payload

    def complete(self, request: LLMRequest) -> LLMResponse:
        data = self._transport(self.endpoint, self._headers(), self._payload(request), self.timeout)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMTransportError(f"no choices in response: {str(data)[:400]}", retryable=False)
        message = choices[0].get("message") or {}
        text = message.get("content")
        if not isinstance(text, str):
            # Reasoning models occasionally return the answer in a sibling field.
            text = message.get("reasoning_content") or ""
        usage_data = data.get("usage") or {}

        return LLMResponse(
            text=text,
            model=str(data.get("model") or request.model or self.model),
            usage=Usage(
                prompt_tokens=int(usage_data.get("prompt_tokens") or 0),
                completion_tokens=int(usage_data.get("completion_tokens") or 0),
            ),
            finish_reason=choices[0].get("finish_reason"),
            raw=data,
        )

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "base_url": self.base_url, "authenticated": bool(self.api_key)}
