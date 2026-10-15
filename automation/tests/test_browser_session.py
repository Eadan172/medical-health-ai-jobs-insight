from __future__ import annotations

from pathlib import Path

import pytest

from jobsinsight.collectors import CollectorContext, CollectorError, build_collector
from jobsinsight.collectors.browser import iter_search_urls, session_failure_reason
from jobsinsight.config import SourceSettings


def test_search_urls_expand_each_keyword_and_honor_page_start():
    urls = iter_search_urls(
        ["https://example.test/s?key={keyword}&page={page}"],
        ["医疗AI", "药物研发"],
        pages=2,
        page_start=0,
    )

    assert urls == [
        "https://example.test/s?key=%E5%8C%BB%E7%96%97AI&page=0",
        "https://example.test/s?key=%E5%8C%BB%E7%96%97AI&page=1",
        "https://example.test/s?key=%E8%8D%AF%E7%89%A9%E7%A0%94%E5%8F%91&page=0",
        "https://example.test/s?key=%E8%8D%AF%E7%89%A9%E7%A0%94%E5%8F%91&page=1",
    ]


def test_search_urls_without_keyword_placeholder_are_not_repeated():
    urls = iter_search_urls(
        ["https://example.test/list?page={page}"],
        ["医疗AI", "药物研发"],
        pages=2,
    )

    assert urls == [
        "https://example.test/list?page=1",
        "https://example.test/list?page=2",
    ]


def test_search_urls_reject_bad_paging():
    with pytest.raises(CollectorError, match="page_start"):
        iter_search_urls(["https://example.test/?page={page}"], ["医疗AI"], pages=1, page_start=-1)


def test_session_failure_reason_names_captcha_login_wall_and_expired_session():
    captcha = session_failure_reason(
        account_name="liepin",
        captcha_visible=True,
        login_wall_visible=False,
        logged_in_visible=True,
        job_card_count=3,
    )
    wall = session_failure_reason(
        account_name="job51",
        captcha_visible=False,
        login_wall_visible=True,
        logged_in_visible=False,
        job_card_count=0,
    )
    expired = session_failure_reason(
        account_name="boss",
        captcha_visible=False,
        login_wall_visible=False,
        logged_in_visible=False,
        job_card_count=0,
    )
    usable = session_failure_reason(
        account_name="boss",
        captcha_visible=False,
        login_wall_visible=False,
        logged_in_visible=False,
        job_card_count=4,
    )

    assert captcha and "验证码" in captcha and "browser-login liepin" in captcha
    assert wall and "登录墙" in wall
    assert expired and "过期" in expired
    assert usable is None


def test_browser_collector_fails_before_playwright_when_storage_state_is_missing(tmp_path: Path):
    accounts = tmp_path / "accounts.toml"
    accounts.write_text(
        """
[accounts.job51]
login_url = "https://login.51job.com/login.php?loginway=0"
storage_state = "state/browser/job51.json"

[accounts.job51.selectors]
job_card = ".joblist-item"
title = ".jname"
""",
        encoding="utf-8",
    )
    collector = build_collector(
        SourceSettings(
            name="job51",
            type="browser",
            required=False,
            options={"account": "job51", "accounts_file": str(accounts)},
        ),
        CollectorContext(project_root=tmp_path),
    )

    with pytest.raises(CollectorError, match="browser-login job51"):
        list(collector.collect())
