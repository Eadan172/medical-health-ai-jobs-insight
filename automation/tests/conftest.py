from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobsinsight.config import Config, LLMSettings, OutputSettings, ScheduleSettings, ServerSettings, SourceSettings

SAMPLE_POSTINGS = [
    {
        "source_id": "a-1",
        "platform": "51job",
        "title": "高级医学影像算法工程师",
        "company": "联影智能",
        "city": "上海",
        "salary_text": "40-60K·14薪",
        "experience_text": "5-8年经验",
        "education_text": "硕士及以上",
        "company_scale": "1000-5000人",
        "company_level": "上市公司",
        "description": "负责 CT/MRI 医学影像的深度学习模型研发，熟悉 PyTorch 与分割算法。",
        "publish_date": "2026-02-01",
    },
    {
        "source_id": "a-2",
        "platform": "Boss直聘",
        "title": "AI药物研发工程师",
        "company": "晶泰科技",
        "city": "深圳",
        "salary_text": "30-45K",
        "experience_text": "3-5年",
        "education_text": "博士",
        "company_scale": "500-999人",
        "description": "靶点预测与化合物设计，使用机器学习加速药物发现，需要 Python 与分子生物学基础。",
        "publish_date": "2026-02-02",
    },
    {
        "source_id": "a-3",
        "platform": "猎聘网",
        "title": "前台行政",
        "company": "某贸易公司",
        "city": "北京",
        "salary_text": "5-7K",
        "experience_text": "应届",
        "description": "负责接待与文档整理。",
        "publish_date": "2026-02-03",
    },
]


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    path = tmp_path / "postings.json"
    path.write_text(json.dumps(SAMPLE_POSTINGS, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def config(tmp_path: Path, seed_file: Path) -> Config:
    return Config(
        schedule=ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="Asia/Shanghai"),
        llm=LLMSettings(enabled=True, provider="mock", model="mock-1", batch_size=2),
        sources=[SourceSettings(name="seed", type="fixture", path=str(seed_file))],
        output=OutputSettings(
            data_dir=str(tmp_path / "data"),
            state_dir=str(tmp_path / "state"),
            min_relevance=30,
        ),
        server=ServerSettings(host="127.0.0.1", port=0),
        project_root=tmp_path,
    ).validate()
