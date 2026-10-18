"""51job search responses are JSON with resultbody.job.items (or job.item)."""

from __future__ import annotations

import json
import urllib.request

import pytest

from jobsinsight.collectors.base import CollectorContext, CollectorError
from jobsinsight.collectors.json_api import JsonApiCollector
from jobsinsight.config import SourceSettings

FIXTURE = {
    "status": "1",
    "resultbody": {
        "job": {
            "items": [
                {
                    "jobId": "159384721",
                    "jobName": "医学影像算法工程师",
                    "fullCompanyName": "联影智能",
                    "companyName": "联影",
                    "jobAreaString": "上海-浦东新区",
                    "provideSalaryString": "30-50万/年",
                    "workYearString": "3-5年",
                    "degreeString": "硕士",
                    "jobHref": "https://jobs.51job.com/shanghai/159384721.html",
                    "issueDateString": "2026-10-01",
                    "jobTags": ["PyTorch", "医学影像"],
                    "companySizeString": "1000-5000人",
                }
            ]
        }
    },
}

FIELD_MAP = {
    "source_id": "jobId",
    "title": "jobName",
    "company": "fullCompanyName",
    "city": "jobAreaString",
    "salary_text": "provideSalaryString",
    "experience_text": "workYearString",
    "education_text": "degreeString",
    "url": "jobHref",
    "publish_date": "issueDateString",
    "description": "jobTags",
    "company_scale": "companySizeString",
}


class _Body:
    def __init__(self, body: str) -> None:
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


def _source(**overrides: object) -> SourceSettings:
    settings = SourceSettings(
        name="51job",
        type="json_api",
        platform="51job",
        urls=["https://we.51job.com/api/job/search-pc?keyword={keyword}&pageNum={page}&timestamp={timestamp}"],
        keywords=["医疗 AI", "药物研发 算法"],
        headers={"Cookie": "fixture-cookie", "Referer": "https://we.51job.com/pc/search"},
        options={"items_path": "resultbody.job.items", "pages": 1, "delay_seconds": 0, "field_map": FIELD_MAP},
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _collector(settings: SourceSettings) -> JsonApiCollector:
    return JsonApiCollector(settings, CollectorContext())


def test_fixture_response_maps_51job_fields(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    def fake_fetch(self: JsonApiCollector, url: str) -> dict[str, object]:
        seen.append(url)
        return FIXTURE

    monkeypatch.setattr(JsonApiCollector, "_fetch", fake_fetch)
    postings = list(_collector(_source()).collect())

    decoded = [urllib.parse.unquote(url) for url in seen]
    assert decoded[0].startswith("https://we.51job.com/api/job/search-pc?keyword=医疗 AI&pageNum=1&timestamp=")
    assert decoded[1].startswith("https://we.51job.com/api/job/search-pc?keyword=药物研发 算法&pageNum=1&timestamp=")
    assert decoded[0].rsplit("=", 1)[-1].isdigit()
    assert "药物研发" not in decoded[0]
    posting = postings[0]
    assert posting.platform == "51job"
    assert posting.source_type == "51job"
    assert posting.source_id == "159384721"
    assert posting.title == "医学影像算法工程师"
    assert posting.company == "联影智能"
    assert posting.city == "上海-浦东新区"
    assert posting.salary_text == "30-50万/年"
    assert posting.experience_text == "3-5年"
    assert posting.education_text == "硕士"
    assert posting.url == "https://jobs.51job.com/shanghai/159384721.html"
    assert posting.publish_date == "2026-10-01"
    assert posting.description == "PyTorch、医学影像"
    assert posting.company_scale == "1000-5000人"
    assert "fixture-cookie" not in json.dumps(posting.as_dict(), ensure_ascii=False)


def test_job_item_singular_is_accepted(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "resultbody": {"job": {"item": [{"jobId": 7, "jobName": "医疗大模型工程师", "fullCompanyName": "某公司"}]}}
    }

    monkeypatch.setattr(JsonApiCollector, "_fetch", lambda self, url: payload)
    settings = _source(keywords=["医疗大模型"])
    postings = list(_collector(settings).collect())

    assert [posting.source_id for posting in postings] == ["7"]
    assert postings[0].title == "医疗大模型工程师"


def test_missing_items_path_reports_status_without_the_body(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        JsonApiCollector,
        "_fetch",
        lambda self, url: {"status": "0", "message": "请登录", "secret": "do-not-print-body"},
    )
    with pytest.raises(CollectorError, match="missing resultbody.job.items") as raised:
        list(_collector(_source(keywords=["医疗 AI"])).collect())

    message = str(raised.value)
    assert "请登录" in message
    assert "do-not-print-body" not in message


def test_waf_html_does_not_echo_the_challenge(monkeypatch: pytest.MonkeyPatch):
    html = '<html><meta name="aliyun_waf_aa"><textarea>{"_waf_bd8ce2ce37":"SECRETTOKEN"}</textarea>'

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> _Body:
        assert request.get_header("Cookie") == "fixture-cookie"
        assert request.get_header("Referer") == "https://we.51job.com/pc/search"
        return _Body(html)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(CollectorError, match="anti-bot HTML") as raised:
        list(_collector(_source(keywords=["医疗 AI"])).collect())

    assert "SECRETTOKEN" not in str(raised.value)
    assert "fixture-cookie" not in str(raised.value)


def test_blank_cookie_fails_before_any_request(monkeypatch: pytest.MonkeyPatch):
    def urlopen(*_args: object, **_kwargs: object) -> _Body:
        raise AssertionError("blank cookie must not be sent")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    settings = _source(headers={"Cookie": "  "})
    with pytest.raises(CollectorError, match="Cookie is empty"):
        list(_collector(settings).collect())


def test_url_without_keyword_placeholder_is_requested_once(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []
    monkeypatch.setattr(JsonApiCollector, "_fetch", lambda self, url: seen.append(url) or FIXTURE)
    settings = _source(urls=["https://example.test/jobs?page={page}"], keywords=["医疗 AI", "药物研发 算法"])
    list(_collector(settings).collect())
    assert seen == ["https://example.test/jobs?page=1"]


def test_delay_is_between_requests(monkeypatch: pytest.MonkeyPatch):
    sleeps: list[float] = []
    monkeypatch.setattr("jobsinsight.collectors.json_api.time.sleep", sleeps.append)
    monkeypatch.setattr(JsonApiCollector, "_fetch", lambda self, url: FIXTURE)
    settings = _source()
    settings.options = {**settings.options, "delay_seconds": 1.5}
    list(_collector(settings).collect())
    assert sleeps == [1.5]
