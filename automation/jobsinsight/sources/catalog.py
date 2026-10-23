"""Read source and query catalogs shipped in automation/config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..career.yaml_lite import loads


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def enabled_sites(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    sources = catalog.get("sources") if isinstance(catalog.get("sources"), dict) else {}
    sites: list[dict[str, Any]] = []
    for name, body in sources.items():
        if name == "search" or not isinstance(body, dict) or body.get("enabled") is False:
            continue
        modes = body.get("mode") or []
        if isinstance(modes, str):
            modes = [modes]
        if "search_discovery" not in modes and modes:
            continue
        domains = body.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        sites.append(
            {
                "name": name,
                "domains": [str(item) for item in domains],
                "rate_limit_per_minute": int(body.get("rate_limit_per_minute") or 10),
            }
        )
    return sites


def build_search_queries(
    catalog: dict[str, Any],
    *,
    domains: list[str],
    max_queries: int,
    focus_index: int = 0,
) -> list[str]:
    """Stay inside ``max_queries``. When the cap is at least 2, the last slot is one focus term.

    The term rotates with ``focus_index`` (the caller passes the day number) so
    the CADD phrases and the other ``focus_keywords`` are searched across days
    without adding a request.
    """

    keywords = [str(item) for item in catalog.get("keywords") or []]
    cities = [str(item) for item in catalog.get("cities") or []] or [""]
    focus = [str(item) for item in catalog.get("focus_keywords") or []]
    primary = _expand(keywords, cities, domains)
    cap = max(0, max_queries)
    if cap == 0:
        return []
    if cap == 1 or not focus:
        return primary[:cap]
    focus_queries = _expand([focus[focus_index % len(focus)]], cities[:1], domains)
    head = [query for query in primary if query not in focus_queries][: cap - 1]
    chosen = next((query for query in focus_queries if query not in head), None)
    if chosen is None:
        return primary[:cap]
    return [*head, chosen]


def _expand(keywords: list[str], cities: list[str], domains: list[str]) -> list[str]:
    queries: list[str] = []
    for keyword in keywords:
        for city in cities:
            for domain in domains:
                text = " ".join(part for part in (f"site:{domain}", city, keyword) if part)
                queries.append(text)
    return queries
