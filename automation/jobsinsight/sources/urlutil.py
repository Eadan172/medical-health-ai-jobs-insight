"""URL cleanup and job identity. Tracking parameters are not part of a job."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "from",
    "search_id",
    "spm",
    "trackid",
    "ckid",
    "sid",
}


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in TRACKING_KEYS
    ]
    cleaned = parsed._replace(query=urlencode(query), fragment="")
    text = urlunparse(cleaned)
    if text.endswith("/") and parsed.path not in {"", "/"}:
        text = text[:-1]
    return text


def host_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def matches_domain(url: str, domains: list[str]) -> bool:
    host = host_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def fingerprint_job(
    *, source: str, source_job_id: str = "", company: str = "", title: str = "", city: str = "", salary: str = ""
) -> str:
    if source_job_id:
        return f"{source}|{source_job_id}".lower()
    parts = [_fold(company), _fold(title), _fold(city), _fold(salary)]
    return "|".join(parts)


# Search, company-index and keyword-listing pages are not postings.
_LISTING_TITLE = re.compile(r"有限公司招聘|股份有限公司招聘|招聘信息")
_DETAIL_PATH = re.compile(r"/job_detail/|/jobs/\d|/job/\d|/\d{5,}\.html", re.I)


def is_job_posting_url(url: str) -> bool:
    """False for company indexes and search/listing pages; empty URLs are left alone."""

    text = (url or "").strip()
    if not text:
        return True
    parsed = urlparse(text)
    host = host_of(text)
    path = parsed.path.lower()
    blocked = False
    if _on_host(host, "zhipin.com"):
        blocked = (
            "/companys/" in path
            or path.rstrip("/").endswith("/companys")
            or "/zhaopin" in path
            or "/web/geek/job" in path
        )
    elif (_on_host(host, "51job.com") and "/pc/search" in path) or (
        _on_host(host, "liepin.com") and path.startswith("/zhaopin")
    ):
        blocked = True
    return not blocked


def _on_host(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def looks_like_non_job_title(title: str) -> bool:
    """Company-index and keyword-listing titles, not a posting that merely says 招聘."""

    return bool(_LISTING_TITLE.search(title or ""))


def is_publishable_record(record: object) -> bool:
    """Drop company/listing pages. A real posting may still lack a URL."""

    if isinstance(record, Mapping):
        title = str(record.get("title") or "")
        url = str(record.get("source_url") or record.get("url") or "")
    else:
        title = str(getattr(record, "title", "") or "")
        url = str(getattr(record, "source_url", "") or getattr(record, "url", "") or "")
    if url and not is_job_posting_url(url):
        return False
    if _DETAIL_PATH.search(urlparse(url).path):
        return True
    return not looks_like_non_job_title(title)


def cache_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _fold(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
