"""Rule-based normalisation used when the LLM is disabled or unavailable.

Every LLM step in the pipeline has a deterministic fallback so a run never
fails just because an API key is missing or a request timed out. The rules are
also what the offline ``mock`` provider replays, which keeps the offline demo
close to the real output shape.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import EXPERIENCE_BUCKETS, RawPosting

# 医药健康 + AI 领域的技能词典：key 为标准写法，value 为匹配用的别名。
SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow", "tf2", "keras"),
    "深度学习": ("深度学习", "deep learning", "神经网络", "transformer"),
    "机器学习": ("机器学习", "machine learning", "sklearn", "xgboost"),
    "NLP": ("nlp", "自然语言", "大模型", "llm", "语言模型"),
    "计算机视觉": ("计算机视觉", "cv", "图像识别", "目标检测"),
    "医学影像": ("医学影像", "影像", "ct", "mri", "dicom", "病理切片"),
    "生物信息学": ("生物信息", "bioinformatics", "ngs", "测序"),
    "基因组学": ("基因组", "genomic", "转录组", "单细胞"),
    "分子生物学": ("分子生物", "细胞实验", "蛋白", "pcr"),
    "药物研发": ("药物研发", "药物发现", "靶点", "先导化合物", "aidd"),
    "临床知识": ("临床", "gcp", "ich", "受试者", "适应症"),
    "统计建模": ("统计建模", "生物统计", "sas", "回归", "假设检验"),
    "R语言": ("r语言", " r ", "rstudio"),
    "SQL": ("sql", "mysql", "postgres", "数据仓库"),
    "Spark": ("spark", "hadoop", "flink"),
    "数据分析": ("数据分析", "data analysis", "报表", "可视化"),
}

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI药物研发", ("药物", "靶点", "化合物", "aidd", "分子")),
    ("医学影像AI", ("影像", "ct", "mri", "病理", "放射")),
    ("临床数据科学", ("临床", "cro", "真实世界", "rwd", "统计")),
    ("生物信息", ("基因", "测序", "组学", "生物信息")),
    ("医疗大模型", ("大模型", "llm", "问诊", "知识图谱", "nlp")),
    ("智能医疗产品", ("产品", "运营", "解决方案", "售前")),
)

_SALARY_MONTHLY = re.compile(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*[kK千]")
_SALARY_YEARLY = re.compile(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*[wW万]")
_SALARY_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK千]")
_MONTH_COUNT = re.compile(r"(\d{1,2})\s*薪")
_YEARS = re.compile(r"(\d+)\s*[-~到至]?\s*(\d+)?\s*年")

SCALE_BUCKETS: tuple[tuple[int, str], ...] = (
    (20, "20-99"),
    (100, "100-499"),
    (500, "500-999"),
    (1000, "1000-5000"),
    (5000, "5000以上"),
)


def parse_salary(text: str) -> tuple[int, int]:
    """Return a ``(min, max)`` monthly salary in thousands of CNY.

    Handles ``25-40K``, ``30-60万/年`` (with an optional ``·14薪``) and single
    values such as ``40K``. Unparseable input yields ``(0, 0)`` so downstream
    aggregation can skip the posting instead of inventing numbers.
    """

    if not text:
        return (0, 0)
    normalised = text.replace(" ", "")

    match = _SALARY_MONTHLY.search(normalised)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return (round(low), round(high))

    match = _SALARY_YEARLY.search(normalised)
    if match:
        month_match = _MONTH_COUNT.search(normalised)
        months = max(12, min(24, int(month_match.group(1)))) if month_match else 12
        # 30万 == 300K per year; divide by the number of paid months.
        return (
            round(float(match.group(1)) * 10 / months),
            round(float(match.group(2)) * 10 / months),
        )

    match = _SALARY_SINGLE.search(normalised)
    if match:
        value = round(float(match.group(1)))
        return (value, value)
    return (0, 0)


def parse_experience(text: str) -> str:
    """Map free-form experience text onto the dashboard's five buckets."""

    if not text:
        return "1-3年"
    lowered = text.lower()
    if any(word in lowered for word in ("应届", "在校", "实习", "无经验", "不限")):
        return "应届"
    match = _YEARS.search(text)
    if not match:
        return "1-3年"
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) else low
    midpoint = (low + high) / 2
    if midpoint < 1:
        return "应届"
    if midpoint < 3:
        return "1-3年"
    if midpoint < 5:
        return "3-5年"
    if midpoint < 10:
        return "5-10年"
    return "10年以上"


def parse_education(text: str) -> str:
    for level in ("博士", "硕士", "本科", "大专"):
        if level in text:
            return level
    if "研究生" in text:
        return "硕士"
    return "本科"


def infer_job_level(title: str, experience: str, salary_max: int) -> str:
    lowered = title.lower()
    if any(word in title for word in ("首席", "总监", "负责人", "科学家")) or "head" in lowered:
        return "资深专家"
    if any(word in title for word in ("专家", "架构", "principal")):
        return "专家"
    if any(word in title for word in ("高级", "senior", "主管", "经理")):
        return "高级"
    if any(word in title for word in ("初级", "助理", "实习", "junior")):
        return "初级"
    if experience in ("5-10年", "10年以上") or salary_max >= 70:
        return "高级"
    if experience == "应届":
        return "初级"
    return "中级"


def extract_skills(*texts: str, limit: int = 8) -> list[str]:
    haystack = " ".join(t for t in texts if t).lower()
    found = [skill for skill, aliases in SKILL_KEYWORDS.items() if any(alias in haystack for alias in aliases)]
    return found[:limit]


def infer_category(*texts: str) -> str:
    """Classify a posting, giving the title priority over the description.

    Job descriptions list adjacent skills ("熟悉分子生物学") that would otherwise
    drag, say, a product role into the drug-discovery bucket.
    """

    for haystack in (texts[:1], texts):
        text = " ".join(t for t in haystack if t).lower()
        for category, keywords in CATEGORY_RULES:
            if any(keyword in text for keyword in keywords):
                return category
    return "其他"


def scale_bucket(text: str) -> tuple[str, int]:
    """Return ``(label, sortable_value)`` for a company headcount string."""

    if not text:
        return ("未知", 0)
    numbers = [int(n) for n in re.findall(r"\d+", text.replace("万", "0000"))]
    if not numbers:
        return (text, 0)
    upper = max(numbers)
    label = text if any(sep in text for sep in "-~") else None
    for threshold, bucket in reversed(SCALE_BUCKETS):
        if upper >= threshold:
            return (label or bucket, min(100, int(upper**0.5)))
    return (label or "少于20", min(100, upper))


def relevance_score(title: str, description: str, skills: Iterable[str]) -> int:
    """0-100 score for "医药健康 + AI" fit, used to drop off-topic postings."""

    haystack = f"{title} {description}".lower()
    health_hits = sum(
        1
        for word in ("医", "药", "临床", "健康", "生物", "基因", "诊断", "病", "护理", "pharma", "clinical", "health")
        if word in haystack
    )
    ai_hits = sum(
        1
        for word in ("ai", "人工智能", "算法", "模型", "机器学习", "深度学习", "数据", "大模型", "nlp")
        if word in haystack
    )
    # A posting needs both halves of "医药健康 + AI" to score well; skills only
    # top it up so a keyword-stuffed description cannot fake relevance.
    skill_bonus = min(10, 3 * len(list(skills)))
    score = min(45, health_hits * 15) + min(45, ai_hits * 15) + skill_bonus
    return int(min(100, score))


def summarise(posting: RawPosting, skills: list[str], category: str) -> str:
    """Short one-line summary; the LLM usually replaces this with a better one."""

    if posting.description:
        first = re.split(r"[。；;\n]", posting.description.strip())[0]
        if 6 <= len(first) <= 60:
            return first
    skill_text = "、".join(skills[:3]) if skills else posting.title
    return f"{category}方向，重点关注{skill_text}"


def normalise(posting: RawPosting) -> dict[str, object]:
    """Full heuristic enrichment of one posting."""

    salary_min, salary_max = parse_salary(posting.salary_text)
    experience = parse_experience(posting.experience_text or posting.description)
    skills = extract_skills(posting.title, posting.description, posting.salary_text)
    category = infer_category(posting.title, posting.description)
    scale_label, scale_value = scale_bucket(posting.company_scale)
    return {
        "salary_min": salary_min,
        "salary_max": salary_max,
        "experience": experience if experience in EXPERIENCE_BUCKETS else "1-3年",
        "education": parse_education(posting.education_text or posting.description),
        "job_level": infer_job_level(posting.title, experience, salary_max),
        "skills": skills,
        "category": category,
        "summary": summarise(posting, skills, category),
        "relevance": relevance_score(posting.title, posting.description, skills),
        "company_scale": scale_label,
        "company_scale_value": scale_value,
    }
