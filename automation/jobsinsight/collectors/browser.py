"""Optional Playwright collector using a normal persisted login session.

This is intended for sites the user is authorised to access. It does not hide
automation, bypass CAPTCHAs, or evade rate limits. When a verification page is
detected, collection stops and asks the user to refresh the session manually.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from ..accounts import DEFAULT_ACCOUNTS_FILE, BrowserAccount, get_account, storage_path
from ..config import ConfigError
from ..keywords import with_cadd_keywords
from ..models import RawPosting
from ..sources.urlutil import is_job_posting_url
from .base import Collector, CollectorError, register_collector

_SOURCE_TYPES = {"boss": "zhipin", "liepin": "liepin", "job51": "51job", "51job": "51job"}

LOGGER = logging.getLogger(__name__)


class BrowserCollector(Collector):
    type = "browser"

    def collect(self) -> Iterable[RawPosting]:
        options = self.settings.options or {}
        account_name = str(options.get("account") or self.settings.name)
        accounts_file = str(options.get("accounts_file") or DEFAULT_ACCOUNTS_FILE)
        try:
            account = get_account(self.context.project_root, account_name, accounts_file)
        except ConfigError as exc:
            raise CollectorError(str(exc)) from exc

        state = storage_path(self.context.project_root, account)
        allow_password = bool(options.get("allow_password_login"))
        if not state.is_file() and not allow_password:
            raise CollectorError(
                f"账号 {account.name!r} 没有已保存的登录会话 {state}；"
                f"先执行 python -m jobsinsight browser-login {account.name}"
            )

        pages = max(1, int(options.get("pages", 1)))
        page_start = int(options.get("page_start", 1))
        delay = float(options.get("delay_seconds", 0))
        urls = iter_search_urls(
            self.settings.urls,
            with_cadd_keywords(list(self.settings.keywords)),
            pages=pages,
            page_start=page_start,
        )
        slow_mo = max(0, int(options.get("slow_mo_ms", 250)))
        source_type = str(options.get("source_type") or _SOURCE_TYPES.get(account.name) or account.name or "browser")
        sync_playwright = _playwright()
        postings: list[RawPosting] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                slow_mo=slow_mo,
                channel=(os.environ.get("JOBSINSIGHT_BROWSER_CHANNEL") or None),
                args=["--disable-blink-features=AutomationControlled"],
            )
            context_options: dict[str, Any] = {}
            if state.is_file():
                context_options["storage_state"] = str(state)
            if os.environ.get("JOBSINSIGHT_USER_AGENT"):
                context_options["user_agent"] = os.environ["JOBSINSIGHT_USER_AGENT"]
            context = browser.new_context(**context_options)
            page = context.new_page()
            try:
                if not state.is_file():
                    self._login(page, account, state)
                for index, url in enumerate(urls):
                    if delay and index:
                        time.sleep(delay)
                    page.goto(url, wait_until="domcontentloaded", timeout=int(self.settings.timeout_seconds * 1000))
                    page.wait_for_timeout(int(options.get("settle_ms", 1500)))
                    self._reject_verification(page, account)
                    self._reject_expired_session(page, account)
                    postings.extend(self._extract(page, account, url, source_type))
                    if self.settings.limit and len(postings) >= self.settings.limit:
                        return postings[: self.settings.limit]
                state.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(state))
            finally:
                context.close()
                browser.close()
        return postings

    def _login(self, page: Any, account: BrowserAccount, state: Path) -> None:
        username = account.resolved_username()
        password = account.resolved_password()
        selectors = account.selectors
        if not username or not password:
            raise CollectorError(
                f"账号 {account.name!r} 没有可用凭据或登录状态；"
                f"先执行 python -m jobsinsight browser-login {account.name}"
            )
        required = ("username", "password", "submit")
        missing = [name for name in required if not selectors.get(name)]
        if missing:
            raise CollectorError(f"账号 {account.name!r} 缺少登录 selector：{', '.join(missing)}")

        LOGGER.info("使用浏览器登录账号 %s（凭据不会写入日志）", account.name)
        page.goto(account.login_url, wait_until="domcontentloaded", timeout=int(self.settings.timeout_seconds * 1000))
        page.locator(selectors["username"]).fill(username)
        page.locator(selectors["password"]).fill(password)
        page.locator(selectors["submit"]).click()
        page.wait_for_timeout(int(self.settings.options.get("login_wait_ms", 3000)))
        self._reject_verification(page, account)
        logged_in = selectors.get("logged_in")
        if logged_in and not page.locator(logged_in).first.is_visible():
            raise CollectorError(f"账号 {account.name!r} 登录后未找到登录标志；请用 browser-login 人工确认并保存会话")
        state.parent.mkdir(parents=True, exist_ok=True)
        page.context.storage_state(path=str(state))

    @staticmethod
    def _reject_verification(page: Any, account: BrowserAccount) -> None:
        reason = session_failure_reason(
            account_name=account.name,
            captcha_visible=_locator_visible(page, account.selectors.get("captcha")),
            login_wall_visible=False,
            logged_in_visible=None,
            job_card_count=0,
        )
        if reason:
            raise CollectorError(reason)

    @staticmethod
    def _reject_expired_session(page: Any, account: BrowserAccount) -> None:
        selectors = account.selectors
        logged_in = selectors.get("logged_in")
        job_card = selectors.get("job_card")
        reason = session_failure_reason(
            account_name=account.name,
            captcha_visible=False,
            login_wall_visible=_locator_visible(page, selectors.get("login_wall") or selectors.get("logged_out")),
            logged_in_visible=_locator_visible(page, logged_in) if logged_in else None,
            job_card_count=page.locator(job_card).count() if job_card else 0,
        )
        if reason:
            raise CollectorError(reason)

    def _extract(self, page: Any, account: BrowserAccount, page_url: str, source_type: str) -> list[RawPosting]:
        selectors = account.selectors
        if not selectors.get("job_card") or not selectors.get("title"):
            raise CollectorError(f"账号 {account.name!r} 至少需要 job_card 和 title selector")
        cards = page.locator(selectors["job_card"])
        results: list[RawPosting] = []
        for index in range(cards.count()):
            card = cards.nth(index)
            sensors = _attribute(card, "[sensorsdata]", "sensorsdata") or _own_attribute(card, "sensorsdata")
            posting = posting_from_card(
                platform=self.settings.platform or self.settings.name,
                source_type=source_type,
                page_url=page_url,
                title=_text(card, selectors.get("title")),
                company=_text(card, selectors.get("company")),
                city=_text(card, selectors.get("city")),
                salary_text=_text(card, selectors.get("salary")),
                experience_text=_text(card, selectors.get("experience")),
                education_text=_text(card, selectors.get("education")),
                description=_text(card, selectors.get("description")),
                publish_date=_text(card, selectors.get("publish_date")),
                link=_attribute(card, selectors.get("link"), "href"),
                source_id=_attribute(card, selectors.get("source_id"), "data-id"),
                sensorsdata=sensors,
                index=index,
            )
            if posting is not None:
                results.append(posting)
        return results


def iter_search_urls(
    urls: Sequence[str],
    keywords: Sequence[str],
    *,
    pages: int,
    page_start: int = 1,
) -> list[str]:
    """Expand ``{keyword}`` once per keyword and ``{page}`` across ``pages``.

    Templates without ``{keyword}`` are requested once per page. ``page_start``
    is the first page number (猎聘 ``currentPage`` is 0).
    """

    if pages < 1:
        raise CollectorError("pages must be >= 1")
    if page_start < 0:
        raise CollectorError("page_start must be >= 0")
    built: list[str] = []
    for template in urls:
        terms = list(keywords) if "{keyword}" in template else [""]
        if not terms:
            terms = [""]
        for keyword in terms:
            quoted = quote(keyword, safe="") if keyword else ""
            for page in range(page_start, page_start + pages):
                built.append(template.format(page=page, keyword=quoted))
    return built


def session_failure_reason(
    *,
    account_name: str,
    captcha_visible: bool,
    login_wall_visible: bool,
    logged_in_visible: bool | None,
    job_card_count: int,
) -> str | None:
    """Why a browser source should stop, or None when the page looks usable.

    Captcha and an expired login are source failures. Callers mark the source
    ``required = false`` so the rest of the run still publishes.
    """

    relogin = f"请执行 python -m jobsinsight browser-login {account_name}"
    if captcha_visible:
        return f"账号 {account_name!r} 遇到验证码/安全验证；不会自动绕过，{relogin}"
    if login_wall_visible:
        return f"账号 {account_name!r} 的登录会话已失效（出现登录墙）；{relogin}"
    if logged_in_visible is False and job_card_count == 0:
        return f"账号 {account_name!r} 的登录会话可能已过期（未见登录标志，也没有岗位卡片）；{relogin}"
    return None


def save_interactive_session(
    project_root: Path,
    account_name: str,
    accounts_file: str = DEFAULT_ACCOUNTS_FILE,
) -> Path:
    """Open a visible browser; the user logs in normally, then presses Enter."""

    account = get_account(project_root, account_name, accounts_file)
    state = storage_path(project_root, account)
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            channel=(os.environ.get("JOBSINSIGHT_BROWSER_CHANNEL") or None),
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(account.login_url, wait_until="domcontentloaded")
        print("浏览器已打开。请正常登录；遇到验证码请人工完成。登录完成后回到终端按 Enter。")
        input()
        state.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state))
        context.close()
        browser.close()
    return state


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CollectorError(
            "browser 数据源需要 Playwright：pip install '.[browser]' && playwright install chromium"
        ) from exc
    return sync_playwright


def _locator_visible(page: Any, selector: str | None) -> bool:
    if not selector:
        return False
    locator = page.locator(selector)
    return bool(locator.count() and locator.first.is_visible())


def posting_from_card(
    *,
    platform: str,
    source_type: str,
    page_url: str,
    title: str,
    company: str = "",
    city: str = "",
    salary_text: str = "",
    experience_text: str = "",
    education_text: str = "",
    description: str = "",
    publish_date: str = "",
    link: str = "",
    source_id: str = "",
    sensorsdata: str = "",
    index: int = 0,
) -> RawPosting | None:
    """Build one card.

    51job search cards share the results URL and often have no ``<a>``. Using that
    URL as the job identity collapses a whole page into one row, and an empty
    ``source_type`` makes the daily report treat the row as sample data.
    ``sensorsdata`` carries the per-job id and, when present, the real href.
    """

    payload = _sensors(sensorsdata)
    title = (title or _sensor_text(payload, "jobTitle", "jobName")).strip()
    if not title:
        return None
    company = company or _sensor_text(payload, "companyName", "fullCompanyName")
    city = city or _sensor_text(payload, "jobArea", "jobAreaString")
    salary_text = salary_text or _sensor_text(payload, "jobSalary", "provideSalaryString", "salary")
    experience_text = experience_text or _sensor_text(payload, "jobYear", "workYearString")
    education_text = education_text or _sensor_text(payload, "jobDegree", "degreeString")
    publish_date = publish_date or _sensor_text(payload, "issueDate", "issueDateString")
    job_url = _concrete_url(page_url, link) or _concrete_url(
        page_url, _sensor_text(payload, "jobHref", "jobUrl", "pageUrl")
    )
    if not job_url:
        job_id = _sensor_text(payload, "jobId", "jobid")
        if job_id.isdigit():
            job_url = f"https://jobs.51job.com/all/{job_id}.html"
    identity = source_id or _sensor_text(payload, "jobId", "jobid") or job_url
    if not identity:
        identity = "|".join((platform, company, title, city, str(index)))
    return RawPosting(
        source_id=identity,
        platform=platform,
        title=title,
        company=company.strip(),
        city=city.strip(),
        url=job_url,
        salary_text=salary_text.strip(),
        experience_text=experience_text.strip(),
        education_text=education_text.strip(),
        description=description.strip(),
        publish_date=publish_date.strip(),
        source_type=source_type,
        source_url=job_url,
    )


def _sensors(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _sensor_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _concrete_url(page_url: str, link: str) -> str:
    if not link:
        return ""
    absolute = urljoin(page_url, link)
    return absolute if is_job_posting_url(absolute) else ""


def _text(card: Any, selector: str | None) -> str:
    if not selector:
        return ""
    locator = card.locator(selector).first
    return (locator.text_content() or "").strip() if locator.count() else ""


def _own_attribute(card: Any, name: str) -> str:
    try:
        return (card.get_attribute(name) or "").strip()
    except Exception:
        return ""


def _attribute(card: Any, selector: str | None, name: str) -> str:
    if not selector:
        return ""
    locator = card.locator(selector).first
    return (locator.get_attribute(name) or "").strip() if locator.count() else ""


register_collector("browser", BrowserCollector)
register_collector("playwright", BrowserCollector)
