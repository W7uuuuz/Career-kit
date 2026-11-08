"""陌陌（Hello Group）招聘 Scraper——静态 HTML（无需登录）。

页面：https://www.immomo.com/jobs/join/index

岗位列表与详情在同一页面内（手风琴展开），服务端渲染首批岗位；
分页 AJAX（/jobs/join/ajaxJobs）对空类别返回 406，因此这里直接解析静态页面。
使用标准库 re + html.parser 提取岗位与正文。
"""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client

INDEX = "https://www.immomo.com/jobs/join/index"

_BLOCK_SPLIT = '<div class="jobs-item-big">'
_TITLE_RE = re.compile(r'<span class="carrier-word">(.*?)</span>', re.S)
_CATEGORY_RE = re.compile(r'<p class="cate-name"><span>(.*?)</span></p>', re.S)
_LOCATION_RE = re.compile(r'<p class="addr"><span>(.*?)</span></p>', re.S)
_PUBLISH_RE = re.compile(r'<p class="publish"><span>(.*?)</span></p>', re.S)
_ARTICLE_RE = re.compile(r'<article class="job-article">(.*)</article>', re.S)

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """陌陌社会招聘 Scraper。"""

    COMPANY_SLUG = "momo"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Android\"、\"产品\"、\"设计\"），匹配标题/类别/正文"},
        "city": {"required": False, "description": "工作地点（如 \"北京\"、\"上海\"），对结果做本地过滤"},
        "job_type": {"required": False, "description": "岗位类别（如 \"技术类\"、\"设计类\"），对类别做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "immomo.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        job_type = (kwargs.get("job_type") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, job_type=job_type, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, job_type, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _fetch_jobs(self, keyword: str, city: str, job_type: str, limit: int) -> list[dict[str, Any]]:
        try:
            with make_client() as client:
                page_html = _fetch_html(client, INDEX)
        except ScraperHttpError as exc:
            return [{"error": f"陌陌页面请求失败：{exc}"}]

        collected: list[dict[str, Any]] = []
        for item in _parse_positions(page_html):
            if job_type and job_type not in item.get("job_type", ""):
                continue
            if city and city not in item.get("location", ""):
                continue
            if keyword and not _matches(item, keyword):
                continue
            collected.append(item)
            _remember(item)
            if len(collected) >= limit:
                return collected

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city, "job_type": job_type}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于陌陌：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(url)
        if result.get("error") and url in _FALLBACK:
            result = dict(_FALLBACK[url])
            result["url"] = url
            result["_note"] = "详情页不可用，内容来自搜索列表快照"
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_detail(self, url: str) -> dict[str, Any]:
        fragment = unquote(urlsplit(url).fragment or "")
        if not fragment.startswith("job-"):
            return {"error": f"无法从 URL 提取陌陌岗位锚点：{url}"}
        wanted = fragment[len("job-"):].strip()
        if not wanted:
            return {"error": f"陌陌岗位锚点为空：{url}"}

        try:
            with make_client() as client:
                page_html = _fetch_html(client, INDEX)
        except ScraperHttpError as exc:
            return {"error": f"陌陌详情页请求失败：{exc}", "url": url}

        for item in _parse_positions(page_html):
            if item.get("title") != wanted:
                continue
            return {
                "title": item.get("title", ""),
                "company": "陌陌",
                "location": item.get("location", ""),
                "department": item.get("job_type", ""),
                "salary": "",
                "description": item.get("description", ""),
                "requirements": item.get("requirements", ""),
                "publish_time": item.get("publish_time", ""),
                "url": url,
                "source": "momo",
            }
        return {"error": f"未在陌陌页面找到岗位：{wanted}", "url": url}


def _fetch_html(client: Any, url: str) -> str:
    response = client.get(url)
    if response.status_code >= 400:
        raise ScraperHttpError(f"HTTP {response.status_code}: {url}")
    response.encoding = "utf-8"
    return response.text


def _parse_positions(page_html: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"<script\b.*?</script>", "", page_html, flags=re.S | re.I)
    cleaned = re.sub(r"<style\b.*?</style>", "", cleaned, flags=re.S | re.I)

    results: list[dict[str, Any]] = []
    for block in cleaned.split(_BLOCK_SPLIT)[1:]:
        title = _first(_TITLE_RE, block)
        if not title:
            continue
        category = _first(_CATEGORY_RE, block)
        location = _first(_LOCATION_RE, block)
        publish = _first(_PUBLISH_RE, block)
        article = _ARTICLE_RE.search(block)
        body = _html_to_text(_strip_cangjie(article.group(1))) if article else ""
        description, requirements = _split_body(body)
        summary_source = description or body
        results.append({
            "title": title,
            "url": f"{INDEX}#job-{quote(title, safe='')}",
            "company": "陌陌",
            "location": location,
            "department": category,
            "job_type": category,
            "summary": _truncate(summary_source, 800),
            "description": description,
            "requirements": requirements,
            "publish_time": publish,
            "job_id": title,
            "source": "momo",
        })
    return results


def _strip_cangjie(value: str) -> str:
    """移除页面里未转义的 data-clipboard-cangjie 属性，否则标准库解析会被截断。"""
    return re.sub(r' data-clipboard-cangjie=".*?"(?=>)', "", value or "", flags=re.S)


def _first(pattern: re.Pattern[str], block: str) -> str:
    match = pattern.search(block)
    if not match:
        return ""
    return _clean_text(match.group(1))


def _split_body(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        return "", ""
    req_markers = ("任职要求", "岗位要求", "任职资格", "职位要求", "应聘条件", "応募資格")
    positions = [(text.find(marker), marker) for marker in req_markers if text.find(marker) >= 0]
    if not positions:
        return text, ""
    index, marker = min(positions, key=lambda item: item[0])
    description = text[:index].strip()
    requirements = text[index + len(marker):].strip()
    for prefix in ("岗位职责：", "岗位职责:", "工作职责：", "工作职责:", "职位描述：", "职位描述:"):
        if description.startswith(prefix):
            description = description[len(prefix):].strip()
            break
    return description, requirements


def _matches(item: dict[str, Any], keyword: str) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "description", "requirements", "job_type")
    ).lower()
    return keyword.lower() in haystack


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["url"]] = {
        "title": item.get("title", ""),
        "company": "陌陌",
        "location": item.get("location", ""),
        "department": item.get("job_type", ""),
        "salary": "",
        "description": item.get("description") or item.get("summary", ""),
        "requirements": item.get("requirements", ""),
        "publish_time": item.get("publish_time", ""),
        "source": "momo",
    }


class _TextExtractor(HTMLParser):
    """把 HTML 片段转成可读文本。"""

    _BLOCK_TAGS = {
        "br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "article", "section", "ul", "ol", "table",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            if self._skip:
                self._skip -= 1
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value or "")
        parser.close()
    except Exception:
        return ""
    text = parser.text().replace("\xa0", " ").replace("\r", "")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = _html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
