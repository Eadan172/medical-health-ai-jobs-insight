"""Rule-based normalisation used when the LLM is disabled or unavailable.

Every LLM step in the pipeline has a deterministic fallback so a run never
fails just because an API key is missing or a request timed out. The rules are
also what the offline ``mock`` provider replays, which keeps the offline demo
close to the real output shape.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .models import EXPERIENCE_BUCKETS, RawPosting

# 医药健康 + AI 领域的技能词典：key 为标准写法，value 为匹配用的别名。
SKILL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "PyTorch": ("pytorch", "torch"),
    "TensorFlow": ("tensorflow", "tf2", "keras"),
    "深度学习": ("深度学习", "deep learning", "deep-learning", "神经网络", "transformer"),
    "机器学习": ("机器学习", "machine learning", "machine-learning", "sklearn", "xgboost"),
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
    ("AI药物研发", ("药物", "靶点", "化合物", "aidd", "drug discovery", "drug design")),
    ("医学影像AI", ("影像", "病理", "放射", "dicom", "radiology", "pathology", "imaging", "ct", "mri")),
    ("临床数据科学", ("临床", "cro", "真实世界", "rwd", "生物统计", "clinical trial", "clinical data")),
    ("生物信息", ("基因", "测序", "组学", "生物信息", "bioinformatic", "genomic")),
    ("医疗大模型", ("大模型", "llm", "问诊", "知识图谱", "语言模型")),
    ("智能医疗产品", ("产品经理", "产品运营", "解决方案", "售前")),
)

_SALARY_MONTHLY = re.compile(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*[kK千]")
_SALARY_YEARLY = re.compile(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*[wW万]")
_SALARY_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*[kK千]")
_MONTH_COUNT = re.compile(r"(\d{1,2})\s*薪")
_USD_K = re.compile(r"\$(\d+(?:\.\d+)?)[kK](?:[-~–—到至]\$?(\d+(?:\.\d+)?)[kK])?")
_USD_FULL = re.compile(r"\$([\d,]{4,})(?:[-~–—到至]\$?([\d,]{4,}))?")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*[-~到至]?\s*(\d{1,2})?\s*年")
_EN_YEARS = re.compile(
    r"(?<!\d)(\d{1,2})\s*(\+|plus)?\s*(?:[-~–—]|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)

SCALE_BUCKETS: tuple[tuple[int, str], ...] = (
    (20, "20-99"),
    (100, "100-499"),
    (500, "500-999"),
    (1000, "1000-5000"),
    (5000, "5000以上"),
)


@dataclass(frozen=True)
class SalaryQuote:
    """One salary range in its own currency and pay period.

    ``low`` / ``high`` use ``unit``: ``k`` is thousands, ``wan`` is 万.
    USD amounts are not converted into CNY, and a year is not rewritten as a month.
    """

    low: float
    high: float
    currency: str  # CNY | USD
    period: str  # month | year
    unit: str  # k | wan

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


def parse_salary_quote(text: str) -> SalaryQuote | None:
    """Parse a salary string without mixing currencies or pay periods."""

    if not text or not text.strip():
        return None
    compact = re.sub(r"\s+", "", text)
    if "$" in text or "USD" in text.upper() or "美元" in text:
        return _parse_usd(compact)
    return _parse_cny(text, compact)


def parse_salary(text: str) -> tuple[int, int]:
    """Return a ``(min, max)`` monthly salary in thousands of CNY.

    Handles ``25-40K``, ``30-60万/年`` (with an optional ``·14薪``), ``2-4万/月``
    and single values such as ``40K``. USD ranges and unparseable input yield
    ``(0, 0)`` so they are not stored as monthly CNY.
    """

    quote = parse_salary_quote(text)
    if quote is None or quote.currency != "CNY":
        return (0, 0)
    if quote.period == "month":
        return (round(quote.low), round(quote.high))
    compact = re.sub(r"\s+", "", text)
    month_match = _MONTH_COUNT.search(compact)
    months = max(12, min(24, int(month_match.group(1)))) if month_match else 12
    # 30万 == 300K per year; divide by the number of paid months.
    return (round(quote.low * 10 / months), round(quote.high * 10 / months))


def _parse_usd(compact: str) -> SalaryQuote | None:
    """US job-board figures marked ``$`` / ``K`` are annual, including ``$240K - $360K``."""

    match = _USD_K.search(compact)
    if match:
        low = float(match.group(1))
        high = float(match.group(2) or low)
        if high < low:
            low, high = high, low
        return SalaryQuote(low, high, "USD", "year", "k")
    match = _USD_FULL.search(compact)
    if not match:
        return None
    low = int(match.group(1).replace(",", "")) / 1000
    high = int(match.group(2).replace(",", "")) / 1000 if match.group(2) else low
    if high < low:
        low, high = high, low
    if low < 10:
        return None
    return SalaryQuote(low, high, "USD", "year", "k")


def _parse_cny(original: str, compact: str) -> SalaryQuote | None:
    match = _SALARY_MONTHLY.search(compact)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return SalaryQuote(low, high, "CNY", "month", "k")

    match = _SALARY_YEARLY.search(compact)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        # 「2-4万/月」 is monthly; 「30-60万/年」 and 「36-48万·12薪」 stay annual.
        if "月" in compact and "年" not in original and "年" not in compact:
            return SalaryQuote(low * 10, high * 10, "CNY", "month", "k")
        return SalaryQuote(low, high, "CNY", "year", "wan")

    match = _SALARY_SINGLE.search(compact)
    if match:
        value = float(match.group(1))
        return SalaryQuote(value, value, "CNY", "month", "k")
    return None


def parse_experience(text: str) -> str:
    """Map free-form experience text onto the dashboard's five buckets.

    Returns ``""`` when the text does not state a tenure. Callers must not
    substitute a default such as ``1-3年``.
    """

    if not text or not text.strip():
        return ""
    lowered = text.lower()
    if any(word in lowered for word in ("应届", "在校", "实习", "无经验", "经验不限", "不限经验")):
        return "应届"
    match = _YEARS.search(text)
    if match:
        high = int(match.group(2)) if match.group(2) else None
        return _bucket_years(int(match.group(1)), high)
    match = _EN_YEARS.search(lowered)
    if not match:
        return ""
    low = int(match.group(1))
    high = int(match.group(3)) if match.group(3) else None
    if match.group(2) and high is None:
        high = low
    return _bucket_years(low, high)


def _bucket_years(low: int, high: int | None) -> str:
    if low > 40:
        return ""
    upper = high if high is not None else low
    midpoint = (low + upper) / 2
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
    """Return a degree bucket, or ``""`` when the posting does not state one."""

    if not text or not text.strip():
        return ""
    for level in ("博士", "硕士", "本科", "大专"):
        if level in text:
            return level
    if "研究生" in text:
        return "硕士"
    lowered = text.lower()
    if re.search(r"ph\.?\s*d|doctorate", lowered):
        return "博士"
    if re.search(r"master'?s|\bmsc\b|\bm\.s\b", lowered):
        return "硕士"
    if re.search(r"bachelor'?s|\bb\.s\b|undergraduate", lowered):
        return "本科"
    return ""


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
    found = [
        skill for skill, aliases in SKILL_KEYWORDS.items() if any(_keyword_in(haystack, alias) for alias in aliases)
    ]
    return found[:limit]


def _keyword_in(text: str, keyword: str) -> bool:
    """Match Latin keywords on word boundaries so ``ct`` does not hit ``director``.

    Aliases that are already wrapped in spaces (``" r "``) stay substring checks.
    """

    lowered = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+_-]*[a-z0-9]", lowered):
        return re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text) is not None
    return lowered in text if keyword.isascii() else keyword in text


def infer_category(*texts: str) -> str:
    """Classify a posting, giving the title priority over the description.

    Short Latin tokens use word boundaries. A posting that matches none of the
    direction keywords lands in ``其他`` instead of the imaging bucket.
    """

    for haystack in (texts[:1], texts):
        text = " ".join(t for t in haystack if t).lower()
        for category, keywords in CATEGORY_RULES:
            if any(_keyword_in(text, keyword) for keyword in keywords):
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
        for word in (
            "医",
            "药",
            "临床",
            "健康",
            "生物",
            "基因",
            "诊断",
            "病",
            "护理",
            "pharma",
            "clinical",
            "health",
            "medical",
            "medicine",
            "biotech",
            "biomedical",
            "diagnostic",
            "genomic",
            "hospital",
            "patient",
        )
        if word in haystack
    )
    ai_hits = sum(
        1
        for word in (
            "ai",
            "人工智能",
            "算法",
            "模型",
            "机器学习",
            "深度学习",
            "数据",
            "大模型",
            "nlp",
            "machine learning",
            "deep learning",
            "artificial intelligence",
            "data science",
            "data scientist",
            "data engineer",
            "ml engineer",
        )
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
        "experience": experience if experience in EXPERIENCE_BUCKETS else "",
        "education": parse_education(posting.education_text or posting.description),
        "job_level": infer_job_level(posting.title, experience, salary_max),
        "skills": skills,
        "category": category,
        "summary": summarise(posting, skills, category),
        "relevance": relevance_score(posting.title, posting.description, skills),
        "company_scale": scale_label,
        "company_scale_value": scale_value,
    }
