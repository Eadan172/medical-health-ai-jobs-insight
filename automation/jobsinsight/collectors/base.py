"""Collector interface and registry."""

from __future__ import annotations

import abc
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import SourceSettings
from ..models import RawPosting

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..llm import LLMClient


class CollectorError(RuntimeError):
    """A source could not be collected. Other sources keep going."""


@dataclass
class CollectorContext:
    """Everything a collector may need from the surrounding run."""

    project_root: Path = field(default_factory=Path.cwd)
    llm: LLMClient | None = None


class Collector(abc.ABC):
    """Fetches raw postings from one source.

    Collectors deliberately do no normalisation: parsing salaries, skills and
    seniority is the enricher's job (heuristics, or the LLM).
    """

    type: str = "base"

    def __init__(self, settings: SourceSettings, context: CollectorContext | None = None) -> None:
        self.settings = settings
        self.context = context or CollectorContext()

    @abc.abstractmethod
    def collect(self) -> Iterable[RawPosting]:
        """Yield raw postings, at most ``settings.limit`` of them."""

    def resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.context.project_root / path

    def describe(self) -> dict[str, object]:
        return {"name": self.settings.name, "type": self.type, "platform": self.settings.platform}


CollectorFactory = Callable[[SourceSettings, CollectorContext], Collector]

_REGISTRY: dict[str, CollectorFactory] = {}


def register_collector(type_name: str, factory: CollectorFactory) -> None:
    """Register a custom source type so ``sources[].type`` accepts it."""

    _REGISTRY[type_name.lower()] = factory


def available_collectors() -> list[str]:
    return sorted(_REGISTRY)


def build_collector(settings: SourceSettings, context: CollectorContext | None = None) -> Collector:
    factory = _REGISTRY.get(settings.type.lower())
    if factory is None:
        raise CollectorError(
            f"unknown source type {settings.type!r} for source {settings.name!r}; "
            f"available: {', '.join(available_collectors())}"
        )
    return factory(settings, context or CollectorContext())
