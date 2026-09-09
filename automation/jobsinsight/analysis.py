"""Aggregates jobs into the ``stats.json`` payload the dashboard renders.

Pure functions only: given the same jobs, the output is byte-identical, which
keeps the committed data diffable and the tests simple.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from .models import EXPERIENCE_BUCKETS, Job, RunDiff, today_iso

#: (label, lower bound inclusive, upper bound exclusive) on the average monthly salary in K.
SALARY_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("15K以下", 0, 15),
    ("15-25K", 15, 25),
    ("25-35K", 25, 35),
    ("35-50K", 35, 50),
    ("50-70K", 50, 70),
    ("70-100K", 70, 100),
    ("100K+", 100, float("inf")),
)


def salary_bucket(avg_salary: float) -> str | None:
    if avg_salary <= 0:
        return None
    for label, low, high in SALARY_BUCKETS:
        if low <= avg_salary < high:
            return label
    return SALARY_BUCKETS[-1][0]


def _avg(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def _count_avg_stats(jobs: Iterable[Job], key: str) -> dict[str, dict[str, float]]:
    counts: Counter[str] = Counter()
    salaries: dict[str, list[float]] = defaultdict(list)
    for job in jobs:
        group = str(getattr(job, key) or "未知")
        counts[group] += 1
        if job.avg_salary > 0:
            salaries[group].append(job.avg_salary)
    return {
        group: {"count": count, "avg_salary": _avg(salaries[group])}
        for group, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    }


def _ordered_experience_stats(jobs: Sequence[Job]) -> dict[str, dict[str, float]]:
    stats = _count_avg_stats(jobs, "experience")
    ordered = {bucket: stats[bucket] for bucket in EXPERIENCE_BUCKETS if bucket in stats}
    ordered.update({key: value for key, value in stats.items() if key not in ordered})
    return ordered


def skill_stats(jobs: Iterable[Job], *, limit: int = 24) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for job in jobs:
        counter.update({skill for skill in job.skills if skill})
    return dict(counter.most_common(limit))


def category_stats(jobs: Iterable[Job], *, limit: int = 12) -> dict[str, int]:
    counter: Counter[str] = Counter(job.category or "其他" for job in jobs)
    return dict(counter.most_common(limit))


def salary_distribution(jobs: Sequence[Job]) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    grouped: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        bucket = salary_bucket(job.avg_salary)
        if bucket:
            grouped[bucket].append(job)

    distribution: dict[str, int] = {}
    detail: dict[str, dict[str, Any]] = {}
    for label, _, _ in SALARY_BUCKETS:
        bucket_jobs = grouped.get(label)
        if not bucket_jobs:
            continue
        distribution[label] = len(bucket_jobs)
        top_city, top_city_count = Counter(job.city for job in bucket_jobs).most_common(1)[0]
        top_title, top_title_count = Counter(job.title for job in bucket_jobs).most_common(1)[0]
        detail[label] = {
            "count": len(bucket_jobs),
            "top_city": top_city,
            "top_city_count": top_city_count,
            "top_title": top_title,
            "top_title_count": top_title_count,
        }
    return distribution, detail


def build_stats(jobs: Sequence[Job], diff: RunDiff | None = None, *, run_date: str | None = None) -> dict[str, Any]:
    active = [job for job in jobs if job.status != "deleted"]
    diff = diff or RunDiff()
    distribution, distribution_detail = salary_distribution(active)
    salaries = [job.avg_salary for job in active if job.avg_salary > 0]

    return {
        "total_jobs": len(active),
        "last_update": run_date or today_iso(),
        "new_jobs_today": diff.new_jobs,
        "updated_jobs_today": diff.updated_jobs,
        "deleted_jobs_today": diff.deleted_jobs,
        "avg_salary": _avg(salaries),
        "platform_stats": _count_avg_stats(active, "platform"),
        "city_stats": _count_avg_stats(active, "city"),
        "skill_stats": skill_stats(active),
        "experience_stats": _ordered_experience_stats(active),
        "education_stats": _count_avg_stats(active, "education"),
        "job_level_stats": _count_avg_stats(active, "job_level"),
        "category_stats": category_stats(active),
        "salary_distribution": distribution,
        "salary_distribution_detail": distribution_detail,
    }


def diff_jobs(previous: Sequence[dict[str, Any]], current: Sequence[Job]) -> RunDiff:
    """Compare against the previous snapshot to fill the "今日" counters."""

    def key_of(entry: Any) -> str:
        if isinstance(entry, dict):
            return str(entry.get("fingerprint") or f"{entry.get('company')}|{entry.get('title')}".lower())
        return entry.fingerprint or f"{entry.company}|{entry.title}".lower()

    previous_by_key = {key_of(entry): entry for entry in previous}
    current_keys = set()
    diff = RunDiff()

    for job in current:
        key = key_of(job)
        current_keys.add(key)
        old = previous_by_key.get(key)
        if old is None:
            diff.new_jobs += 1
        elif _materially_changed(old, job):
            diff.updated_jobs += 1
            job.status = "updated"
        else:
            diff.unchanged_jobs += 1
            job.update_date = str(old.get("update_date") or job.update_date)

    diff.deleted_jobs = len(set(previous_by_key) - current_keys)
    return diff


def _materially_changed(old: dict[str, Any], new: Job) -> bool:
    return any(
        [
            int(old.get("salary_min") or 0) != new.salary_min,
            int(old.get("salary_max") or 0) != new.salary_max,
            str(old.get("experience") or "") != new.experience,
            str(old.get("job_level") or "") != new.job_level,
            sorted(map(str, old.get("skills") or [])) != sorted(new.skills),
        ]
    )
