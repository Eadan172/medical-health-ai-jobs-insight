"""统一的 LLM 调用接口。

支持任何兼容 OpenAI ``/chat/completions`` 协议的服务（OpenAI、DeepSeek、
Kimi/Moonshot、通义千问、智谱、SiliconFlow、Groq、Ollama、vLLM……）、
Anthropic Messages API，以及用于离线运行的 ``mock`` provider。
自定义 provider 可以通过 :func:`register_provider` 注册。
"""

from .base import (
    ChatMessage,
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTransportError,
    Usage,
)
from .client import LLMClient, LLMMetrics, iter_batches
from .json_utils import extract_json
from .mock import MockProvider
from .registry import available_providers, build_client, build_provider, register_provider

__all__ = [
    "ChatMessage",
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMMetrics",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseError",
    "LLMTransportError",
    "MockProvider",
    "Usage",
    "available_providers",
    "build_client",
    "build_provider",
    "extract_json",
    "iter_batches",
    "register_provider",
]
