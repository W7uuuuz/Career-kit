"""豆瓣招聘 Scraper——静态 HTML（无需登录）。

页面：
- 社会招聘：https://jobs.douban.com/
- 校园招聘：https://jobs.douban.com/jobs/campus/
- 实习生招聘：https://jobs.douban.com/jobs/intern/

岗位列表与详情在同一页面内：列表锚点链到 #position-<code>，
正文在 div.mod.position 中，使用标准库正则 + html 解析。
"""

from __future__ import annotations

import html as _html
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client

PAGES = {
    "social": "https://jobs.douban.com/",
    "campus": "https://jobs.douban.com/jobs/campus/",
    "intern": "https://jobs.douban.com/jobs/intern/",
}
JOB_TYPE_LABELS = {
    "social": "社会招聘",
    "campus": "校园招聘",
    "intern": "实习生招聘",
}
_TYPE_ALIASES = {
    "social": "social",
    "社招": "social",
    "社会": "social",
    "社会招聘": "social",
    "campus": "campus",
    "校招": "campus",
    "校园": "campus",
    "校园招聘": "campus",
    "intern": "intern",
    "实习": "intern",
    "实习生": "intern",
    "实习生招聘": "intern",
    "all": "all",
    "全部": "all",
}

_HEADING_RE = re.compile(r'<h3 id="position-([^"]+)">(.*?)</h3>', re.S)
_SECTION_RE = re.compile(r"<em>(.*?)</em>\s*<pre>(.*?)</pre>", re.S)
_COL_RE = re.compile(r'<div class="col">\s*<em>(.*?)</em>(.*?)</div>', re.S)
_ANCHOR_RE = re.compile(r'<a href="#position-([^"]+)">')

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """豆瓣招聘 Scraper。"""

    COMPANY_SLUG = "douban"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"算法\"、\"运营\"、\"Android\"），匹配标题/职责/要求"},
        "city": {"required": False, "description": "城市名（如 \"北京\"、\"天津\"），对结果做本地过滤"},
        "job_type": {"required": False, "description": "招聘类型：social（社招）/ campus（校招）/ intern（实习）/ all（默认全部）"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "jobs.douban.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        job_type = _normalize_type(kwargs.get("job_type"))
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
        types = list(PAGES) if job_type == "all" else [job_type]
        collected: list[dict[str, Any]] = []
        errors: list[str] = []

        with make_client() as client:
            for kind in types:
                page = PAGES[kind]
                try:
                    page_html = _fetch_html(client, page)
                except ScraperHttpError as exc:
                    errors.append(f"{JOB_TYPE_LABELS[kind]}页面请求失败：{exc}")
                    continue
                group_map = _parse_group_map(page_html)
                for item in _parse_positions(page_html, page, kind, group_map):
                    if keyword and not _matches(item, keyword):
                        continue
                    if city and city not in item.get("location", ""):
                        continue
                    collected.append(item)
                    _remember(item)
                    if len(collected) >= limit:
                        return collected

        if not collected:
            if errors:
                return [{"error": "豆瓣页面抓取失败：" + "；".join(errors)}]
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city, "job_type": job_type}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于豆瓣：{url}"}

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
        parsed = urlsplit(url)
        fragment = unquote(parsed.fragment or "")
        if not fragment.startswith("position-"):
            return {"error": f"无法从 URL 提取豆瓣岗位锚点：{url}"}
        position_id = fragment[len("position-"):]
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else PAGES["social"]

        pages = [base]
        for candidate in PAGES.values():
            if candidate not in pages:
                pages.append(candidate)

        last_error = ""
        with make_client() as client:
            for page in pages:
                try:
                    page_html = _fetch_html(client, page)
                except ScraperHttpError as exc:
                    last_error = f"豆瓣详情页请求失败：{exc}"
                    continue
                block = _find_block(page_html, position_id)
                if block is None:
                    continue
                group_map = _parse_group_map(page_html)
                kind = _kind_for_page(page)
                _, detail = _parse_block(block, page, kind, group_map, position_id)
                if detail:
                    detail["url"] = url
                    return detail

        if last_error:
            return {"error": last_error, "url": url}
        return {"error": f"未在豆瓣页面找到岗位锚点 position-{position_id}", "url": url}


def _normalize_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "all"
    return _TYPE_ALIASES.get(text, "all")


def _kind_for_page(page_url: str) -> str:
    if "/jobs/campus/" in page_url:
        return "campus"
    if "/jobs/intern/" in page_url:
        return "intern"
    return "social"


def _fetch_html(client: Any, url: str) -> str:
    response = client.get(url)
    if response.status_code >= 400:
        raise ScraperHttpError(f"HTTP {response.status_code}: {url}")
    response.encoding = "utf-8"
    return response.text


def _parse_group_map(page_html: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for label, body in _COL_RE.findall(page_html):
        clean_label = _clean_text(label)
        for target in _ANCHOR_RE.findall(body):
            mapping[_html.unescape(target)] = clean_label
    return mapping


def _parse_positions(
    page_html: str, page_url: str, kind: str, group_map: dict[str, str]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    blocks = page_html.split('<div class="mod position">')[1:]
    for block in blocks:
        position_id, item = _parse_block(block, page_url, kind, group_map, "")
        if item:
            results.append(item)
    return results


def _find_block(page_html: str, position_id: str) -> str | None:
    for block in page_html.split('<div class="mod position">')[1:]:
        match = _HEADING_RE.search(block)
        if match and _html.unescape(match.group(1)).strip() == position_id:
            return block
    return None


def _parse_block(
    block: str,
    page_url: str,
    kind: str,
    group_map: dict[str, str],
    fallback_id: str,
) -> tuple[str, dict[str, Any]]:
    match = _HEADING_RE.search(block)
    if not match:
        return "", {}
    position_id = _html.unescape(match.group(1)).strip() or fallback_id
    title = _clean_text(match.group(2))
    description = ""
    requirements = ""
    benefits = ""
    for label, body in _SECTION_RE.findall(block):
        clean_label = _clean_text(label)
        text = _pre_text(body)
        if not text:
            continue
        if "优先" in clean_label or "加分" in clean_label:
            benefits = text
        elif "描述" in clean_label or "职责" in clean_label:
            description = text
        elif "要求" in clean_label or "资格" in clean_label or "条件" in clean_label:
            requirements = text

    label = group_map.get(position_id, "")
    department, location = _resolve_group(label)
    detail_url = f"{page_url}#position-{quote(position_id, safe='')}"
    summary_source = description or requirements or benefits
    return position_id, {
        "title": title,
        "url": detail_url,
        "company": "豆瓣",
        "location": location,
        "department": department,
        "summary": _truncate(summary_source, 800),
        "description": description,
        "requirements": requirements,
        "benefits": benefits,
        "job_id": position_id,
        "job_type": kind,
        "source": "douban",
    }


def _resolve_group(label: str) -> tuple[str, str]:
    label = (label or "").strip()
    if "天津" in label:
        return "", "天津"
    departments = ("研发", "运营", "产品", "设计", "市场", "销售", "职能", "内容")
    if label in departments:
        return label, "北京"
    return label, "北京"


def _matches(item: dict[str, Any], keyword: str) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("title", "description", "requirements", "benefits", "department")
    ).lower()
    return keyword.lower() in haystack


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["url"]] = {
        "title": item.get("title", ""),
        "company": "豆瓣",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("description") or item.get("summary", ""),
        "requirements": item.get("requirements", ""),
        "benefits": item.get("benefits", ""),
        "job_type": item.get("job_type", ""),
        "source": "douban",
    }


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _pre_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text).replace("\r", "")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
