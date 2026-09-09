"""Collector that lets the LLM read a job list page.

Useful when a site has no usable JSON endpoint: the page is fetched, reduced to
plain text and handed to the model, which returns structured postings. Slower
and more expensive than :mod:`json_api`, so it is opt-in per source.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

from ..llm import LLMError
from ..models import RawPosting
from .base import Collector, CollectorError, register_collector
from .json_api import DEFAULT_USER_AGENT

LOGGER = logging.getLogger(__name__)

EXTRACTION_INSTRUCTIONS = """你是一个招聘信息抽取器。
从给定的网页文本中抽取所有招聘岗位，只保留“医药健康 + AI/数据”相关岗位。
严格输出 JSON：{"postings": [{"title": "", "company": "", "city": "", "salary_text": "", "experience_text": "", "education_text": "", "description": "", "url": "", "publish_date": ""}]}
找不到岗位时输出 {"postings": []}。不要编造不存在的岗位。"""

_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class HtmlLLMCollector(Collector):
    type = "html_llm"

    def collect(self) -> Iterable[RawPosting]:
        if self.context.llm is None:
            raise CollectorError(
                f"source {self.settings.name!r} has type 'html_llm' but the LLM is disabled; "
                "set llm.enabled = true or switch the source type"
            )
        if not self.settings.urls:
            raise CollectorError(f"source {self.settings.name!r} needs at least one url")

        options = self.settings.options or {}
        max_chars = int(options.get("max_chars", 12000))

        postings: list[RawPosting] = []
        for url in self.settings.urls:
            text = html_to_text(self._fetch(url))[:max_chars]
            if not text.strip():
                LOGGER.warning("%s 返回空页面，跳过", url)
                continue
            try:
                result = self.context.llm.task_json(
                    task="extract_postings",
                    payload={"url": url, "page_text": text},
                    instructions=EXTRACTION_INSTRUCTIONS,
                    max_tokens=int(options.get("max_tokens", 4096)),
                )
            except LLMError as exc:
                LOGGER.warning("LLM 抽取 %s 失败：%s", url, exc)
                continue

            for index, entry in enumerate(_iter_postings(result)):
                posting = RawPosting.from_dict({**entry, "platform": self.settings.platform or self.settings.name})
                if not posting.title:
                    continue
                posting.source_id = posting.url or f"{url}#{index}"
                postings.append(posting)
                if self.settings.limit and len(postings) >= self.settings.limit:
                    return postings
        return postings

    def _fetch(self, url: str) -> str:
        headers = {"User-Agent": DEFAULT_USER_AGENT, **self.settings.headers}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CollectorError(f"cannot fetch {url}: {exc}") from exc


def _iter_postings(result: Any) -> Iterable[Mapping[str, Any]]:
    candidates = (result.get("postings") or result.get("jobs") or []) if isinstance(result, Mapping) else result
    if not isinstance(candidates, list):
        return []
    return [entry for entry in candidates if isinstance(entry, Mapping)]


def html_to_text(html: str) -> str:
    """Strip markup so the model sees content instead of tag soup."""

    text = _SCRIPT.sub(" ", html)
    text = _TAG.sub("\n", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    text = _WHITESPACE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(line for line in lines if line))


register_collector("html_llm", HtmlLLMCollector)
