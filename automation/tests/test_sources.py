from jobsinsight.collectors import CollectorContext, build_collector
from jobsinsight.config import SourceSettings
from jobsinsight.sources.catalog import build_search_queries, load_catalog


def test_query_catalog_contains_healthcare_terms():
    catalog = load_catalog(__import__("pathlib").Path("automation/config/job_queries.yaml"))
    # tests run from automation/
    if not catalog:
        catalog = load_catalog(
            __import__("pathlib").Path(__file__).resolve().parents[1] / "config" / "job_queries.yaml"
        )
    assert "医疗AI" in catalog["keywords"]
    assert "上海" in catalog["cities"]
    queries = build_search_queries(catalog, domains=["zhipin.com"], max_queries=1)
    assert queries == ["site:zhipin.com 上海 医疗AI"]
    assert "CADD" in catalog["keywords"]
    assert "computational chemistry" in catalog["focus_keywords"]
    added = ["化学信息", "AIDD", "数据标注", "医疗审核", "AI应用", "Agent", "计算模拟", "生物信息"]
    for term in added:
        assert catalog["keywords"].count(term) == 1
        assert catalog["focus_keywords"].count(term) == 1
    assert catalog["keywords"].count("计算化学") == 1
    assert catalog["keywords"].count("生物信息学") == 1

    capped = build_search_queries(catalog, domains=["zhipin.com"], max_queries=2, focus_index=0)
    assert len(capped) == 2
    assert capped[0] == "site:zhipin.com 上海 医疗AI"
    assert capped[-1] == "site:zhipin.com 上海 CADD"

    rotated = build_search_queries(catalog, domains=["zhipin.com"], max_queries=2, focus_index=1)
    assert len(rotated) == 2
    assert rotated[-1] == "site:zhipin.com 上海 计算机辅助药物设计"

    last_slots = {
        build_search_queries(catalog, domains=["zhipin.com"], max_queries=2, focus_index=index)[-1]
        for index in range(len(catalog["focus_keywords"]))
    }
    assert len(last_slots) == len(catalog["focus_keywords"])


def test_unknown_collector_is_rejected(tmp_path):
    source = SourceSettings(name="nope", type="not-a-source")
    try:
        build_collector(source, CollectorContext(project_root=tmp_path))
    except Exception as exc:  # noqa: BLE001
        assert "unknown source type" in str(exc)
    else:
        raise AssertionError("expected unknown source to fail")
