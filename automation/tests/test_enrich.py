from __future__ import annotations

from typing import Any

from jobsinsight.config import LLMSettings
from jobsinsight.enrich import Enricher, summarise_stats
from jobsinsight.llm import LLMClient, MockProvider
from jobsinsight.models import RawPosting

POSTING = RawPosting(
    source_id="1",
    platform="51job",
    title="医学影像算法工程师",
    company="联影智能",
    city="上海",
    salary_text="30-45K",
    experience_text="3-5年",
    education_text="硕士",
    description="CT 影像分割，PyTorch。",
)


def enrich_with(response: dict[str, Any]) -> Any:
    """Enrich one posting with a scripted LLM reply and return the job."""

    import json

    provider = MockProvider(scripted=[json.dumps({"results": [response]}, ensure_ascii=False)])
    enricher = Enricher(LLMSettings(provider="mock"), LLMClient(provider))
    return enricher.enrich([POSTING])[0]


def test_valid_llm_fields_replace_the_heuristics():
    job = enrich_with(
        {
            "source_id": "1",
            "salary_min": 35,
            "salary_max": 55,
            "experience": "5-10年",
            "education": "博士",
            "job_level": "专家",
            "skills": ["医学影像", "PyTorch", "分割算法"],
            "category": "医学影像AI",
            "summary": "负责 CT 影像分割模型",
            "relevance": 92,
        }
    )

    assert (job.salary_min, job.salary_max) == (35, 55)
    assert job.experience == "5-10年"
    assert job.education == "博士"
    assert job.job_level == "专家"
    assert job.skills == ["医学影像", "PyTorch", "分割算法"]
    assert job.summary == "负责 CT 影像分割模型"
    assert job.relevance == 92
    assert job.enriched_by == "llm"


def test_values_outside_the_vocabulary_are_ignored():
    job = enrich_with(
        {
            "source_id": "1",
            "experience": "大概五年吧",
            "education": "小学",
            "job_level": "God Mode",
            "relevance": 900,
        }
    )

    # Falls back to what the rules derived from the raw text.
    assert job.experience == "3-5年"
    assert job.education == "硕士"
    assert job.job_level == "中级"
    assert job.relevance < 100


def test_absurd_salaries_are_ignored():
    job = enrich_with({"source_id": "1", "salary_min": 9000, "salary_max": 90000})
    assert (job.salary_min, job.salary_max) == (30, 45)


def test_inverted_salary_range_is_ignored():
    job = enrich_with({"source_id": "1", "salary_min": 80, "salary_max": 20})
    assert (job.salary_min, job.salary_max) == (30, 45)


def test_string_numbers_are_accepted():
    job = enrich_with({"source_id": "1", "salary_min": "40K", "salary_max": "60"})
    assert (job.salary_min, job.salary_max) == (40, 60)


def test_empty_llm_result_leaves_a_complete_job():
    job = enrich_with({"source_id": "1"})
    assert job.salary_min == 30
    assert job.skills
    assert job.summary


def test_summary_and_skills_are_cleaned_up():
    job = enrich_with(
        {
            "source_id": "1",
            "skills": ["  PyTorch  ", "PyTorch", "", "医学影像"],
            "summary": "  多余   空白  ",
        }
    )
    assert job.skills == ["PyTorch", "医学影像"]
    assert job.summary == "多余 空白"


def test_rule_based_insight_describes_the_dataset():
    stats = {
        "total_jobs": 120,
        "new_jobs_today": 8,
        "avg_salary": 52.4,
        "city_stats": {"上海": {"count": 40, "avg_salary": 70.0}, "北京": {"count": 30, "avg_salary": 80.0}},
        "skill_stats": {"PyTorch": 60, "医学影像": 45, "SQL": 20},
        "experience_stats": {"应届": {"count": 10, "avg_salary": 20.0}, "10年以上": {"count": 5, "avg_salary": 100.0}},
    }

    insight = summarise_stats(stats)

    assert insight["source"] == "rules"
    assert "120" in insight["headline"]
    assert "上海" in insight["headline"]  # most postings
    assert any("北京薪资最高" in item for item in insight["highlights"])  # highest average
    assert any("5.0 倍" in item for item in insight["highlights"])
    assert insight["hot_skills"][0] == "PyTorch"
    assert insight["advice"]


def test_rule_based_insight_survives_an_empty_dataset():
    insight = summarise_stats({"total_jobs": 0})
    assert insight["headline"]
    assert insight["hot_skills"] == []


def test_enricher_reports_llm_usage():
    enricher = Enricher(LLMSettings(provider="mock"), LLMClient(MockProvider()))
    enricher.enrich([POSTING])
    report = enricher.stats_report()

    assert report["llm_enriched"] == 1
    assert report["heuristic_enriched"] == 0
    assert report["llm"]["calls"] == 1
    assert report["llm"]["total_tokens"] > 0


def test_max_jobs_per_run_limits_the_llm_budget():
    postings = [RawPosting(source_id=str(index), platform="p", title=f"AI 医疗岗位 {index}") for index in range(6)]
    enricher = Enricher(LLMSettings(provider="mock", max_jobs_per_run=2, batch_size=2), LLMClient(MockProvider()))

    jobs = enricher.enrich(postings)

    assert [job.enriched_by for job in jobs] == ["llm", "llm", *["heuristic"] * 4]
