"""Seed rows with no source and no URL must not survive the local snapshot."""

from __future__ import annotations

import json

from jobsinsight.job_store import is_sample_record, without_sample_jobs
from jobsinsight.models import Job
from jobsinsight.pipeline import Pipeline


def test_blank_source_and_url_is_a_sample_row():
    seed = {
        "title": "药物发现AI专家",
        "company": "医渡科技",
        "platform": "猎聘网",
        "city": "深圳",
        "source_type": "",
        "url": "",
        "source_url": "",
        "first_seen_at": "2026-10-01T20:51:25+00:00",
    }
    kept = {
        "id": 1,
        "title": "医学影像算法工程师",
        "company": "联影智能",
        "platform": "51job",
        "city": "上海",
        "source_type": "51job",
        "url": "",
    }
    assert is_sample_record(seed)
    assert is_sample_record(Job.from_dict(dict(seed)))
    assert not is_sample_record(kept)
    assert not is_sample_record(Job.from_dict(kept))
    assert [job.title for job in without_sample_jobs([Job.from_dict(dict(seed)), Job.from_dict(kept)])] == [
        "医学影像算法工程师"
    ]


def test_existing_jobs_drop_seed_rows_from_the_file_and_the_snapshot(config):
    seed = {
        "title": "药物发现AI专家",
        "company": "医渡科技",
        "platform": "猎聘网",
        "city": "深圳",
        "source_type": "",
        "url": "",
        "first_seen_at": "2026-10-01T20:51:25+00:00",
    }
    real = {
        "title": "医学影像算法工程师",
        "company": "联影智能",
        "platform": "51job",
        "city": "上海",
        "source_type": "51job",
        "url": "https://jobs.51job.com/shanghai/1.html",
    }
    config.data_dir.mkdir(parents=True, exist_ok=True)
    (config.data_dir / "jobs.json").write_text(json.dumps([seed, real], ensure_ascii=False), encoding="utf-8")
    pipeline = Pipeline(config)
    pipeline.store.save_snapshot([seed, real])

    assert [job.title for job in pipeline._existing_jobs()] == ["医学影像算法工程师"]
