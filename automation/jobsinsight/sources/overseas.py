"""Public overseas job boards that do not need an API key.

ATS boards come from ``automation/config/overseas_companies.yaml``. Remote OK and
We Work Remotely are keyword-filtered on title and tags only; benefit text in
the description often mentions health and must not decide a match.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from ..career.yaml_lite import loads
from ..models import RawPosting
from .http_client import HttpClient

LOGGER = logging.getLogger(__name__)

USER_AGENT = "jobsinsight/1.0 (+https://github.com/Eadan172/medical-health-ai-jobs-insight; medical AI job digest)"
MAX_RESPONSE_BYTES = 32_000_000
REGION = "海外"
REMOTEOK_URL = "https://remoteok.com/api"
WWR_URL = "https://weworkremotely.com/remote-jobs.rss"
OVERSEAS_SOURCE_TYPES = frozenset({"greenhouse", "ashby", "lever", "workable", "remoteok", "weworkremotely"})
ATS_PLATFORM = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workable": "Workable",
}
ISO2_COUNTRY = {
    "US": "United States",
    "USA": "United States",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "IN": "India",
    "FR": "France",
    "DE": "Germany",
    "CA": "Canada",
    "JP": "Japan",
    "KR": "South Korea",
    "SG": "Singapore",
    "AU": "Australia",
    "NL": "Netherlands",
    "SE": "Sweden",
    "CH": "Switzerland",
    "ES": "Spain",
    "IT": "Italy",
    "IE": "Ireland",
    "PT": "Portugal",
    "BE": "Belgium",
    "DK": "Denmark",
    "NO": "Norway",
    "FI": "Finland",
    "IL": "Israel",
    "CN": "China",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "BR": "Brazil",
    "NZ": "New Zealand",
    "AT": "Austria",
    "PL": "Poland",
    "AE": "United Arab Emirates",
}

_TAG = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"\s+")
_USD_RANGE = re.compile(r"\$\s*([\d,]{4,})\s*(?:to|–|—|-)\s*\$?\s*([\d,]{4,})", re.I)
_HEALTH = (
    "healthcare",
    "medical",
    "medicine",
    "biotech",
    "biotechnology",
    "clinical",
    "pharma",
    "pharmaceutical",
    "biomedical",
    "diagnostic",
    "genomic",
    "genomics",
    "hospital",
    "patient",
    "health",
    "cadd",
    "computational chemistry",
    "drug discovery",
    "drug design",
    "medicinal chemistry",
)
_AI_PHRASES = (
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "data science",
    "data scientist",
    "data engineer",
    "computer vision",
    "applied scientist",
    "research scientist",
    "ml engineer",
    "ai engineer",
    "cadd",
    "computational chemistry",
    "molecular dynamics",
    "molecular simulation",
)
_AI_WORDS = ("ai", "ml", "nlp", "llm", "mle", "mlops")
_ROLE_STRONG = (
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "data scientist",
    "data science",
    "research scientist",
    "applied scientist",
    "bioinformatic",
    "computational",
    "computer vision",
    "ml engineer",
    "ai engineer",
    "mlops",
    "cadd",
    "computational chemistry",
    "molecular dynamics",
    "molecular simulation",
)
_ROLE_STRONG_WORDS = ("ai", "ml", "nlp", "llm", "mle")
_ROLE_MEDIUM = (
    "scientist",
    "research",
    "data engineer",
    "data analyst",
    "statistic",
    "algorithm",
    "quantitative",
    "technical staff",
)
_ROLE_BASE = (
    "engineer",
    "engineering",
    "developer",
    "software",
    "programmer",
    "devops",
    "infrastructure",
    "full stack",
    "fullstack",
    "full-stack",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "sre",
)
_EXCLUDE_PHRASES = (
    "account executive",
    "account manager",
    "talent acquisition",
    "customer success",
    "customer support",
    "business development",
    "human resources",
    "office manager",
    "people partner",
    "social media",
    "public relations",
    "legal counsel",
)
_EXCLUDE_WORDS = (
    "sales",
    "marketing",
    "recruiter",
    "recruiting",
    "accountant",
    "accounting",
    "payroll",
    "counsel",
    "receptionist",
    "copywriter",
)


def load_companies(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Return valid company rows and human-readable reasons for dropped rows."""

    if not path.is_file():
        return [], [f"company list not found: {path}"]
    payload = loads(path.read_text(encoding="utf-8"))
    rows = payload.get("companies") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], ["companies: must be a list"]
    companies: list[dict[str, str]] = []
    dropped: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            dropped.append(f"row {index} is not a mapping")
            continue
        if row.get("enabled", True) is False:
            continue
        name = str(row.get("name") or "").strip()
        ats = str(row.get("ats") or "").strip().lower()
        token = str(row.get("token") or "").strip()
        sector = str(row.get("sector") or "").strip()
        if not name or not token or ats not in ATS_PLATFORM:
            dropped.append(f"row {index} ({name or 'unnamed'}) needs name, token, and ats")
            continue
        companies.append({"name": name, "ats": ats, "token": token, "sector": sector})
    return companies, dropped


def board_url(ats: str, token: str, *, content: bool = True) -> str:
    quoted = urllib.parse.quote(token, safe="")
    if ats == "greenhouse":
        suffix = "?content=true" if content else ""
        return f"https://boards-api.greenhouse.io/v1/boards/{quoted}/jobs{suffix}"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{quoted}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{quoted}?includeCompensation=true"
    if ats == "workable":
        return f"https://apply.workable.com/api/v1/widget/accounts/{quoted}"
    raise ValueError(f"unsupported ats {ats}")


def role_score(title: str) -> int:
    """Prefer AI/ML/data/research titles, then other engineering titles. 0 drops the role."""

    text = _match_text(title)
    if _excluded(text):
        return 0
    score = 0
    if _contains_any(text, _ROLE_STRONG) or _has_word(text, _ROLE_STRONG_WORDS):
        score += 3
    if _contains_any(text, _ROLE_MEDIUM):
        score += 2
    if _contains_any(text, _ROLE_BASE) or _has_word(text, ("sre",)):
        score += 1
    return score


def select_roles(postings: list[RawPosting], limit: int) -> list[RawPosting]:
    scored = [(role_score(posting.title), posting) for posting in postings]
    scored = [(score, posting) for score, posting in scored if score > 0 and posting.url]
    scored.sort(key=lambda item: -item[0])
    chosen: list[RawPosting] = []
    seen: set[str] = set()
    for _score, posting in scored:
        if posting.url in seen:
            continue
        seen.add(posting.url)
        chosen.append(posting)
        if limit and len(chosen) >= limit:
            break
    return chosen


def matches_remote_focus(title: str, tags: list[str]) -> bool:
    """Health and AI/ML must both show up in the title or tags, never the description.

    The title has to carry at least one of those signals. Remote OK sometimes attaches
    a long sitewide tag dump (including both ``medical`` and ``data science``) to
    unrelated roles, so tag lists longer than 12 are ignored.
    """

    if role_score(title) <= 0:
        return False
    trusted = tags if len(tags) <= 12 else []
    title_text = _match_text(title)
    combined = _match_text(" ".join([title, *trusted]))
    health = _contains_any(combined, _HEALTH)
    ai = _contains_any(combined, _AI_PHRASES) or _has_word(combined, _AI_WORDS)
    title_hit = _contains_any(title_text, (*_HEALTH, *_AI_PHRASES)) or _has_word(title_text, _AI_WORDS)
    return bool(health and ai and title_hit)


def collect_ats_postings(
    path: Path,
    client: HttpClient,
    *,
    limit: int = 200,
    per_company_limit: int = 3,
    delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[RawPosting], list[str]]:
    companies, dropped = load_companies(path)
    failures = list(dropped)
    if not companies:
        return [], failures or [f"no companies in {path}"]
    per_company = max(1, per_company_limit)
    postings: list[RawPosting] = []
    for index, company in enumerate(companies):
        if index and delay_seconds:
            sleep(delay_seconds)
        found, error = _fetch_company(client, company)
        if error:
            failures.append(f"{company['name']}: {error}")
            continue
        kept = select_roles(found, per_company)
        LOGGER.info("%s %s: kept %d/%d", company["ats"], company["name"], len(kept), len(found))
        postings.extend(kept)
        if limit and len(postings) >= limit:
            return postings[:limit], failures
    return postings, failures


def collect_remoteok_postings(
    client: HttpClient,
    *,
    limit: int = 25,
    delay_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> list[RawPosting]:
    if delay_seconds:
        sleep(delay_seconds)
    payload, error = _fetch_json(client, REMOTEOK_URL)
    if error or not isinstance(payload, list):
        raise RuntimeError(error or "Remote OK did not return a JSON list")
    postings: list[RawPosting] = []
    for item in payload:
        if not isinstance(item, Mapping) or not item.get("position"):
            continue
        tags = [str(tag) for tag in item.get("tags") or [] if str(tag).strip()]
        title = str(item.get("position") or "")
        if not matches_remote_focus(title, tags):
            continue
        url = str(item.get("url") or item.get("apply_url") or "")
        if not url:
            continue
        location = repair_text(str(item.get("location") or ""))
        postings.append(
            _remote_posting(
                source_id=str(item.get("id") or url),
                platform="Remote OK",
                source_type="remoteok",
                title=repair_text(title),
                company=repair_text(str(item.get("company") or "")),
                city=location,
                country="",
                remote=True,
                url=url,
                salary_text=_remoteok_salary(item.get("salary_min"), item.get("salary_max")),
                tags=tags,
                published=item.get("date") or item.get("epoch"),
                method="remoteok_api",
            )
        )
    postings.sort(key=lambda posting: posting.publish_date, reverse=True)
    return postings[:limit] if limit else postings


def collect_wwr_postings(
    client: HttpClient,
    *,
    limit: int = 25,
    delay_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> list[RawPosting]:
    if delay_seconds:
        sleep(delay_seconds)
    response = client.request("GET", WWR_URL, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
    if response.status != 200 or not response.body.strip():
        raise RuntimeError(response.error or f"We Work Remotely HTTP {response.status}")
    try:
        root = ET.fromstring(response.body.encode("utf-8"))
    except ET.ParseError as exc:
        raise RuntimeError("We Work Remotely RSS was not valid XML") from exc
    postings: list[RawPosting] = []
    for item in root.findall(".//item"):
        raw_title = _text(item, "title")
        company, title = _split_wwr_title(raw_title)
        tags = _wwr_tags(item)
        if not matches_remote_focus(title or raw_title, tags):
            continue
        url = _text(item, "link")
        if not url:
            continue
        country = _text(item, "country")
        state = _text(item, "state")
        region_name = _text(item, "region")
        city = "" if "anywhere" in region_name.lower() else ", ".join(part for part in (state, region_name) if part)
        postings.append(
            _remote_posting(
                source_id=url,
                platform="We Work Remotely",
                source_type="weworkremotely",
                title=title or raw_title,
                company=company,
                city=city,
                country=country,
                remote=True,
                url=url,
                salary_text="",
                tags=tags,
                published=_text(item, "pubDate"),
                method="wwr_rss",
            )
        )
    postings.sort(key=lambda posting: posting.publish_date, reverse=True)
    return postings[:limit] if limit else postings


def _fetch_company(client: HttpClient, company: Mapping[str, str]) -> tuple[list[RawPosting], str]:
    ats = company["ats"]
    token = company["token"]
    try:
        payload, error = _fetch_json(client, board_url(ats, token, content=True))
        if payload is None and ats == "greenhouse" and error == "invalid JSON":
            payload, error = _fetch_json(client, board_url(ats, token, content=False))
        if payload is None:
            return [], error or "empty response"
        return _parse_board(ats, payload, company), ""
    except ValueError as exc:
        return [], str(exc)


def _fetch_json(client: HttpClient, url: str) -> tuple[Any | None, str]:
    response = client.request("GET", url, headers={"Accept": "application/json"})
    if response.status != 200:
        return None, response.error or f"HTTP {response.status}"
    try:
        return json.loads(response.body), ""
    except json.JSONDecodeError:
        return None, "invalid JSON"


def _parse_board(ats: str, payload: Any, company: Mapping[str, str]) -> list[RawPosting]:
    if ats == "greenhouse":
        return _parse_greenhouse(payload, company)
    if ats == "lever":
        return _parse_lever(payload, company)
    if ats == "ashby":
        return _parse_ashby(payload, company)
    if ats == "workable":
        return _parse_workable(payload, company)
    raise ValueError(f"unsupported ats {ats}")


def _parse_greenhouse(payload: Any, company: Mapping[str, str]) -> list[RawPosting]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("greenhouse payload has no jobs list")
    postings: list[RawPosting] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        url = str(job.get("absolute_url") or "")
        title = str(job.get("title") or "")
        if not url or not title:
            continue
        location = job.get("location")
        place = location.get("name") if isinstance(location, Mapping) else str(location or "")
        postings.append(
            _ats_posting(
                company,
                source_id=str(job.get("id") or url),
                title=title,
                city=str(place or ""),
                country="",
                remote="remote" in str(place or "").lower(),
                url=url,
                salary_text="",
                description=str(job.get("content") or ""),
                published=job.get("first_published") or job.get("updated_at"),
            )
        )
    return postings


def _parse_lever(payload: Any, company: Mapping[str, str]) -> list[RawPosting]:
    if not isinstance(payload, list):
        raise ValueError("lever payload is not a list")
    postings: list[RawPosting] = []
    for job in payload:
        if not isinstance(job, Mapping):
            continue
        url = str(job.get("hostedUrl") or job.get("applyUrl") or "")
        title = str(job.get("text") or "")
        if not url or not title:
            continue
        categories = job.get("categories") if isinstance(job.get("categories"), Mapping) else {}
        place = str(categories.get("location") or "")
        workplace = str(job.get("workplaceType") or "")
        postings.append(
            _ats_posting(
                company,
                source_id=str(job.get("id") or url),
                title=title,
                city=place,
                country=str(job.get("country") or ""),
                remote=workplace.lower() == "remote" or "remote" in place.lower(),
                url=url,
                salary_text=_usd_range_text(str(job.get("additionalPlain") or "")),
                description=str(job.get("descriptionPlain") or ""),
                published=job.get("createdAt"),
            )
        )
    return postings


def _parse_ashby(payload: Any, company: Mapping[str, str]) -> list[RawPosting]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("ashby payload has no jobs list")
    postings: list[RawPosting] = []
    for job in jobs:
        if not isinstance(job, Mapping) or job.get("isListed") is False:
            continue
        url = str(job.get("jobUrl") or job.get("applyUrl") or "")
        title = str(job.get("title") or "")
        if not url or not title:
            continue
        address = job.get("address") if isinstance(job.get("address"), Mapping) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), Mapping) else {}
        country = str(postal.get("addressCountry") or "")
        workplace = str(job.get("workplaceType") or "")
        place = str(job.get("location") or "")
        compensation = job.get("compensation") if isinstance(job.get("compensation"), Mapping) else {}
        postings.append(
            _ats_posting(
                company,
                source_id=str(job.get("id") or url),
                title=title,
                city=place,
                country=country,
                remote=bool(job.get("isRemote")) or workplace.lower() == "remote" or "remote" in place.lower(),
                url=url,
                salary_text=_ashby_salary(compensation),
                description=str(job.get("descriptionPlain") or job.get("descriptionHtml") or ""),
                published=job.get("publishedAt"),
            )
        )
    return postings


def _parse_workable(payload: Any, company: Mapping[str, str]) -> list[RawPosting]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("workable payload has no jobs list")
    postings: list[RawPosting] = []
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        url = str(job.get("url") or job.get("shortlink") or "")
        title = str(job.get("title") or "")
        if not url or not title:
            continue
        locations = job.get("locations") if isinstance(job.get("locations"), list) else []
        primary = locations[0] if locations and isinstance(locations[0], Mapping) else {}
        country = str(job.get("country") or primary.get("country") or primary.get("countryCode") or "")
        city = str(job.get("city") or primary.get("city") or "")
        postings.append(
            _ats_posting(
                company,
                source_id=str(job.get("shortcode") or url),
                title=title,
                city=city,
                country=country,
                remote=bool(job.get("telecommuting")),
                url=url,
                salary_text="",
                description="",
                published=job.get("published_on") or job.get("created_at"),
            )
        )
    return postings


def _ats_posting(
    company: Mapping[str, str],
    *,
    source_id: str,
    title: str,
    city: str,
    country: str,
    remote: bool,
    url: str,
    salary_text: str,
    description: str,
    published: Any,
) -> RawPosting:
    plain = html_to_text(description)
    sector = company.get("sector") or ""
    note = f"行业：{sector}（医疗健康）" if sector else "行业：医疗健康"
    text = f"{plain}\n{note}" if plain else note
    shown_country = display_country(country)
    return RawPosting(
        source_id=source_id,
        platform=ATS_PLATFORM[company["ats"]],
        title=" ".join(title.split()),
        company=company["name"],
        city=format_place(city, shown_country, remote=remote),
        url=url,
        salary_text=salary_text,
        description=text[:1500],
        publish_date=iso_date(published),
        source_type=company["ats"],
        discovery_method="ats_json",
        source_url=url,
        company_level="海外",
        country=shown_country,
        region=REGION,
        partial=not bool(plain),
        detail_fetch_status="parsed" if plain else "partial",
    )


def _remote_posting(
    *,
    source_id: str,
    platform: str,
    source_type: str,
    title: str,
    company: str,
    city: str,
    country: str,
    remote: bool,
    url: str,
    salary_text: str,
    tags: list[str],
    published: Any,
    method: str,
) -> RawPosting:
    # Title and tags only. The public description repeats benefit language such as "health".
    focus = " ".join(part for part in [title, *tags] if part)
    shown_country = display_country(country)
    return RawPosting(
        source_id=source_id,
        platform=platform,
        title=" ".join(title.split()),
        company=company.strip() or platform,
        city=format_place(city, shown_country, remote=remote),
        url=url,
        salary_text=salary_text,
        description=focus[:500],
        publish_date=iso_date(published),
        source_type=source_type,
        discovery_method=method,
        source_url=url,
        company_level="海外",
        country=shown_country,
        region=REGION,
        partial=False,
        detail_fetch_status="parsed",
    )


def repair_text(value: str) -> str:
    """Undo UTF-8 text that Remote OK sometimes returns decoded as Latin-1."""

    text = value or ""
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return repaired or text


def format_place(city: str, country: str, *, remote: bool) -> str:
    place = " ".join((city or "").split())
    country = " ".join((country or "").split())
    if remote and place and "remote" not in place.lower():
        place = f"{place} · Remote"
    elif remote and not place:
        place = "Remote"
    if country and country.lower() not in place.lower():
        place = f"{place}, {country}" if place else country
    return place or "Remote"


def display_country(value: str) -> str:
    text = " ".join((value or "").split())
    if 2 <= len(text) <= 3 and text.isalpha():
        return ISO2_COUNTRY.get(text.upper(), text.upper())
    return text


def html_to_text(value: str, limit: int = 1200) -> str:
    text = html.unescape(value or "")
    text = _TAG.sub(" ", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = _SPACE.sub(" ", text).strip()
    return text[:limit]


def iso_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        number = int(float(value))
        if number > 10**12:
            number //= 1000
        try:
            return datetime.fromtimestamp(number, UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return ""
    return parsed.date().isoformat()


def _ashby_salary(compensation: Mapping[str, Any]) -> str:
    summary = compensation.get("scrapeableCompensationSalarySummary") or compensation.get("compensationTierSummary")
    if isinstance(summary, str) and summary.strip():
        return " ".join(summary.split())
    for tier in compensation.get("compensationTiers") or []:
        if not isinstance(tier, Mapping):
            continue
        for component in tier.get("components") or []:
            if not isinstance(component, Mapping):
                continue
            kind = str(component.get("compensationType") or "")
            if "salary" not in kind.lower() and kind.lower() not in {"cash", "salary"}:
                continue
            low, high = component.get("minValue"), component.get("maxValue")
            text = _usd_numbers(low, high)
            if text:
                return text
    return ""


def _remoteok_salary(low: Any, high: Any) -> str:
    return _usd_numbers(low, high)


def _usd_range_text(text: str) -> str:
    match = _USD_RANGE.search(text or "")
    if not match:
        return ""
    return _usd_numbers(match.group(1).replace(",", ""), match.group(2).replace(",", ""))


def _usd_numbers(low: Any, high: Any) -> str:
    try:
        low_n = int(float(low))
        high_n = int(float(high))
    except (TypeError, ValueError):
        return ""
    if high_n < low_n:
        low_n, high_n = high_n, low_n
    if low_n < 10000:
        return ""
    return f"${low_n:,}–${high_n:,}/年"


def _wwr_tags(item: ET.Element) -> list[str]:
    skills = _text(item, "skills")
    category = _text(item, "category")
    tags = [part.strip() for part in skills.split(",") if part.strip()]
    if category:
        tags.append(category)
    return tags


def _split_wwr_title(raw: str) -> tuple[str, str]:
    text = " ".join((raw or "").split())
    if ":" in text:
        company, _, title = text.partition(":")
        company, title = company.strip(), title.strip()
        if company and title:
            return company, title
    return "", text


def _text(item: ET.Element, tag: str) -> str:
    value = item.findtext(tag)
    return " ".join(value.split()) if value else ""


def _match_text(value: str) -> str:
    return value.lower().replace("-", " ").replace("_", " ")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _excluded(text: str) -> bool:
    return _contains_any(text, _EXCLUDE_PHRASES) or _has_word(text, _EXCLUDE_WORDS)
