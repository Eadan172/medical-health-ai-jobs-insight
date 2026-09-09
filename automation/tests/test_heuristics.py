from __future__ import annotations

import pytest

from jobsinsight import heuristics
from jobsinsight.models import RawPosting


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("25-40K", (25, 40)),
        ("25-40K·14薪", (25, 40)),
        ("30~45k/月", (30, 45)),
        ("40K", (40, 40)),
        ("30-60万/年", (25, 50)),
        ("36-48万·12薪", (30, 40)),
        ("薪资面议", (0, 0)),
        ("", (0, 0)),
    ],
)
def test_parse_salary(text: str, expected: tuple[int, int]):
    assert heuristics.parse_salary(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("应届生", "应届"),
        ("经验不限", "应届"),
        ("1-3年经验", "1-3年"),
        ("3-5年", "3-5年"),
        ("5-8年经验", "5-10年"),
        ("12年以上", "10年以上"),
        ("", "1-3年"),
    ],
)
def test_parse_experience(text: str, expected: str):
    assert heuristics.parse_experience(text) == expected


def test_parse_education_prefers_the_highest_mentioned_level():
    assert heuristics.parse_education("硕士及以上，博士优先") == "博士"
    assert heuristics.parse_education("研究生学历") == "硕士"
    assert heuristics.parse_education("学历不限") == "本科"


def test_infer_job_level_from_title_then_experience():
    assert heuristics.infer_job_level("首席科学家", "3-5年", 40) == "资深专家"
    assert heuristics.infer_job_level("算法专家", "3-5年", 40) == "专家"
    assert heuristics.infer_job_level("高级算法工程师", "1-3年", 30) == "高级"
    assert heuristics.infer_job_level("算法工程师", "5-10年", 60) == "高级"
    assert heuristics.infer_job_level("算法工程师", "应届", 15) == "初级"
    assert heuristics.infer_job_level("算法工程师", "1-3年", 25) == "中级"


def test_extract_skills_maps_aliases_to_canonical_names():
    skills = heuristics.extract_skills("医学影像算法工程师", "熟悉 pytorch、CT 影像分割与深度学习，了解 mysql")
    assert "PyTorch" in skills
    assert "医学影像" in skills
    assert "深度学习" in skills
    assert "SQL" in skills


def test_infer_category():
    assert heuristics.infer_category("AI药物研发工程师", "靶点预测") == "AI药物研发"
    assert heuristics.infer_category("影像算法工程师", "CT 分割") == "医学影像AI"
    assert heuristics.infer_category("行政专员", "接待") == "其他"


def test_relevance_separates_on_topic_from_off_topic_postings():
    on_topic = heuristics.relevance_score("医学影像算法工程师", "使用深度学习完成 CT 病灶检测", ["PyTorch", "医学影像"])
    off_topic = heuristics.relevance_score("前台行政", "负责接待与文档整理", [])
    assert on_topic >= 60
    assert off_topic < 30


def test_scale_bucket():
    assert heuristics.scale_bucket("1000-5000人")[0] == "1000-5000人"
    assert heuristics.scale_bucket("10000人以上")[0] == "5000以上"
    assert heuristics.scale_bucket("") == ("未知", 0)


def test_normalise_produces_every_field_the_job_model_needs():
    posting = RawPosting(
        source_id="1",
        platform="51job",
        title="高级医学影像算法工程师",
        company="联影智能",
        city="上海",
        salary_text="40-60K·14薪",
        experience_text="5-8年经验",
        education_text="硕士及以上",
        company_scale="1000-5000人",
        description="负责 CT/MRI 影像的深度学习模型研发，熟悉 PyTorch。",
    )
    result = heuristics.normalise(posting)
    assert result["salary_min"] == 40
    assert result["salary_max"] == 60
    assert result["experience"] == "5-10年"
    assert result["education"] == "硕士"
    assert result["job_level"] == "高级"
    assert result["category"] == "医学影像AI"
    assert result["summary"]
    assert result["relevance"] > 50
