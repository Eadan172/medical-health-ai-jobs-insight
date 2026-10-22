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
        ("3.5-5万", (35, 50)),
        ("3-4万·15薪", (30, 40)),
        ("36-48万·12薪", (360, 480)),
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
        ("8+ years", "5-10年"),
        ("5-10 years of experience", "5-10年"),
        ("", ""),
        ("Lead the platform", ""),
    ],
)
def test_parse_experience(text: str, expected: str):
    assert heuristics.parse_experience(text) == expected


def test_parse_education_prefers_the_highest_mentioned_level():
    assert heuristics.parse_education("硕士及以上，博士优先") == "博士"
    assert heuristics.parse_education("研究生学历") == "硕士"
    assert heuristics.parse_education("学历不限") == ""
    assert heuristics.parse_education("") == ""
    assert heuristics.parse_education("PhD or equivalent") == "博士"
    assert heuristics.parse_education("Master's degree") == "硕士"


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
    # "ct" inside director/function/product/infrastructure must not become 医学影像AI.
    assert (
        heuristics.infer_category(
            "Senior Staff Data Engineer - Data & ML Platform",
            "Own the data platform, ML infrastructure, and production functions.",
        )
        == "其他"
    )
    assert heuristics.infer_category("Data Scientist", "machine learning for claims and product analytics") == "其他"
    assert heuristics.infer_category("Senior AI Engineer", "Build ambient documentation software at Suki") == "其他"
    assert heuristics.infer_category("MLOps Engineer", "Deploy models and operate the platform") == "其他"
    assert heuristics.infer_category("Senior Machine Learning Scientist, Imaging", "CT and MRI models") == "医学影像AI"
    assert heuristics.infer_category("CADD Scientist", "") == "AI药物研发"
    assert heuristics.infer_category("计算机辅助药物设计工程师", "") == "AI药物研发"
    assert heuristics.infer_category("计算化学研究员", "") == "AI药物研发"
    assert heuristics.infer_category("分子模拟工程师", "") == "AI药物研发"
    assert heuristics.infer_category("Computational Chemist", "molecular dynamics") == "AI药物研发"
    assert heuristics.infer_category("需求对接专员", "负责客户对接与需求整理") == "其他"
    assert heuristics.infer_category("化学分析员", "实验室样品分析") == "其他"


def test_cadd_focus_reuses_category_and_phrases():
    assert heuristics.matches_cadd_focus({"title": "计算化学研究员", "category": "其他"})
    assert heuristics.matches_cadd_focus({"title": "CADD Scientist"})
    assert heuristics.matches_cadd_focus({"title": "算法工程师", "category": "AI制药"})
    assert heuristics.matches_cadd_focus({"title": "算法工程师", "summary": "计算机辅助药物设计"})
    assert not heuristics.matches_cadd_focus({"title": "需求对接专员", "description": "负责客户对接与需求整理"})
    assert not heuristics.matches_cadd_focus({"title": "caddy operator", "description": "golf club"})


def test_relevance_separates_on_topic_from_off_topic_postings():
    on_topic = heuristics.relevance_score("医学影像算法工程师", "使用深度学习完成 CT 病灶检测", ["PyTorch", "医学影像"])
    off_topic = heuristics.relevance_score("前台行政", "负责接待与文档整理", [])
    assert on_topic >= 60
    assert off_topic < 30
    assert heuristics.relevance_score("计算化学研究员", "", []) >= 30
    assert heuristics.relevance_score("CADD Scientist", "", []) >= 30
    assert heuristics.relevance_score("需求对接专员", "负责客户对接", []) < 30


def test_bare_wan_and_pay_count_are_monthly_but_explicit_year_stays_annual():
    bare = heuristics.parse_salary_quote("3.5-5万")
    assert bare is not None
    assert (bare.currency, bare.period, bare.unit) == ("CNY", "month", "k")
    assert (bare.low, bare.high) == (35, 50)
    assert bare.pay_months == 0

    paid = heuristics.parse_salary_quote("3-4万·15薪")
    assert paid is not None
    assert (paid.currency, paid.period, paid.unit) == ("CNY", "month", "k")
    assert (paid.low, paid.high) == (30, 40)
    assert paid.pay_months == 15
    assert heuristics.parse_salary("3-4万·15薪") == (30, 40)

    per_year = heuristics.parse_salary_quote("30-60万/年")
    assert per_year is not None
    assert (per_year.currency, per_year.period, per_year.unit) == ("CNY", "year", "wan")
    assert (per_year.low, per_year.high) == (30, 60)

    named = heuristics.parse_salary_quote("年薪40-80万")
    assert named is not None
    assert (named.currency, named.period, named.unit) == ("CNY", "year", "wan")
    assert (named.low, named.high) == (40, 80)
    assert heuristics.parse_salary("年薪40-80万") == (33, 67)


def test_usd_annual_is_not_stored_as_monthly_cny():
    quote = heuristics.parse_salary_quote("$240K - $360K")
    assert quote is not None
    assert (quote.currency, quote.period) == ("USD", "year")
    assert (quote.low, quote.high) == (240, 360)
    assert heuristics.parse_salary("$240K - $360K") == (0, 0)
    assert heuristics.parse_salary("$240,000–$360,000/年") == (0, 0)
    assert heuristics.parse_salary("2-4万/月") == (20, 40)


def test_unparsed_senior_title_does_not_invent_experience_or_degree():
    posting = RawPosting(
        title="Staff Machine Learning Scientist",
        company="Freenome",
        city="Remote",
        description="Own model development and the production platform.",
        salary_text="$240K - $360K",
    )
    result = heuristics.normalise(posting)
    assert result["experience"] == ""
    assert result["education"] == ""
    assert result["category"] == "其他"
    assert result["salary_min"] == 0


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
