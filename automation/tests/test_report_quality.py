"""Data-quality fixes for the daily mailed report."""

from __future__ import annotations

import importlib.util
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from jobsinsight.collectors.browser import posting_from_card
from jobsinsight.config import SourceSettings
from jobsinsight.heuristics import normalise
from jobsinsight.job_store import job_identity, merge_jobs
from jobsinsight.models import Job, RawPosting
from jobsinsight.pipeline import Pipeline
from jobsinsight.sources.discovery import _from_hit
from jobsinsight.sources.search_provider import SearchHit

FIXTURE = Path(__file__).parent / "fixtures" / "report" / "postings.json"
RUN_STARTED = "2026-10-17T13:00:00+00:00"
NOW = datetime(2026, 10, 17, 13, 10, tzinfo=UTC)


def _report_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "send_report.py"
    spec = importlib.util.spec_from_file_location("send_report_quality", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jobs_from_fixture() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs: list[dict] = []
    for entry in payload["postings"]:
        posting = RawPosting(
            title=entry["title"],
            company=entry["company"],
            city=entry.get("city", ""),
            platform=entry.get("platform", ""),
            url=entry.get("url", ""),
            source_url=entry.get("url", ""),
            salary_text=entry.get("salary_text", ""),
            experience_text=entry.get("experience_text", ""),
            education_text=entry.get("education_text", ""),
            description=entry.get("description", ""),
            source_type=entry.get("source_type", ""),
            region=entry.get("region", ""),
        )
        values = normalise(posting)
        jobs.append(
            {
                "title": posting.title,
                "company": posting.company,
                "city": posting.city,
                "platform": posting.platform,
                "url": posting.url,
                "source_type": posting.source_type,
                "region": posting.region,
                "salary_text": posting.salary_text,
                "salary_min": values["salary_min"],
                "salary_max": values["salary_max"],
                "experience": values["experience"],
                "education": values["education"],
                "category": values["category"],
                "relevance": values["relevance"],
                "first_seen_at": entry["first_seen_at"],
            }
        )
    jobs.extend(payload["noise"])
    return jobs


def test_sample_report_from_fixture_counts_salary_and_direction():
    report = _report_module()
    jobs = _jobs_from_fixture()
    subject, body = report.build_report(
        jobs,
        {"started_at": RUN_STARTED, "sources": []},
        [],
        now=NOW,
        today="2026-10-17",
    )

    assert "新增 6 条" in subject
    assert "国内 1，海外 5" in body
    assert "海外岗位 <b>6</b> 条，其中今日新增 5 条" in body
    assert "其他 4、医学影像AI 2" in body
    assert "美元/年中位数约 300k（2 条）" in body
    assert "人民币/月中位数约 50k（1 条）" in body
    assert "k/月" not in body
    assert "未知/未知" in body
    assert "5-10年/博士" in body
    assert "5-10年/硕士" in body
    assert "医学影像算法工程师" in body
    assert "联影智能" in body
    assert "样例公司" not in body
    assert "有限公司招聘" not in body
    assert "招聘信息" not in body
    assert "未知公司" not in body


def test_annual_cny_is_labeled_by_year_not_folded_into_monthly():
    report = _report_module()
    jobs = [
        {
            "title": "算法工程师",
            "company": "甲公司",
            "city": "上海",
            "platform": "51job",
            "source_type": "51job",
            "url": "https://jobs.51job.com/shanghai/160000009.html",
            "salary_text": "30-60万/年",
            "salary_min": 25,
            "salary_max": 50,
            "relevance": 80,
            "first_seen_at": "2026-10-17T13:02:00+00:00",
        }
    ]
    _subject, body = report.build_report(
        jobs, {"started_at": RUN_STARTED, "sources": []}, [], now=NOW, today="2026-10-17"
    )
    assert "人民币/年中位数约 45万（1 条）" in body
    assert "k/月" not in body


def test_51job_bare_wan_is_monthly_and_explicit_year_stays_annual():
    report = _report_module()
    started = "2026-10-18T13:00:00+00:00"
    now = datetime(2026, 10, 18, 13, 10, tzinfo=UTC)

    def job(salary: str, url: str) -> dict:
        return {
            "title": "算法工程师",
            "company": "甲公司",
            "city": "上海",
            "platform": "51job",
            "source_type": "51job",
            "url": url,
            "salary_text": salary,
            "relevance": 80,
            "first_seen_at": "2026-10-18T13:02:00+00:00",
        }

    _subject, monthly = report.build_report(
        [
            job("3.5-5万", "https://jobs.51job.com/shanghai/160000011.html"),
            job("3-4万·15薪", "https://jobs.51job.com/shanghai/160000012.html"),
        ],
        {"started_at": started, "sources": []},
        [],
        now=now,
        today="2026-10-18",
    )
    assert "人民币/月" in monthly
    assert "人民币/年" not in monthly

    _subject, noted = report.build_report(
        [job("3-4万·15薪", "https://jobs.51job.com/shanghai/160000012.html")],
        {"started_at": started, "sources": []},
        [],
        now=now,
        today="2026-10-18",
    )
    assert "人民币/月中位数约 35k·15薪（1 条）" in noted
    assert "人民币/年" not in noted

    _subject, yearly = report.build_report(
        [job("年薪30-60万", "https://jobs.51job.com/shanghai/160000013.html")],
        {"started_at": started, "sources": []},
        [],
        now=now,
        today="2026-10-18",
    )
    assert "人民币/年中位数约 45万（1 条）" in yearly
    assert "k/月" not in yearly


def test_liepin_company_pages_and_unknown_place_stay_out_of_the_report():
    report = _report_module()
    started = "2026-10-18T13:00:00+00:00"
    jobs = [
        {
            "title": "某医疗科技有限公司",
            "company": "未知公司",
            "city": "未知",
            "platform": "猎聘网",
            "source_type": "liepin",
            "discovery_method": "search_engine",
            "url": "https://m.liepin.com/company/12541563",
            "salary_text": "80-120元",
            "relevance": 40,
            "first_seen_at": "2026-10-18T13:02:00+00:00",
        },
        {
            "title": "医疗算法工程师",
            "company": "未知公司",
            "city": "未知城市",
            "platform": "猎聘网",
            "source_type": "liepin",
            "discovery_method": "public_page",
            "url": "https://www.liepin.com/s/medical-ai",
            "relevance": 50,
            "first_seen_at": "2026-10-18T13:02:00+00:00",
        },
        {
            "title": "医疗AI算法工程师",
            "company": "联影智能",
            "city": "上海",
            "platform": "猎聘网",
            "source_type": "liepin",
            "discovery_method": "search_engine",
            "url": "https://www.liepin.com/job/1978123456.shtml",
            "salary_text": "40-60K",
            "relevance": 80,
            "first_seen_at": "2026-10-18T13:02:00+00:00",
        },
    ]
    _subject, body = report.build_report(
        jobs,
        {"started_at": started, "sources": []},
        [],
        now=datetime(2026, 10, 18, 13, 10, tzinfo=UTC),
        today="2026-10-18",
    )
    assert "新增 1 条" in _subject
    assert "联影智能" in body
    assert "12541563" not in body
    assert "未知公司" not in body
    assert "80-120元" not in body


def test_same_day_second_run_reports_no_new_jobs():
    report = _report_module()
    jobs = _jobs_from_fixture()
    later = "2026-10-17T21:00:00+00:00"
    subject, body = report.build_report(
        jobs,
        {"started_at": later, "sources": []},
        [],
        now=datetime(2026, 10, 17, 21, 5, tzinfo=UTC),
        today="2026-10-17",
    )
    assert "新增 0 条" in subject
    assert "今日没有新增，下表是相关度最高的海外岗位。" in body


def test_restoring_published_data_keeps_first_seen(config, tmp_path: Path):
    seed = tmp_path / "live.json"
    seed.write_text(
        json.dumps(
            [
                {
                    "source_id": "gh-1",
                    "platform": "Greenhouse",
                    "title": "Senior AI Engineer",
                    "company": "Suki",
                    "city": "Redwood City",
                    "url": "https://job-boards.greenhouse.io/suki/jobs/1",
                    "salary_text": "$240K - $360K",
                    "description": "Healthcare machine learning engineer.",
                    "source_type": "greenhouse",
                    "region": "海外",
                    "publish_date": "2025-04-24",
                },
                {
                    "source_id": "51-1",
                    "platform": "51job",
                    "title": "医学影像算法工程师",
                    "company": "联影智能",
                    "city": "上海",
                    "url": "https://jobs.51job.com/shanghai/159384721.html",
                    "salary_text": "40-60K",
                    "experience_text": "5-8年经验",
                    "education_text": "硕士",
                    "description": "负责 CT 影像的深度学习分割。",
                    "source_type": "51job",
                    "publish_date": "2026-10-01",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config.sources = [SourceSettings(name="seed", type="fixture", path=str(seed))]
    pipeline = Pipeline(config)
    first = pipeline.run()
    assert first.diff["new_jobs"] == 2
    stored = json.loads((config.data_dir / "jobs.json").read_text(encoding="utf-8"))
    seen = {job["title"]: job["first_seen_at"] for job in stored}
    assert all(seen.values())

    for path in config.data_dir.iterdir():
        path.unlink()
    assert not (config.data_dir / "jobs.json").exists()
    time.sleep(1.1)

    second = pipeline.run()
    assert second.diff["new_jobs"] == 0
    again = json.loads((config.data_dir / "jobs.json").read_text(encoding="utf-8"))
    assert {job["title"]: job["first_seen_at"] for job in again} == seen

    report = _report_module()
    subject, _body = report.build_report(
        again,
        {"started_at": second.started_at, "sources": []},
        [],
        now=datetime.now(UTC),
        today="2026-10-17",
    )
    assert "新增 0 条" in subject


def test_51job_cards_keep_separate_identities_and_source_type():
    page = "https://we.51job.com/pc/search?keyword=%E5%8C%BB%E7%96%97AI&searchType=2&pageNum=1"
    first = posting_from_card(
        platform="51job",
        source_type="51job",
        page_url=page,
        title="AI算法工程师",
        company="上海探寻信息技术有限公司",
        city="上海·徐汇区",
        salary_text="",
        link="",
        sensorsdata=json.dumps(
            {
                "jobId": "160000001",
                "jobSalary": "2-3万/月",
                "jobYear": "3-5年",
                "jobDegree": "本科",
                "jobHref": "https://jobs.51job.com/shanghai-xhq/160000001.html",
            },
            ensure_ascii=False,
        ),
    )
    second = posting_from_card(
        platform="51job",
        source_type="51job",
        page_url=page,
        title="大模型算法工程师",
        company="美年大健康产业控股股份有限公司",
        city="上海",
        link=page,
        sensorsdata=json.dumps({"jobId": "160000002"}, ensure_ascii=False),
    )
    assert first is not None and second is not None
    assert first.source_type == "51job"
    assert first.url == "https://jobs.51job.com/shanghai-xhq/160000001.html"
    assert page not in first.url
    assert second.url == "https://jobs.51job.com/all/160000002.html"
    assert first.experience_text == "3-5年"
    assert first.education_text == "本科"
    assert first.salary_text == "2-3万/月"
    left = Job(
        id=1,
        platform=first.platform,
        title=first.title,
        company=first.company,
        city=first.city,
        url=first.url,
        source_url=first.source_url,
        source_type=first.source_type,
    )
    right = Job(
        id=2,
        platform=second.platform,
        title=second.title,
        company=second.company,
        city=second.city,
        url=second.url,
        source_url=second.source_url,
        source_type=second.source_type,
    )
    assert job_identity(left) != job_identity(right)
    merged = merge_jobs([], [left, right], [], "2026-10-17T13:00:00+00:00")
    assert merged.new == 2
    assert len(merged.jobs) == 2


def test_previously_seen_51job_rows_are_not_new_domestic_jobs():
    """A later run of the same 51job cards keeps first_seen, so the mail shows 0 new."""

    report = _report_module()
    jobs = [
        {
            "title": f"医学影像算法工程师{index}",
            "company": "联影智能",
            "city": "上海",
            "platform": "51job",
            "source_type": "51job",
            "url": f"https://jobs.51job.com/shanghai/160000{index:03d}.html",
            "salary_text": "3-4万",
            "relevance": 80,
            "first_seen_at": "2026-10-20T13:02:00+00:00",
        }
        for index in range(38)
    ]
    subject, body = report.build_report(
        jobs,
        {"started_at": "2026-10-21T13:00:00+00:00", "sources": []},
        [],
        now=datetime(2026, 10, 21, 13, 10, tzinfo=UTC),
        today="2026-10-21",
    )
    assert "新增 0 条" in subject
    assert "国内 0" in body
    assert "今天没有抓到新的国内岗位" in body


def test_company_and_listing_pages_are_not_discovered_as_jobs():
    company = SearchHit(
        title="「冰洲石生物科技（上海）有限公司招聘」-boss直聘",
        url="https://m.zhipin.com/companys/207230937914ae4c1nFy0926EQ~~.html",
    )
    listing = SearchHit(
        title="「医疗人工智能招聘信息」-boss直聘",
        url="https://www.zhipin.com/zhaopin/a0af30c4427a2f301n173dm-FA~~",
    )
    detail = SearchHit(
        title="医疗AI算法工程师",
        url="https://www.zhipin.com/job_detail/8c5a000af8d2ed610nJ_3d67GVZQ.html",
    )
    assert _from_hit(company, "zhipin", ["zhipin.com"]) is None
    assert _from_hit(listing, "zhipin", ["zhipin.com"]) is None
    assert _from_hit(detail, "zhipin", ["zhipin.com"]) is not None
