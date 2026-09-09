"""Provider registry: turns configuration into a ready-to-use client."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .anthropic import AnthropicProvider
from .base import LLMConfigError, LLMProvider
from .client import LLMClient
from .mock import MockProvider
from .openai_compatible import KNOWN_BASE_URLS, OpenAICompatibleProvider

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import LLMSettings

ProviderFactory = Callable[[dict[str, Any]], LLMProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Add a custom provider so ``llm.provider = "<name>"`` starts working."""

    _REGISTRY[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def _openai_factory(alias: str) -> ProviderFactory:
    def factory(options: dict[str, Any]) -> LLMProvider:
        base_url = options.pop("base_url", None) or KNOWN_BASE_URLS[alias]
        return OpenAICompatibleProvider(base_url=base_url, **options)

    return factory


for _alias in KNOWN_BASE_URLS:
    register_provider(_alias, _openai_factory(_alias))
register_provider("openai_compatible", lambda options: OpenAICompatibleProvider(**options))
register_provider("anthropic", lambda options: AnthropicProvider(**options))
register_provider("claude", lambda options: AnthropicProvider(**options))
register_provider("mock", lambda options: MockProvider(**_only(options, {"model", "timeout"})))


def _only(options: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: value for key, value in options.items() if key in keys and value is not None}


def build_provider(settings: LLMSettings) -> LLMProvider:
    factory = _REGISTRY.get(settings.provider.lower())
    if factory is None:
        raise LLMConfigError(
            f"unknown LLM provider {settings.provider!r}; available: {', '.join(available_providers())}"
        )

    options: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "timeout": settings.timeout_seconds,
        "extra_headers": dict(settings.extra_headers),
    }
    if settings.base_url:
        options["base_url"] = settings.base_url
    if settings.provider.lower() == "mock":
        options = {"model": settings.model, "timeout": settings.timeout_seconds}
    return factory(options)


def build_client(settings: LLMSettings) -> LLMClient:
    return LLMClient(
        build_provider(settings),
        max_retries=settings.max_retries,
        backoff_seconds=settings.backoff_seconds,
        min_interval_seconds=settings.min_interval_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
