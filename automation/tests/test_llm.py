from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from jobsinsight.config import LLMSettings
from jobsinsight.llm import (
    ChatMessage,
    LLMClient,
    LLMConfigError,
    LLMRequest,
    LLMResponseError,
    LLMTransportError,
    MockProvider,
    available_providers,
    build_client,
    extract_json,
    register_provider,
)
from jobsinsight.llm.anthropic import AnthropicProvider
from jobsinsight.llm.openai_compatible import OpenAICompatibleProvider
from jobsinsight.llm.registry import build_provider


class RecordingTransport:
    """Stands in for the network: records calls, replays queued replies."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float) -> dict:
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload), "timeout": timeout})
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        return reply


def openai_reply(text: str) -> dict[str, Any]:
    return {
        "model": "gpt-test",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


# ------------------------------------------------------------------- providers


def test_openai_provider_builds_the_expected_request():
    transport = RecordingTransport(openai_reply("你好"))
    provider = OpenAICompatibleProvider(
        model="gpt-test", api_key="sk-123", base_url="https://example.com/v1/", transport=transport
    )

    response = provider.complete(
        LLMRequest(messages=[ChatMessage("system", "s"), ChatMessage("user", "u")], json_mode=True, max_tokens=64)
    )

    call = transport.calls[0]
    assert call["url"] == "https://example.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-123"
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert response.text == "你好"
    assert response.usage.total_tokens == 18


def test_openai_provider_rejects_a_response_without_choices():
    provider = OpenAICompatibleProvider(model="m", transport=RecordingTransport({"error": "nope"}))
    with pytest.raises(LLMTransportError):
        provider.complete(LLMRequest(messages=[ChatMessage("user", "hi")]))


def test_anthropic_provider_moves_system_prompt_out_of_messages():
    transport = RecordingTransport(
        {
            "model": "claude-test",
            "content": [{"type": "text", "text": "答案"}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
            "stop_reason": "end_turn",
        }
    )
    provider = AnthropicProvider(model="claude-test", api_key="key", transport=transport)

    response = provider.complete(
        LLMRequest(messages=[ChatMessage("system", "规则"), ChatMessage("user", "问题")], json_mode=True)
    )

    payload = transport.calls[0]["payload"]
    assert payload["system"].startswith("规则")
    assert payload["messages"] == [{"role": "user", "content": "问题"}]
    assert transport.calls[0]["headers"]["x-api-key"] == "key"
    assert response.text == "答案"
    assert response.usage.prompt_tokens == 5


# ---------------------------------------------------------------------- client


def test_client_retries_retryable_errors_then_succeeds():
    transport = RecordingTransport(
        LLMTransportError("429 rate limited", status=429, retryable=True),
        openai_reply("ok"),
    )
    client = LLMClient(
        OpenAICompatibleProvider(model="m", transport=transport), max_retries=2, sleep=lambda _seconds: None
    )

    assert client.complete("hi").text == "ok"
    assert client.metrics.calls == 1
    assert client.metrics.retries == 1


def test_client_does_not_retry_a_permanent_error():
    transport = RecordingTransport(LLMTransportError("400 bad request", status=400, retryable=False))
    client = LLMClient(
        OpenAICompatibleProvider(model="m", transport=transport), max_retries=3, sleep=lambda _seconds: None
    )

    with pytest.raises(LLMTransportError):
        client.complete("hi")
    assert len(transport.calls) == 1
    assert client.metrics.failures == 1


def test_client_gives_up_after_max_retries():
    transport = RecordingTransport(*[LLMTransportError("boom") for _ in range(5)])
    client = LLMClient(
        OpenAICompatibleProvider(model="m", transport=transport), max_retries=2, sleep=lambda _seconds: None
    )

    with pytest.raises(LLMTransportError):
        client.complete("hi")
    assert len(transport.calls) == 3  # 1 attempt + 2 retries


def test_complete_json_recovers_from_prose_wrapped_json():
    transport = RecordingTransport(openai_reply('这是结果：\n```json\n{"a": 1}\n```'))
    client = LLMClient(OpenAICompatibleProvider(model="m", transport=transport))
    assert client.complete_json("hi") == {"a": 1}


def test_complete_json_asks_for_a_repair_then_succeeds():
    transport = RecordingTransport(openai_reply("抱歉，我无法输出"), openai_reply('{"a": 2}'))
    client = LLMClient(OpenAICompatibleProvider(model="m", transport=transport), sleep=lambda _seconds: None)

    assert client.complete_json("hi") == {"a": 2}
    assert len(transport.calls) == 2
    assert "不是合法 JSON" in transport.calls[1]["payload"]["messages"][-1]["content"]


def test_complete_json_raises_when_the_repair_also_fails():
    transport = RecordingTransport(openai_reply("nope"), openai_reply("still nope"))
    client = LLMClient(OpenAICompatibleProvider(model="m", transport=transport), sleep=lambda _seconds: None)
    with pytest.raises(LLMResponseError):
        client.complete_json("hi")


def test_validator_rejection_triggers_a_repair():
    transport = RecordingTransport(openai_reply('{"results": "not a list"}'), openai_reply('{"results": []}'))
    client = LLMClient(OpenAICompatibleProvider(model="m", transport=transport), sleep=lambda _seconds: None)

    def validator(data: Any) -> Any:
        if not isinstance(data.get("results"), list):
            raise ValueError("results must be a list")
        return data

    assert client.complete_json("hi", validator=validator) == {"results": []}


def test_rate_limit_waits_between_calls():
    waits: list[float] = []
    ticks = [0.0, 0.0, 0.0, 0.0, 1.0]
    transport = RecordingTransport(openai_reply("a"), openai_reply("b"))
    client = LLMClient(
        OpenAICompatibleProvider(model="m", transport=transport),
        min_interval_seconds=5.0,
        sleep=waits.append,
        clock=lambda: ticks.pop(0) if ticks else 1.0,
    )

    client.complete("one")
    client.complete("two")
    assert waits and waits[0] == pytest.approx(4.0)


# ------------------------------------------------------------------- registry


def test_build_client_from_settings_uses_the_alias_base_url():
    provider = build_provider(LLMSettings(provider="deepseek", model="deepseek-chat", api_key="k"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.deepseek.com/v1"


def test_explicit_base_url_wins_over_the_alias():
    provider = build_provider(LLMSettings(provider="openai", model="m", base_url="http://localhost:1234/v1"))
    assert provider.base_url == "http://localhost:1234/v1"


def test_unknown_provider_is_reported_with_the_available_list():
    with pytest.raises(LLMConfigError) as excinfo:
        build_provider(LLMSettings(provider="does-not-exist", model="m"))
    assert "available" in str(excinfo.value)


def test_custom_provider_can_be_registered():
    register_provider("my-gateway", lambda options: MockProvider(model=options["model"]))
    assert "my-gateway" in available_providers()
    client = build_client(LLMSettings(provider="my-gateway", model="custom-1"))
    assert client.provider.model == "custom-1"


# ----------------------------------------------------------------------- mock


def test_mock_provider_replays_heuristics_for_a_known_task():
    client = LLMClient(MockProvider())
    result = client.task_json(
        task="enrich_jobs",
        payload={"postings": [{"source_id": "x", "title": "AI医学影像工程师", "salary_text": "30-40K"}]},
        instructions='见 schema: {"results": []}',
    )
    assert result["results"][0]["salary_min"] == 30
    assert result["results"][0]["source_id"] == "x"


def test_mock_provider_returns_an_empty_object_for_unknown_tasks():
    client = LLMClient(MockProvider())
    assert client.complete_json("#task:unknown\n{}") == {}


# ------------------------------------------------------------------ json utils


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('前言 {"a": "}"} 后记', {"a": "}"}),
        ("[1, 2]", [1, 2]),
        ('说明\n[{"a": 1}]', [{"a": 1}]),
    ],
)
def test_extract_json(text: str, expected: Any):
    assert extract_json(text) == expected


def test_extract_json_raises_without_a_payload():
    with pytest.raises(ValueError):
        extract_json("完全没有 JSON")
