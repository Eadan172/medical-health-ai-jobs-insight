"""CADD statistics live in the daily mail, after the summary."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

STARTED = "2026-10-22T13:00:00+00:00"
NOW = datetime(2026, 10, 22, 13, 10, tzinfo=UTC)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "send_report.py"


def _report():
    spec = importlib.util.spec_from_file_location("send_report_cadd", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _job(**overrides: object) -> dict:
    job = {
        "title": "计算化学研究员",
        "company": "晶泰科技",
        "city": "上海",
        "platform": "51job",
        "source_type": "51job",
        "url": "https://jobs.51job.com/shanghai/160000001.html",
        "salary_text": "30-45K",
        "experience": "3-5年",
        "education": "硕士",
        "category": "AI药物研发",
        "relevance": 80,
        "first_seen_at": "2026-10-22T13:02:00+00:00",
    }
    job.update(overrides)
    return job


def _section(body: str) -> str:
    start = body.index("<h3>CADD / AI药物研发</h3>")
    rest = body[start:]
    marker = "<h3>"
    end = rest.index(marker, len("<h3>CADD / AI药物研发</h3>"))
    return rest[:end]


def _jobs() -> list[dict]:
    return [
        _job(),
        _job(
            title="CADD Scientist",
            company="Recursion",
            city="Salt Lake City",
            platform="Greenhouse",
            source_type="greenhouse",
            region="海外",
            url="https://job-boards.greenhouse.io/recursion/jobs/9",
            salary_text="$180K – $220K",
            experience="5-10年",
            education="本科",
            category="其他",
        ),
        _job(
            title="分子模拟工程师",
            company="晶泰科技",
            city="深圳",
            url="https://jobs.51job.com/shenzhen/160000002.html",
            education="博士",
            experience="1-3年",
        ),
        _job(
            title="计算机辅助药物设计",
            company="医渡科技",
            city="北京",
            url="https://jobs.51job.com/beijing/160000003.html",
            education="",
            experience="应届",
            first_seen_at="2026-10-21T13:02:00+00:00",
            relevance=40,
        ),
        _job(
            title="算法工程师",
            company="未知药厂",
            city="杭州",
            url="https://jobs.51job.com/hangzhou/160000004.html",
            education="不限",
            category="AI制药",
            experience="经验不限",
        ),
        _job(
            title="需求对接专员",
            company="对接公司",
            city="上海",
            url="https://jobs.51job.com/shanghai/160000005.html",
            education="本科",
            category="其他",
            description="负责客户对接与需求整理",
        ),
        _job(
            title="CADD 样例",
            company="样例药企",
            source_type="",
            url="",
            source_url="",
            education="硕士",
            category="AI药物研发",
        ),
    ]


def test_cadd_section_follows_the_summary_and_counts_real_jobs():
    report = _report()
    _subject, body = report.build_report(
        _jobs(),
        {"started_at": STARTED, "sources": []},
        [],
        now=NOW,
        today="2026-10-22",
        previous_master_eligible=2,
    )

    assert body.index("<h3>概览</h3>") < body.index("<h3>CADD / AI药物研发</h3>")
    assert body.index("<h3>CADD / AI药物研发</h3>") < body.index("今日新增国内岗位")
    section = _section(body)
    assert "累计 <b>5</b> 条，本次新增 <b>4</b> 条" in section
    assert "国内 4 条，海外 1 条" in section
    assert "硕士可投 <b>4</b> 条" in section
    assert "硕士可投比上次多 2 条" in section
    assert "博士 1" in section
    assert "未注明 1" in section
    assert "3-5年" in section
    assert "上海" in section
    assert "人民币/月" in section
    assert "计算化学研究员" in section
    assert "30-45K" in section
    assert "https://jobs.51job.com/shanghai/160000001.html" in section
    assert "计算机辅助药物设计" not in section.split("本次新增的 CADD 岗位", 1)[1]
    assert "需求对接专员" not in section
    assert "对接公司" not in section
    assert "样例药企" not in body


def test_blank_url_with_a_source_stays_and_seed_row_does_not():
    report = _report()
    jobs = [
        _job(title="分子模拟工程师", url="", education="本科"),
        _job(title="CADD 样例", company="样例药企", source_type="", url="", source_url=""),
    ]
    _subject, body = report.build_report(jobs, {"started_at": STARTED, "sources": []}, [], now=NOW, today="2026-10-22")
    section = _section(body)
    assert "累计 <b>1</b> 条" in section
    assert "分子模拟工程师" in section
    assert "无链接" in section
    assert "样例药企" not in body
    assert "硕士可投数量首次统计，尚无上次可比。" in section


def test_master_trend_can_fall_or_stay_flat(tmp_path: Path):
    report = _report()
    jobs = [_job(education="博士"), _job(title="CADD Scientist", url="https://jobs.51job.com/shanghai/2.html")]
    state = tmp_path / "state"
    report.record_cadd_state(state, jobs)
    assert report.previous_master_eligible(state) == 1
    from jobsinsight.store import StateStore

    store = StateStore(state)
    assert store.cadd_report_state_path.parent == store.snapshot_path.parent
    assert store.cadd_report_state_path.name == "cadd_report_state.json"

    _subject, same = report.build_report(
        jobs,
        {"started_at": STARTED, "sources": []},
        [],
        now=NOW,
        today="2026-10-22",
        previous_master_eligible=report.previous_master_eligible(state),
    )
    assert "硕士可投与上次相同" in _section(same)

    _subject, fewer = report.build_report(
        [_job(education="博士")],
        {"started_at": STARTED, "sources": []},
        [],
        now=NOW,
        today="2026-10-22",
        previous_master_eligible=1,
    )
    assert "硕士可投比上次少 1 条" in _section(fewer)


def test_new_cadd_table_stops_after_twenty_rows():
    report = _report()
    jobs = [
        _job(
            title=f"CADD {index}",
            url=f"https://jobs.51job.com/shanghai/{index}.html",
            education="博士",
            relevance=100 - index,
        )
        for index in range(21)
    ]
    _subject, body = report.build_report(jobs, {"started_at": STARTED, "sources": []}, [], now=NOW, today="2026-10-22")
    section = _section(body)
    assert "新增 21 条，下表只列出前 20 条。" in section
    assert "CADD 0" in section
    assert "CADD 20" not in section
