from __future__ import annotations

import pytest

from jobsinsight import analysis
from jobsinsight.models import Job, RunDiff


def job(**overrides) -> Job:
    defaults = {
        "id": 1,
        "platform": "51job",
        "title": "医学影像算法工程师",
        "company": "联影智能",
        "city": "上海",
        "salary_min": 30,
        "salary_max": 40,
        "experience": "3-5年",
        "education": "硕士",
        "job_level": "高级",
        "skills": ["PyTorch", "医学影像"],
        "category": "医学影像AI",
    }
    return Job(**{**defaults, **overrides})


@pytest.mark.parametrize(
    ("avg", "expected"),
    [(0, None), (12, "15K以下"), (20, "15-25K"), (25, "25-35K"), (49.9, "35-50K"), (85, "70-100K"), (250, "100K+")],
)
def test_salary_bucket_boundaries(avg: float, expected: str | None):
    assert analysis.salary_bucket(avg) == expected


def test_build_stats_matches_the_dashboard_contract():
    jobs = [
        job(id=1, salary_min=30, salary_max=40),
        job(id=2, platform="Boss直聘", city="深圳", salary_min=60, salary_max=80, experience="5-10年"),
        job(id=3, platform="Boss直聘", city="深圳", salary_min=0, salary_max=0, experience="应届"),
    ]
    stats = analysis.build_stats(jobs, RunDiff(new_jobs=2, updated_jobs=1, deleted_jobs=3), run_date="2026-03-01")

    assert stats["total_jobs"] == 3
    assert stats["last_update"] == "2026-03-01"
    assert stats["new_jobs_today"] == 2
    assert stats["updated_jobs_today"] == 1
    assert stats["deleted_jobs_today"] == 3
    assert stats["platform_stats"]["Boss直聘"]["count"] == 2
    # Postings without a salary are counted but excluded from the average.
    assert stats["platform_stats"]["Boss直聘"]["avg_salary"] == 70.0
    assert stats["city_stats"]["深圳"]["count"] == 2
    assert stats["skill_stats"]["PyTorch"] == 3
    assert stats["salary_distribution"] == {"35-50K": 1, "70-100K": 1}
    assert stats["salary_distribution_detail"]["35-50K"]["top_city"] == "上海"
    assert stats["category_stats"] == {"医学影像AI": 3}


def test_experience_stats_keep_the_dashboard_order():
    jobs = [job(id=1, experience="10年以上"), job(id=2, experience="应届"), job(id=3, experience="3-5年")]
    stats = analysis.build_stats(jobs)
    assert list(stats["experience_stats"]) == ["应届", "3-5年", "10年以上"]


def test_deleted_jobs_are_excluded_from_aggregation():
    stats = analysis.build_stats([job(id=1), job(id=2, status="deleted")])
    assert stats["total_jobs"] == 1


def test_diff_detects_new_updated_unchanged_and_deleted():
    previous = [
        job(id=1, fingerprint="a").as_dict(),
        job(id=2, fingerprint="b", salary_min=20, salary_max=30).as_dict(),
        job(id=3, fingerprint="gone").as_dict(),
    ]
    current = [
        job(id=1, fingerprint="a"),
        job(id=2, fingerprint="b", salary_min=25, salary_max=35),
        job(id=3, fingerprint="new"),
    ]

    diff = analysis.diff_jobs(previous, current)

    assert diff.unchanged_jobs == 1
    assert diff.updated_jobs == 1
    assert diff.new_jobs == 1
    assert diff.deleted_jobs == 1
    assert current[1].status == "updated"


def test_diff_against_an_empty_snapshot_marks_everything_new():
    diff = analysis.diff_jobs([], [job(id=1, fingerprint="a"), job(id=2, fingerprint="b")])
    assert diff.new_jobs == 2
    assert diff.deleted_jobs == 0


def test_skill_stats_are_capped_and_sorted():
    jobs = [job(id=index, skills=[f"skill-{index % 3}"]) for index in range(9)]
    stats = analysis.skill_stats(jobs, limit=2)
    assert len(stats) == 2
    assert all(count == 3 for count in stats.values())
