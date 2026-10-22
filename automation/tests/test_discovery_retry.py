"""job-discovery must retry a search challenge and name the platform that failed."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobsinsight.collectors.base import CollectorContext, CollectorError
from jobsinsight.collectors.search_discovery import SearchDiscoveryCollector
from jobsinsight.config import SourceSettings
from jobsinsight.models import RawPosting
from jobsinsight.pipeline import Pipeline
from jobsinsight.sources.discovery import discover_site
from jobsinsight.sources.http_client import HttpClient, HttpResponse, classify_access
from jobsinsight.sources.search_provider import (
    ChainedSearch,
    DDGSProvider,
    SearchHit,
    SearchOutcome,
    provider_chain,
    search_with_retries,
)

ANOMALY = "<html><body><div class='anomaly-modal__title'>bots</div><script src='//duckduckgo.com/anomaly.js'></script></body></html>"
DDG_HTML = Path(__file__).parent.joinpath("fixtures/jobs/ddg.html").read_text(encoding="utf-8")


def _client(bodies: list[tuple[int, str]]) -> tuple[HttpClient, list[float], dict[str, int]]:
    state = {"n": 0}

    def transport(method, url, headers, body, timeout):
        status, text = bodies[min(state["n"], len(bodies) - 1)]
        state["n"] += 1
        return HttpResponse(url=url, status=status, body=text)

    sleeps: list[float] = []
    return HttpClient(transport=transport, sleep=sleeps.append), sleeps, state


def test_duckduckgo_anomaly_page_is_a_challenge_not_an_empty_result():
    verdict = classify_access(HttpResponse(url="https://html.duckduckgo.com/html/", status=202, body=ANOMALY))
    assert verdict.status == "security_challenge"
    assert "anomaly-modal" in verdict.reason

    client, _sleeps, state = _client([(202, ANOMALY)])
    outcome = DDGSProvider(client).search("site:zhipin.com 上海 医疗AI")
    assert outcome.status == "security_challenge"
    assert outcome.hits == []
    assert state["n"] == 1


def test_challenge_is_retried_and_the_next_response_can_be_real_results():
    client, sleeps, state = _client([(202, ANOMALY), (200, DDG_HTML)])
    outcome, tries = search_with_retries(DDGSProvider(client), "site:zhipin.com 上海 医疗AI", sleep=sleeps.append)
    assert tries == 2
    assert sleeps == [1]
    assert outcome.status == "healthy"
    assert outcome.hits[0].url == "https://www.zhipin.com/job_detail/abc"
    assert state["n"] == 2


def test_timeout_is_retried_once_then_the_next_provider_is_used():
    class Down:
        name = "serper"
        calls = 0

        def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
            self.calls += 1
            return SearchOutcome(self.name, status="unavailable", error="timed out")

    class Ok:
        name = "ddgs"
        calls = 0

        def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
            self.calls += 1
            return SearchOutcome(
                self.name,
                hits=[SearchHit(title="医疗AI工程师", url="https://www.zhipin.com/job_detail/abc")],
            )

    down, ok = Down(), Ok()
    sleeps: list[float] = []
    outcome = ChainedSearch([down, ok], sleep=sleeps.append, attempts=3).search("q")
    assert down.calls == 2
    assert ok.calls == 1
    assert outcome.hits
    assert outcome.provider == "ddgs"
    assert sleeps == [1]


def test_discover_site_keeps_the_challenge_reason():
    class Challenged:
        name = "ddgs"

        def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
            return SearchOutcome(
                self.name,
                status="security_challenge",
                error="ddgs: security_challenge response asked for a challenge or login (anomaly-modal)，已重试 2 次",
            )

    client, _sleeps, _state = _client([(403, "denied")])
    report = discover_site(
        source="zhipin",
        domains=["zhipin.com"],
        queries=["site:zhipin.com 上海 医疗AI"],
        provider=Challenged(),
        client=client,
        per_minute=1000,
    )
    assert report.jobs == []
    assert report.status == "security_challenge"
    assert "anomaly-modal" in report.last_error
    assert "直连 blocked" in report.last_error


def test_collector_names_each_platform_when_search_stays_challenged(tmp_path: Path, monkeypatch):
    _write_catalog(tmp_path)

    class Challenged:
        name = "ddgs"

        def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
            return SearchOutcome(
                self.name,
                status="security_challenge",
                error="response asked for a challenge or login (anomaly-modal)",
            )

    monkeypatch.setattr(
        "jobsinsight.collectors.search_discovery.provider_chain",
        lambda client, environ=None: [Challenged()],
    )
    monkeypatch.setattr("jobsinsight.collectors.search_discovery.HttpClient", _quiet_client)
    collector = SearchDiscoveryCollector(_settings(), CollectorContext(project_root=tmp_path))
    with pytest.raises(CollectorError, match="公开搜索未得到可发布岗位") as raised:
        list(collector.collect())
    message = str(raised.value)
    for name in ("zhipin", "51job", "liepin"):
        assert f"{name}=security_challenge" in message
        assert "anomaly-modal" in message
    assert "zhipin=unavailable; 51job=unavailable; liepin=unavailable" not in message


def test_a_later_success_is_returned_and_failed_platforms_are_named(tmp_path: Path, monkeypatch):
    _write_catalog(tmp_path)

    class Mixed:
        name = "ddgs"

        def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
            if "zhipin.com" in query:
                return SearchOutcome(
                    self.name,
                    hits=[SearchHit(title="医疗AI工程师", url="https://www.zhipin.com/job_detail/abc", snippet="上海")],
                )
            return SearchOutcome(
                self.name,
                status="security_challenge",
                error="response asked for a challenge or login (anomaly-modal)",
            )

    monkeypatch.setattr(
        "jobsinsight.collectors.search_discovery.provider_chain",
        lambda client, environ=None: [Mixed()],
    )
    monkeypatch.setattr("jobsinsight.collectors.search_discovery.HttpClient", _quiet_client)
    collector = SearchDiscoveryCollector(_settings(), CollectorContext(project_root=tmp_path))
    postings = list(collector.collect())
    assert [item.title for item in postings] == ["医疗AI工程师"]
    assert "51job=security_challenge" in collector.source_note
    assert "liepin=security_challenge" in collector.source_note
    assert "zhipin=" not in collector.source_note


def test_pipeline_records_a_platform_note_without_failing_the_run(config, monkeypatch):
    class Noted:
        source_note = "部分平台没有可发布岗位：51job=security_challenge: anomaly-modal"

        def collect(self):
            return [
                RawPosting(
                    title="高级医学影像算法工程师",
                    company="联影智能",
                    city="上海",
                    platform="BOSS直聘",
                    description="负责 CT/MRI 医学影像的深度学习模型研发，熟悉 PyTorch。",
                    salary_text="40-60K",
                    experience_text="5-8年",
                    education_text="硕士",
                    source_type="zhipin",
                    url="https://www.zhipin.com/job_detail/abc.html",
                )
            ]

    monkeypatch.setattr("jobsinsight.pipeline.build_collector", lambda _settings, _context: Noted())
    report = Pipeline(config).run(dry_run=True)
    assert report.sources[0]["status"] == "ok"
    assert report.sources[0]["note"] == Noted.source_note
    assert report.status == "success"
    assert report.errors == []


def test_report_shows_a_platform_note_without_calling_it_a_run_error():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report.py"
    spec = importlib.util.spec_from_file_location("send_report_discovery", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _subject, body = module.build_report(
        [],
        {
            "started_at": "2026-10-21T13:00:00+00:00",
            "sources": [
                {
                    "name": "job-discovery",
                    "status": "ok",
                    "collected": 1,
                    "note": "部分平台没有可发布岗位：51job=security_challenge: anomaly-modal",
                }
            ],
        },
        [],
        now=datetime(2026, 10, 21, 13, 5, tzinfo=UTC),
        today="2026-10-21",
    )
    assert "51job=security_challenge" in body
    assert "anomaly-modal" in body


def test_only_ddg_is_used_when_no_search_key_is_configured():
    client, _sleeps, _state = _client([(200, DDG_HTML)])
    chain = provider_chain(client, {})
    assert [item.name for item in chain] == ["ddgs"]


def _settings() -> SourceSettings:
    return SourceSettings(
        name="job-discovery",
        type="search_discovery",
        limit=10,
        options={
            "config": "automation/config/sources.yaml",
            "queries": "automation/config/job_queries.yaml",
            "max_queries": 1,
            "detail_limit": 1,
        },
    )


def _quiet_client(*_args, **_kwargs) -> HttpClient:
    return HttpClient(
        transport=lambda method, url, headers, body, timeout: HttpResponse(url=url, status=403, body="denied"),
        sleep=lambda _seconds: None,
    )


def _write_catalog(root: Path) -> None:
    config = root / "automation" / "config"
    config.mkdir(parents=True)
    (config / "sources.yaml").write_text(
        """
sources:
  zhipin:
    enabled: true
    mode:
      - search_discovery
    domains:
      - zhipin.com
    rate_limit_per_minute: 1000
  51job:
    enabled: true
    mode:
      - search_discovery
    domains:
      - 51job.com
    rate_limit_per_minute: 1000
  liepin:
    enabled: true
    mode:
      - search_discovery
    domains:
      - liepin.com
    rate_limit_per_minute: 1000
""".strip(),
        encoding="utf-8",
    )
    (config / "job_queries.yaml").write_text(
        "keywords:\n  - 医疗AI\ncities:\n  - 上海\n",
        encoding="utf-8",
    )
