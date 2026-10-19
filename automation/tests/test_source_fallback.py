from jobsinsight.sources.discovery import _from_hit, discover_site
from jobsinsight.sources.http_client import HttpClient, HttpResponse
from jobsinsight.sources.search_provider import SearchHit, SearchOutcome
from jobsinsight.sources.urlutil import is_publishable_record


class ScriptedSearch:
    name = "scripted"

    def __init__(self, outcome: SearchOutcome) -> None:
        self.outcome = outcome

    def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        return self.outcome


def _client(pages: dict[str, tuple[int, str]]) -> HttpClient:
    def transport(method, url, headers, body, timeout):
        status, text = pages.get(url, (200, "<html><title>登录</title><body>请登录 captcha</body></html>"))
        return HttpResponse(url=url, status=status, body=text)

    return HttpClient(transport=transport, sleep=lambda _seconds: None)


def test_blocked_detail_keeps_partial_snippet_and_chain_continues():
    outcome = SearchOutcome(
        provider="scripted",
        hits=[SearchHit(title="医疗AI工程师", url="https://www.zhipin.com/job_detail/abc", snippet="上海 算法")],
    )
    report = discover_site(
        source="zhipin",
        domains=["zhipin.com"],
        queries=["site:zhipin.com 上海 医疗AI"],
        provider=ScriptedSearch(outcome),
        client=_client({}),
        per_minute=1000,
    )
    assert report.jobs
    assert report.jobs[0].partial is True
    assert report.jobs[0].title == "医疗AI工程师"
    assert report.fallback
    assert report.blocked_count >= 1


def test_all_sources_unavailable_returns_no_jobs():
    report = discover_site(
        source="liepin",
        domains=["liepin.com"],
        queries=["site:liepin.com 上海 医疗AI"],
        provider=ScriptedSearch(SearchOutcome(provider="scripted", status="unavailable", error="down")),
        client=_client({"https://www.liepin.com/zhaopin/?key=%E5%8C%BB%E7%96%97AI": (403, "denied")}),
        per_minute=1000,
    )
    assert report.jobs == []
    assert report.status in {"unavailable", "blocked"}


def test_liepin_company_pages_and_unknown_place_are_rejected():
    company = SearchHit(
        title="某医疗科技有限公司",
        url="https://m.liepin.com/company/12541563",
        snippet="80-120元",
    )
    unknown = SearchHit(
        title="医疗AI算法工程师",
        url="https://www.liepin.com/s/medical-ai",
    )
    assert _from_hit(company, "liepin", ["liepin.com"]) is None
    assert _from_hit(unknown, "liepin", ["liepin.com"]) is None
    assert (
        is_publishable_record(
            {
                "title": "医疗AI算法工程师",
                "company": "未知公司",
                "city": "未知城市",
                "url": "https://www.liepin.com/job/1978123456.shtml",
                "platform": "猎聘网",
                "source_type": "liepin",
                "discovery_method": "search_engine",
                "salary_text": "80-120元",
            }
        )
        is False
    )
    assert (
        is_publishable_record(
            {
                "title": "医疗AI算法工程师",
                "company": "联影智能",
                "city": "上海",
                "url": "https://www.liepin.com/job/1978123456.shtml",
                "platform": "猎聘网",
                "source_type": "liepin",
                "discovery_method": "search_engine",
            }
        )
        is True
    )
    # 浏览器登录采集的职位没有 discovery_method，公司暂时未知时仍保留详情页。
    assert (
        is_publishable_record(
            {
                "title": "医疗AI算法工程师",
                "company": "未知公司",
                "city": "未知",
                "url": "https://www.liepin.com/job/1978000001.shtml",
                "platform": "猎聘网",
                "source_type": "liepin",
            }
        )
        is True
    )


def test_boss_company_and_keyword_listing_pages_are_rejected():
    company = SearchHit(
        title="「杭州智诊科技有限公司招聘」-boss直聘",
        url="https://m.zhipin.com/companys/3eb2c7d14d7c483d03V42du4ElI~.html",
    )
    listing = SearchHit(
        title="「杭州医疗算法工程师招聘信息」-boss直聘",
        url="https://www.zhipin.com/zhaopin/71824a2fda47284b0nR43t24GQ~~",
    )
    assert _from_hit(company, "zhipin", ["zhipin.com"]) is None
    assert _from_hit(listing, "zhipin", ["zhipin.com"]) is None


def test_partial_job_accepted_and_blank_title_rejected():
    hit = SearchHit(title="生物信息工程师", url="https://www.51job.com/job/9", snippet="")
    posting = _from_hit(hit, "51job", ["51job.com"])
    assert posting is not None
    assert posting.partial is True
    assert _from_hit(SearchHit(title="  ", url="https://www.51job.com/job/1"), "51job", ["51job.com"]) is None
