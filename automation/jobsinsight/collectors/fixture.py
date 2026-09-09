"""Reads postings from a local JSON file.

This is the default source: it keeps the whole pipeline runnable (and testable)
without network access, and it is also how you replay a saved crawl.

The file may contain either raw postings (``RawPosting`` fields) or already
normalised dashboard jobs — the latter are converted back to raw form so the
enricher still does its job.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from ..models import RawPosting
from .base import Collector, CollectorError, register_collector

DEFAULT_PATH = "automation/data/seed_postings.json"


class FixtureCollector(Collector):
    type = "fixture"

    def collect(self) -> Iterable[RawPosting]:
        path = self.resolve_path(self.settings.path or DEFAULT_PATH)
        if not path.is_file():
            raise CollectorError(f"fixture file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CollectorError(f"invalid JSON in {path}: {exc}") from exc

        if isinstance(data, Mapping):
            data = data.get("postings") or data.get("jobs") or []
        if not isinstance(data, list):
            raise CollectorError(f"{path} must contain a list of postings")

        postings: list[RawPosting] = []
        for index, entry in enumerate(data):
            if not isinstance(entry, Mapping):
                continue
            posting = _to_posting(entry, index, default_platform=self.settings.platform)
            if not _matches_filters(posting, self.settings.keywords, self.settings.cities):
                continue
            postings.append(posting)
            if self.settings.limit and len(postings) >= self.settings.limit:
                break
        return postings


def _to_posting(entry: Mapping[str, Any], index: int, *, default_platform: str = "") -> RawPosting:
    if "salary_text" in entry or "description" in entry:
        posting = RawPosting.from_dict(entry)
    else:  # a normalised dashboard job — rebuild the raw view of it
        salary_min = entry.get("salary_min") or 0
        salary_max = entry.get("salary_max") or salary_min
        skills = entry.get("skills") or []
        posting = RawPosting(
            source_id=str(entry.get("id") or index),
            platform=str(entry.get("platform") or default_platform),
            title=str(entry.get("title") or ""),
            company=str(entry.get("company") or ""),
            city=str(entry.get("city") or ""),
            url=str(entry.get("url") or ""),
            salary_text=f"{salary_min}-{salary_max}K" if salary_max else "",
            experience_text=str(entry.get("experience") or ""),
            education_text=str(entry.get("education") or ""),
            company_scale=str(entry.get("company_scale") or ""),
            company_level=str(entry.get("company_level") or ""),
            description=" ".join(filter(None, [str(entry.get("summary") or ""), "、".join(map(str, skills))])),
            publish_date=str(entry.get("publish_date") or ""),
        )
    if not posting.source_id:
        posting.source_id = str(index)
    if not posting.platform:
        posting.platform = default_platform or "未知平台"
    return posting


def _matches_filters(posting: RawPosting, keywords: list[str], cities: list[str]) -> bool:
    if cities and posting.city and posting.city not in cities:
        return False
    if keywords:
        haystack = f"{posting.title} {posting.description}".lower()
        return any(keyword.lower() in haystack for keyword in keywords)
    return True


register_collector("fixture", FixtureCollector)
register_collector("local", FixtureCollector)
