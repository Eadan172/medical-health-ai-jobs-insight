"""Collector that discovers public job URLs without opening a browser.

Direct site APIs that answer with a challenge are recorded and skipped.
Search results are not treated as complete jobs unless a public page confirms them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ..models import RawPosting
from ..sources.catalog import build_search_queries, enabled_sites, load_catalog
from ..sources.discovery import discover_site
from ..sources.health import save_health
from ..sources.http_client import HttpClient
from ..sources.search_provider import ChainedSearch, provider_chain
from .base import Collector, CollectorError, register_collector


class SearchDiscoveryCollector(Collector):
    type = "search_discovery"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        root = self.context.project_root
        sources_path = root / str(options.get("config") or "automation/config/sources.yaml")
        queries_path = root / str(options.get("queries") or "automation/config/job_queries.yaml")
        max_queries = int(options.get("max_queries") or 6)
        detail_limit = int(options.get("detail_limit") or 6)
        catalog = load_catalog(Path(sources_path))
        query_catalog = load_catalog(Path(queries_path))
        client = HttpClient(timeout=self.settings.timeout_seconds)
        provider = ChainedSearch(provider_chain(client), sleep=client._sleep)
        state_dir = root / "automation" / "state"
        reports = []
        postings: list[RawPosting] = []
        self.source_note = ""
        for site in enabled_sites(catalog):
            queries = build_search_queries(
                query_catalog,
                domains=site["domains"],
                max_queries=max_queries,
                focus_index=datetime.now(UTC).toordinal(),
            )
            report = discover_site(
                source=site["name"],
                domains=site["domains"],
                queries=queries,
                provider=provider,
                client=client,
                limit=min(self.settings.limit or 20, 20),
                detail_limit=detail_limit,
                per_minute=site["rate_limit_per_minute"],
            )
            reports.append(report.as_dict())
            postings.extend(report.jobs)
            if self.settings.limit and len(postings) >= self.settings.limit:
                break
        if reports:
            save_health(state_dir, reports)
        failed = [format_site_failure(item) for item in reports if not int(item.get("valid") or 0)]
        if postings and failed:
            self.source_note = "部分平台没有可发布岗位：" + "；".join(failed)
        if not postings:
            detail = "；".join(format_site_failure(item) for item in reports) or "no sites configured"
            raise CollectorError(f"公开搜索未得到可发布岗位（{detail}）")
        return postings[: self.settings.limit] if self.settings.limit else postings


def format_site_failure(item: dict[str, object]) -> str:
    """One platform's status plus the reason, for the mailed source line."""

    status = str(item.get("status") or "unavailable")
    error = str(item.get("last_error") or "").strip()
    text = f"{item.get('source')}={status}"
    if error:
        text += f": {error}"
    return text


register_collector("search_discovery", SearchDiscoveryCollector)
