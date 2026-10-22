"""CADD terms are merged onto a local keyword list without duplicating it."""

from jobsinsight.keywords import with_cadd_keywords


def test_browser_keywords_gain_two_cadd_terms():
    assert with_cadd_keywords(["医疗AI", "医疗大模型"]) == ["医疗AI", "医疗大模型", "CADD", "计算化学"]


def test_terms_already_present_are_not_repeated():
    assert with_cadd_keywords(["cadd", "计算化学", "医疗AI"]) == ["cadd", "计算化学", "医疗AI"]
    assert with_cadd_keywords(["CADD", "医疗AI"]) == ["CADD", "医疗AI", "计算化学"]
