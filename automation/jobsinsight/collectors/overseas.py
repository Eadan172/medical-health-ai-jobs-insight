"""Collectors for public overseas boards: ATS JSON, Remote OK, and We Work Remotely."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..models import RawPosting
from ..sources.http_client import HttpClient
from ..sources.overseas import (
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    collect_ats_postings,
    collect_remoteok_postings,
    collect_wwr_postings,
)
from .base import Collector, CollectorError, register_collector

LOGGER = logging.getLogger(__name__)


class AtsCollector(Collector):
    """One company list, four public ATS hosts. A single board failure does not stop the rest."""

    type = "ats"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        path = self.resolve_path(str(options.get("config") or "automation/config/overseas_companies.yaml"))
        client = _client(self.settings.timeout_seconds)
        postings, failures = collect_ats_postings(
            path,
            client,
            limit=self.settings.limit,
            per_company_limit=int(options.get("per_company_limit", 3)),
            delay_seconds=float(options.get("delay_seconds", 1.0)),
        )
        for failure in failures:
            LOGGER.warning("来源 %s：%s", self.settings.name, failure)
        if not postings and failures:
            raise CollectorError(f"来源 {self.settings.name} 失败：{'; '.join(failures[:8])}")
        return postings


class RemoteOkCollector(Collector):
    type = "remoteok"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        try:
            return collect_remoteok_postings(
                _client(self.settings.timeout_seconds),
                limit=self.settings.limit,
                delay_seconds=float(options.get("delay_seconds", 0.5)),
            )
        except RuntimeError as exc:
            raise CollectorError(f"来源 {self.settings.name} 失败：{exc}") from exc


class WwrCollector(Collector):
    type = "wwr"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        try:
            return collect_wwr_postings(
                _client(self.settings.timeout_seconds),
                limit=self.settings.limit,
                delay_seconds=float(options.get("delay_seconds", 0.5)),
            )
        except RuntimeError as exc:
            raise CollectorError(f"来源 {self.settings.name} 失败：{exc}") from exc


def _client(timeout: float) -> HttpClient:
    return HttpClient(timeout=timeout, max_bytes=MAX_RESPONSE_BYTES, user_agent=USER_AGENT)


register_collector("ats", AtsCollector)
register_collector("remoteok", RemoteOkCollector)
register_collector("wwr", WwrCollector)
