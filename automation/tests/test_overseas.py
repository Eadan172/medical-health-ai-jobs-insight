"""Overseas ATS, Remote OK, and We Work Remotely collectors. No network."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobsinsight import heuristics
from jobsinsight.collectors import available_collectors
from jobsinsight.collectors.base import CollectorContext
from jobsinsight.collectors.overseas import AtsCollector
from jobsinsight.config import SourceSettings
from jobsinsight.sources.http_client import HttpClient, HttpResponse
from jobsinsight.sources.overseas import (
    OVERSEAS_SOURCE_TYPES,
    collect_ats_postings,
    collect_remoteok_postings,
    collect_wwr_postings,
    load_companies,
    repair_text,
    role_score,
)

FIXTURES = Path(__file__).parent / "fixtures" / "overseas"
CATALOG = Path(__file__).resolve().parents[1] / "config" / "overseas_companies.yaml"


def _body(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(pages: dict[str, tuple[int, str]], seen: list[dict] | None = None) -> HttpClient:
    def transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> HttpResponse:
        if seen is not None:
            seen.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
        for needle, response in pages.items():
            if needle in url:
                return HttpResponse(url=url, status=response[0], body=response[1])
        return HttpResponse(url=url, status=404, body="missing")

    return HttpClient(transport=transport, sleep=lambda _seconds: None, user_agent="jobsinsight-test")


def _catalog(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "companies.yaml"
    path.write_text("companies:\n" + rows, encoding="utf-8")
    return path


def test_verified_company_list_parses_and_keeps_doctolib_on_greenhouse_only():
    companies, dropped = load_companies(CATALOG)

    assert dropped == []
    assert len(companies) == 58
    assert {row["ats"] for row in companies} == {"greenhouse", "ashby", "lever", "workable"}
    assert sum(row["ats"] == "greenhouse" for row in companies) == 27
    assert sum(row["ats"] == "ashby" for row in companies) == 25
    assert sum(row["ats"] == "lever" for row in companies) == 5
    assert sum(row["ats"] == "workable" for row in companies) == 1
    doctolib = [row for row in companies if row["name"].casefold() == "doctolib" or "doctolib" in row["token"]]
    assert doctolib == [{"name": "Doctolib", "ats": "greenhouse", "token": "doctolib", "sector": "数字健康"}]
    assert all(row["name"] and row["token"] and row["sector"] for row in companies)


def test_bad_company_rows_are_dropped(tmp_path: Path):
    path = _catalog(
        tmp_path,
        '  - name: "Ok"\n    ats: greenhouse\n    token: "ok"\n    sector: "AI制药"\n'
        '  - name: "Nope"\n    ats: taleo\n    token: "x"\n    sector: "AI制药"\n'
        "  - ats: lever\n",
    )

    companies, dropped = load_companies(path)

    assert [row["name"] for row in companies] == ["Ok"]
    assert len(dropped) == 2


def test_ats_boards_map_roles_and_skip_a_failed_company(tmp_path: Path):
    path = _catalog(
        tmp_path,
        '  - name: "Recursion"\n    ats: greenhouse\n    token: "recursionpharmaceuticals"\n    sector: "AI制药"\n'
        '  - name: "Missing"\n    ats: greenhouse\n    token: "missing"\n    sector: "AI制药"\n'
        '  - name: "Enveda"\n    ats: lever\n    token: "enveda"\n    sector: "AI制药"\n'
        '  - name: "Insitro"\n    ats: ashby\n    token: "insitro"\n    sector: "AI制药"\n'
        '  - name: "Lunit"\n    ats: workable\n    token: "lunit"\n    sector: "医学影像AI"\n',
    )
    sleeps: list[float] = []
    pages = {
        "recursionpharmaceuticals/jobs?content=true": (200, _body("greenhouse.json")),
        "postings/enveda": (200, _body("lever.json")),
        "job-board/insitro": (200, _body("ashby.json")),
        "accounts/lunit": (200, _body("workable.json")),
    }
    postings, failures = collect_ats_postings(
        path,
        _client(pages),
        per_company_limit=3,
        delay_seconds=1,
        sleep=sleeps.append,
    )

    by_company = {posting.company: posting for posting in postings}
    assert "Missing" not in by_company
    assert any(item.startswith("Missing:") for item in failures)
    assert sleeps == [1, 1, 1, 1]
    recursion = [posting for posting in postings if posting.company == "Recursion"]
    assert [posting.title for posting in recursion] == [
        "Research Scientist, Computational Biology",
        "Data Scientist",
        "Machine Learning Engineer",
    ]
    assert all(posting.source_type == "greenhouse" for posting in recursion)
    assert all(posting.platform == "Greenhouse" and posting.region == "海外" for posting in recursion)
    assert all(posting.company_level == "海外" for posting in recursion)
    machine = recursion[-1]
    assert machine.url == "https://job-boards.greenhouse.io/recursionpharmaceuticals/jobs/101"
    assert machine.publish_date == "2026-10-01"
    assert machine.city == "Salt Lake City, Utah"
    assert "Build clinical machine learning models" in machine.description
    assert "行业：AI制药" in machine.description
    assert "Account Executive" not in {posting.title for posting in postings}
    assert heuristics.relevance_score(machine.title, machine.description, []) >= 30

    enveda = by_company["Enveda"]
    assert enveda.source_type == "lever"
    assert enveda.city == "Hyderabad, India"
    assert enveda.country == "India"
    assert enveda.salary_text == "$137,300–$166,000/年"
    assert enveda.url.startswith("https://jobs.lever.co/enveda/")
    assert enveda.publish_date == "2026-08-10"

    insitro = by_company["Insitro"]
    assert insitro.source_type == "ashby"
    assert insitro.salary_text == "$180K – $220K"
    assert insitro.country == "United States"
    assert "South San Francisco" in insitro.city
    assert insitro.publish_date == "2026-09-21"
    assert "hidden" not in insitro.url

    lunit = by_company["Lunit"]
    assert lunit.source_type == "workable"
    assert lunit.city == "Tokyo, Japan"
    assert lunit.url == "https://apply.workable.com/j/ABC123"
    assert lunit.publish_date == "2026-05-08"
    assert lunit.partial is True


def test_greenhouse_retries_without_content_when_the_body_is_truncated(tmp_path: Path):
    path = _catalog(tmp_path, '  - name: "Abridge"\n    ats: greenhouse\n    token: "abridge"\n    sector: "临床AI"\n')
    seen: list[dict] = []
    pages = {
        "boards/abridge/jobs?content=true": (200, "{not-json"),
        "boards/abridge/jobs": (200, _body("greenhouse.json")),
    }
    postings, failures = collect_ats_postings(path, _client(pages, seen), delay_seconds=0, per_company_limit=1)

    assert failures == []
    assert len(postings) == 1
    assert [call["url"].split("/jobs")[-1] for call in seen] == ["?content=true", ""]
    assert postings[0].source_type == "greenhouse"


def test_remoteok_matches_title_and_tags_not_benefit_text():
    postings = collect_remoteok_postings(_client({"remoteok.com/api": (200, _body("remoteok.json"))}), delay_seconds=0)

    assert [posting.title for posting in postings] == ["Machine Learning Engineer"]
    posting = postings[0]
    assert posting.source_type == "remoteok"
    assert posting.company == "Helix Remote"
    assert posting.region == "海外"
    assert posting.city == "Remote"
    assert posting.url == "https://remoteok.com/remote-jobs/keep-ml"
    assert posting.salary_text == "$150,000–$190,000/年"
    assert posting.publish_date == "2026-10-12"
    assert "401k" not in posting.description
    assert "healthcare" in posting.description
    assert "should-drop" not in posting.url
    assert "drop-tag-soup" not in posting.url
    assert heuristics.relevance_score(posting.title, posting.description, []) >= 30
    assert repair_text("Islāmābād".encode().decode("latin-1")) == "Islāmābād"


def test_wwr_matches_title_and_tags_not_the_description():
    postings = collect_wwr_postings(_client({"remote-jobs.rss": (200, _body("wwr.xml"))}), delay_seconds=0)

    assert [posting.title for posting in postings] == ["Clinical Machine Learning Engineer"]
    posting = postings[0]
    assert posting.company == "Helix"
    assert posting.source_type == "weworkremotely"
    assert posting.platform == "We Work Remotely"
    assert posting.region == "海外"
    assert posting.country == "United States"
    assert posting.url == "https://weworkremotely.com/remote-jobs/keep-ml"
    assert posting.publish_date == "2026-10-13"
    assert "401k" not in posting.description
    assert "wellness" not in posting.description
    assert "Clinical" in posting.description
    assert role_score("Account Executive") == 0
    assert role_score("Machine Learning Engineer") > role_score("Senior Software Engineer")


def test_ats_collector_sends_a_user_agent_and_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class StubClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def request(self, method: str, url: str, **kwargs: object) -> HttpResponse:
            return HttpResponse(url=url, status=200, body=_body("greenhouse.json"))

    monkeypatch.setattr("jobsinsight.collectors.overseas.HttpClient", StubClient)
    catalog = _catalog(
        tmp_path,
        '  - name: "Recursion"\n    ats: greenhouse\n    token: "recursionpharmaceuticals"\n    sector: "AI制药"\n',
    )
    settings = SourceSettings(
        name="overseas-ats",
        type="ats",
        platform="海外ATS",
        timeout_seconds=25,
        limit=10,
        options={"config": str(catalog), "delay_seconds": 0, "per_company_limit": 1},
    )

    postings = list(AtsCollector(settings, CollectorContext(project_root=tmp_path)).collect())

    assert "ats" in available_collectors()
    assert "remoteok" in available_collectors()
    assert "wwr" in available_collectors()
    assert str(captured["user_agent"]).startswith("jobsinsight/")
    assert captured["timeout"] == 25
    assert captured["max_bytes"] > 1_000_000
    assert postings[0].source_type == "greenhouse"
    assert postings[0].source_type in OVERSEAS_SOURCE_TYPES


def _report_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report.py"
    spec = importlib.util.spec_from_file_location("send_report", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_report_counts_overseas_jobs_and_ignores_empty_source_type():
    report = _report_module()
    assert report.OVERSEAS_SOURCE_TYPES == OVERSEAS_SOURCE_TYPES
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    jobs = [
        {"title": "样例", "company": "样例公司", "source_type": "", "city": "上海", "relevance": 99},
        {
            "title": "国内算法",
            "company": "晶泰",
            "source_type": "zhipin",
            "city": "上海",
            "relevance": 80,
            "first_seen_at": "2026-10-15T01:00:00+00:00",
            "salary_min": 30,
            "salary_max": 50,
            "url": "https://example.com/domestic",
        },
        {
            "title": "Machine Learning Engineer",
            "company": "Recursion",
            "source_type": "greenhouse",
            "region": "海外",
            "city": "Salt Lake City, Utah",
            "country": "",
            "platform": "Greenhouse",
            "relevance": 70,
            "first_seen_at": "2026-10-15T02:00:00+00:00",
            "salary_text": "$180K – $220K",
            "url": "https://job-boards.greenhouse.io/recursionpharmaceuticals/jobs/101",
        },
    ]

    subject, body = report.build_report(jobs, {"sources": []}, [], now=now, today="2026-10-15")

    assert "新增 2 条" in subject
    assert "海外岗位 <b>1</b> 条，其中今日新增 1 条" in body
    assert "国内 1，海外 1" in body
    assert "样例公司" not in body
    assert "$180K – $220K" in body
    assert "Machine Learning Engineer" in body
    assert "今日新增国内岗位" in body
