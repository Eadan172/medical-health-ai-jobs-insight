"""Generic JSON-endpoint collector.

Recruiting sites expose JSON search endpoints, but the URL, parameters and
cookies differ per account and change over time, so they stay in configuration:

.. code-block:: toml

    [[sources]]
    name = "51job"
    type = "json_api"
    platform = "51job"
    urls = ["https://we.51job.com/api/job/search-pc?keyword={keyword}&pageNum={page}"]
    keywords = ["医疗 AI"]
    headers = { Cookie = "${JOB51_COOKIE}" }
    limit = 200

    [sources.options]
    items_path = "resultbody.job.items"
    pages = 2
    field_map = { title = "jobName", company = "fullCompanyName", city = "jobAreaString", salary_text = "provideSalaryString", url = "jobHref", publish_date = "issueDateString", description = "jobTags" }

``{keyword}`` is filled once per keyword. ``{page}`` and ``{timestamp}`` are
filled for every request. A blank ``Cookie`` header is a configuration error
and is never written into logs.
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
        _reject_blank_cookie(self.settings)

        postings: list[RawPosting] = []
        requests = list(self._request_urls(pages))
        for index, url in enumerate(requests):
            payload = self._fetch(url)
            for item in _items(payload, items_path, url):
                if not isinstance(item, Mapping):
                    continue
                postings.append(self._to_posting(item, field_map))
                if self.settings.limit and len(postings) >= self.settings.limit:
                    return postings
            if delay and index < len(requests) - 1:
                time.sleep(delay)
        return postings

    def _request_urls(self, pages: int) -> Iterable[str]:
        """Expand ``{keyword}`` per keyword, then ``{page}`` and ``{timestamp}``."""

        for template in self.settings.urls:
            keywords = self.settings.keywords if "{keyword}" in template else [""]
            if not keywords:
                keywords = [""]
            for keyword in keywords:
                quoted = urllib.parse.quote(keyword, safe="")
                for page in range(1, pages + 1):
                    yield template.format(page=page, keyword=quoted, timestamp=int(time.time()))

    def _fetch(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=_request_headers(self.settings.headers))
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CollectorError(f"cannot fetch {url}: {exc}") from exc
        return _parse_json(url, raw)

    def _to_posting(self, item: Mapping[str, Any], field_map: Mapping[str, str]) -> RawPosting:
        values: dict[str, str] = {}
        for target, source in field_map.items():
            values[target] = _stringify(_dig(item, source, default=""))
        posting = RawPosting.from_dict(values)
        posting.platform = self.settings.platform or self.settings.name
        if not posting.source_id:
            posting.source_id = posting.url or f"{posting.company}-{posting.title}"
        return posting


def _reject_blank_cookie(settings: Any) -> None:
    """Fail before any request when a Cookie header was configured but is empty."""

    if "Cookie" not in settings.headers:
        return
    if str(settings.headers.get("Cookie") or "").strip():
        return
    raise CollectorError(
        f"source {settings.name!r} Cookie is empty; set the credential in the environment and do not print it"
    )


def _request_headers(configured: Mapping[str, Any]) -> dict[str, str]:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    for key, value in configured.items():
        text = "" if value is None else str(value).strip()
        if text:
            headers[key] = text
    return headers


def _items(payload: Any, items_path: str, url: str) -> list[Any]:
    """Return the posting list, accepting 51job's ``job.items`` or ``job.item``."""

    if not items_path:
        if isinstance(payload, list):
            return list(payload)
        raise CollectorError(f"{url} did not return a JSON list")
    found = _dig(payload, items_path, default=None)
    if isinstance(found, list):
        return found
    if items_path.endswith(".items"):
        alternate = _dig(payload, items_path[:-1], default=None)
        if isinstance(alternate, list):
            return alternate
    raise CollectorError(f"{url} missing {items_path}{_error_hint(payload)}")


def _error_hint(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("message", "msg", "status", "code"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            text = str(value).replace("\n", " ")[:120]
            return f" ({key}={text})"
    return ""


def _parse_json(url: str, raw: str) -> Any:
    lowered = raw.lstrip()[:800].lower()
    if lowered.startswith("<") or "aliyun_waf" in lowered or "<html" in lowered:
        raise CollectorError(
            f"{url} returned an anti-bot HTML page instead of JSON. "
            "The cookie may be missing, expired, or rejected for this network."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CollectorError(f"{url} did not return JSON") from exc


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
