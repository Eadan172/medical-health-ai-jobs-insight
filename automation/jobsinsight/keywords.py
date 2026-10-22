"""CADD terms added on top of a configured keyword list.

Browser and JSON search expand one page load per keyword. Only two terms are
appended, and a term already in the list is not repeated. The longer phrases
(计算机辅助药物设计, 分子模拟, computational chemistry) stay in the public-search
catalog, where one rotating slot uses them without extra requests.
"""

from __future__ import annotations

CADD_BROWSER_TERMS = ("CADD", "计算化学")


def with_cadd_keywords(keywords: list[str]) -> list[str]:
    merged = list(keywords)
    seen = {item.casefold() for item in keywords}
    for term in CADD_BROWSER_TERMS:
        if term.casefold() in seen:
            continue
        merged.append(term)
        seen.add(term.casefold())
    return merged
