"""Provider-agnostic LLM types and the interface every provider implements."""

from __future__ import annotations

import abc
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """Base class for every failure raised by the LLM layer."""


class LLMConfigError(LLMError):
    """The provider cannot be built from the supplied configuration."""


class LLMTransportError(LLMError):
    """The provider could not be reached, or replied with an unusable payload."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class LLMResponseError(LLMError):
    """The provider replied, but the content did not satisfy the request."""


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class LLMRequest:
    messages: Sequence[ChatMessage]
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 2048
    json_mode: bool = False
    stop: Sequence[str] = ()
    extra_body: Mapping[str, Any] = field(default_factory=dict)

    def with_messages(self, messages: Iterable[ChatMessage]) -> LLMRequest:
        return LLMRequest(
            messages=list(messages),
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            json_mode=self.json_mode,
            stop=self.stop,
            extra_body=self.extra_body,
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    usage: Usage = Usage()
    finish_reason: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Minimal surface a provider must expose to plug into the automation.

    Providers are synchronous and stateless: retries, timeouts and JSON
    coercion live in :class:`jobsinsight.llm.client.LLMClient` so that every
    provider benefits from them without re-implementing the logic.
    """

    #: Stable identifier used in configuration files (``llm.provider``).
    name: str = "base"

    def __init__(self, *, model: str, timeout: float = 60.0) -> None:
        self.model = model
        self.timeout = timeout

    @abc.abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one chat completion and return the assistant message."""

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "timeout": self.timeout}
