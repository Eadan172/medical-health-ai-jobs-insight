"""The interface the rest of the automation calls: retries, JSON mode, metrics."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .base import (
    ChatMessage,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTransportError,
    Usage,
)
from .json_utils import extract_json

LOGGER = logging.getLogger(__name__)

Validator = Callable[[Any], Any]


@dataclass
class LLMMetrics:
    """Per-run accounting, surfaced in the run report and the HTTP API."""

    calls: int = 0
    failures: int = 0
    retries: int = 0
    usage: Usage = field(default_factory=Usage)
    latency_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "retries": self.retries,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "total_tokens": self.usage.total_tokens,
            "latency_seconds": round(self.latency_seconds, 3),
        }


class LLMClient:
    """Wraps a provider with the behaviour every caller needs.

    * exponential backoff with jitter for retryable transport errors
    * optional rate limiting between calls
    * ``complete_json`` for structured extraction, including one repair attempt
      when the model returns prose instead of JSON
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
        max_backoff_seconds: float = 30.0,
        min_interval_seconds: float = 0.0,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.metrics = LLMMetrics()
        self._sleep = sleep
        self._clock = clock
        self._last_call_at: float | None = None

    # ------------------------------------------------------------------ text

    def complete(
        self,
        messages: Sequence[ChatMessage] | str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        request = LLMRequest(
            messages=_coerce_messages(messages),
            model=model,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            json_mode=json_mode,
            extra_body=dict(extra_body or {}),
        )
        return self._call_with_retries(request)

    # ------------------------------------------------------------------ json

    def complete_json(
        self,
        messages: Sequence[ChatMessage] | str,
        *,
        validator: Validator | None = None,
        repair: bool = True,
        **kwargs: Any,
    ) -> Any:
        kwargs.setdefault("json_mode", True)
        response = self.complete(messages, **kwargs)
        try:
            return _parse_and_validate(response.text, validator)
        except (ValueError, LLMResponseError) as exc:
            if not repair:
                raise LLMResponseError(str(exc)) from exc

        LOGGER.warning("model returned unusable JSON, asking for a repair")
        self.metrics.retries += 1
        repair_messages = [
            *_coerce_messages(messages),
            ChatMessage("assistant", response.text[:2000]),
            ChatMessage("user", "上一次输出不是合法 JSON。请只输出一个合法的 JSON 对象，不要任何解释。"),
        ]
        repaired = self.complete(repair_messages, **kwargs)
        try:
            return _parse_and_validate(repaired.text, validator)
        except ValueError as exc:
            raise LLMResponseError(str(exc)) from exc

    def task_json(self, *, task: str, payload: Any, instructions: str, **kwargs: Any) -> Any:
        """Structured call convention used by the pipeline.

        The ``#task:<name>`` marker keeps prompts self-describing (useful in
        logs) and lets the offline mock provider pick the right canned reply.
        """

        import json

        messages = [
            ChatMessage("system", instructions),
            ChatMessage(
                "user",
                f"#task:{task}\n\n输入数据(JSON):\n{json.dumps(payload, ensure_ascii=False, indent=2)}",
            ),
        ]
        return self.complete_json(messages, **kwargs)

    # --------------------------------------------------------------- internal

    def _call_with_retries(self, request: LLMRequest) -> LLMResponse:
        attempt = 0
        while True:
            self._respect_rate_limit()
            started = self._clock()
            try:
                response = self.provider.complete(request)
            except LLMTransportError as exc:
                self.metrics.latency_seconds += self._clock() - started
                if not exc.retryable or attempt >= self.max_retries:
                    self.metrics.failures += 1
                    raise
                delay = min(self.max_backoff_seconds, self.backoff_seconds * (2**attempt))
                delay *= 0.5 + random.random()  # noqa: S311 - jitter only
                LOGGER.warning("LLM call failed (%s), retrying in %.1fs", exc, delay)
                self.metrics.retries += 1
                attempt += 1
                self._sleep(delay)
                continue
            except LLMError:
                self.metrics.latency_seconds += self._clock() - started
                self.metrics.failures += 1
                raise

            self.metrics.calls += 1
            self.metrics.usage = self.metrics.usage + response.usage
            self.metrics.latency_seconds += self._clock() - started
            return response

    def _respect_rate_limit(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        now = self._clock()
        if self._last_call_at is not None:
            wait = self.min_interval_seconds - (now - self._last_call_at)
            if wait > 0:
                self._sleep(wait)
        self._last_call_at = self._clock()

    def describe(self) -> dict[str, Any]:
        return {**self.provider.describe(), "max_retries": self.max_retries}


def _coerce_messages(messages: Sequence[ChatMessage] | str) -> list[ChatMessage]:
    if isinstance(messages, str):
        return [ChatMessage("user", messages)]
    return list(messages)


def _parse_and_validate(text: str, validator: Validator | None) -> Any:
    data = extract_json(text)
    return validator(data) if validator else data


def iter_batches(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
