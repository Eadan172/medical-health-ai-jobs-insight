"""Generic JSON-endpoint collector.

The招聘平台 (51job / Boss直聘 / 猎聘) all expose JSON search endpoints, but the
exact URL, parameters and cookies differ per account and change over time, so
they are configuration rather than code:

.. code-block:: toml

    [[sources]]
    name = "51job"
    type = "json_api"
    platform = "51job"
    urls = ["https://we.51job.com/api/job/search-pc?keyword=AI+医疗&pageNum={page}"]
    headers = { Cookie = "${JOB51_COOKIE}", User-Agent = "Mozilla/5.0" }
    limit = 200

    [sources.options]
    items_path = "resultbody.job.items"
    pages = 3
    field_map = { title = "jobName", company = "companyName", city = "jobAreaString", salary_text = "provideSalaryString", url = "jobHref", publish_date = "issueDateString", description = "jobTags" }
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..models import RawPosting
from .base import Collector, CollectorError, register_collector

LOGGER = logging.getLogger(__name__)

DEFAULT_FIELD_MAP: dict[str, str] = {
    "source_id": "id",
    "title": "title",
    "company": "company",
    "city": "city",
    "url": "url",
    "salary_text": "salary",
    "experience_text": "experience",
    "education_text": "education",
    "description": "description",
    "publish_date": "publish_date",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class JsonApiCollector(Collector):
    type = "json_api"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        field_map: dict[str, str] = {**DEFAULT_FIELD_MAP, **(options.get("field_map") or {})}
        items_path: str = options.get("items_path", "")
        pages = max(1, int(options.get("pages", 1)))
        delay = float(options.get("delay_seconds", 1.0))

        if not self.settings.urls:
            raise CollectorError(f"source {self.settings.name!r} needs at least one url")

        postings: list[RawPosting] = []
        for template in self.settings.urls:
            for page in range(1, pages + 1):
                url = template.format(page=page, keyword=urllib.parse.quote(" ".join(self.settings.keywords)))
                payload = self._fetch(url)
                for item in _dig(payload, items_path):
                    if not isinstance(item, Mapping):
                        continue
                    postings.append(self._to_posting(item, field_map))
                    if self.settings.limit and len(postings) >= self.settings.limit:
                        return postings
                if delay and page < pages:
                    time.sleep(delay)
        return postings

    def _fetch(self, url: str) -> Any:
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json", **self.settings.headers}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CollectorError(f"cannot fetch {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CollectorError(f"{url} did not return JSON: {raw[:200]}") from exc

    def _to_posting(self, item: Mapping[str, Any], field_map: Mapping[str, str]) -> RawPosting:
        values: dict[str, str] = {}
        for target, source in field_map.items():
            values[target] = _stringify(_dig(item, source, default=""))
        posting = RawPosting.from_dict(values)
        posting.platform = self.settings.platform or self.settings.name
        if not posting.source_id:
            posting.source_id = posting.url or f"{posting.company}-{posting.title}"
        return posting


def _dig(payload: Any, path: str, default: Any = ()) -> Any:
    """Follow a dotted path such as ``resultbody.job.items``."""

    if not path:
        return payload if isinstance(payload, (list, tuple)) else default
    cursor = payload
    for key in path.split("."):
        if isinstance(cursor, Mapping):
            cursor = cursor.get(key)
        elif isinstance(cursor, Sequence) and not isinstance(cursor, str) and key.isdigit():
            index = int(key)
            cursor = cursor[index] if index < len(cursor) else None
        else:
            return default
        if cursor is None:
            return default
    return cursor


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        return " ".join(_stringify(item) for item in value.values())
    if isinstance(value, Sequence):
        return "、".join(_stringify(item) for item in value)
    return str(value)


register_collector("json_api", JsonApiCollector)
register_collector("http_json", JsonApiCollector)
