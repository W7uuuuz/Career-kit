"""实习僧（shixiseng.com）实习岗位 Scraper。

数据源：第三方实习聚合平台，匿名访问公开列表与详情页。
列表页与详情页均为 SSR，直接解析公开 HTML，不登录、不绕过验证码。

返回字段按 Career Kit 的 JD 规范：
- search: title / url / company / location / salary / summary / department / job_type
- get_detail: title / company / location / salary / description / requirements / benefits
"""

from __future__ import annotations

import html as _html
import re
from typing import Any
from urllib.parse import urlsplit

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client

BASE_URL = "https://www.shixiseng.com"
SEARCH_URL = f"{BASE_URL}/interns"
REFERER = f"{BASE_URL}/interns?type=intern"

# 站点用 iconfont 私有区字符渲染部分汉字与数字；只剥离，不解析字体映射。
_PUA_RE = re.compile(r"[\ue000-\uf8ff\ufffd]")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")

_TITLE_RE = re.compile(
    r'<a[^>]+class="[^"]*\btitle\b[^"]*\bfont\b[^"]*"[^>]*>(.*?)</a>', re.S
)
_COMPANY_RE = re.compile(
    r'<a\s+title="([^"]*)"\s+href="javascript:;"\s+class="title ellipsis"', re.S
)
_CITY_RE = re.compile(r'<span class="city ellipsis"[^>]*>(.*?)</span>', re.S)
_SALARY_RE = re.compile(r'<span class="day font"[^>]*>(.*?)</span>', re.S)
_INDUSTRY_RE = re.compile(
    r'<p class="tip"[^>]*>\s*<span class="ellipsis"[^>]*>(.*?)</span>', re.S
)

_DETAIL_TITLE_RE = re.compile(
    r'<div class="new_job_name"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S
)
_DETAIL_COMPANY_RE = re.compile(
    r'<a[^>]+class="[^"]*\bcom-name\b[^"]*"[^>]*>(.*?)</a>', re.S
)
_DETAIL_REFRESH_RE = re.compile(
    r'<div class="job_date"[^>]*>\s*<span[^>]*>(.*?)</span>', re.S
)
_DETAIL_SALARY_RE = re.compile(r'<span class="job_money[^"]*"[^>]*>(.*?)</span>', re.S)
_DETAIL_CITY_RE = re.compile(
    r'<span title="[^"]*" class="job_position"[^>]*>(.*?)</span>', re.S
)
_DETAIL_DEGREE_RE = re.compile(
    r'<span class="job_academic"[^>]*>(.*?)</span>', re.S
)
_DETAIL_ADDRESS_RE = re.compile(
    r'<span class="com_position"[^>]*>(.*?)</span>', re.S
)
_DETAIL_DESCRIPTION_RE = re.compile(
    r'<div class="job_detail"[^>]*>(.*?)</div>', re.S
)
_DETAIL_BENEFITS_RE = re.compile(
    r'<div class="job_good_list"[^>]*>(.*?)</div>', re.S
)
_DEADLINE_RE = re.compile(r"截止日期[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """实习僧 Scraper。"""

    COMPANY_SLUG = "shixiseng"
    DATA_TYPE = "jds"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": True, "description": "搜索关键词，如 \"量化\"、\"投行\"、\"中金\""},
        "city": {"required": False, "description": "城市名，如 \"北京\"、\"上海\"；默认全国"},
        "page": {"required": False, "description": "页码，默认 1"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    search_cache_ttl = 3600
    detail_cache_ttl = 86400

    def supports_url(self, url: str) -> bool:
        return "shixiseng.com" in url and "/intern/" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = str(kwargs.get("keyword") or "").strip()
        city = str(kwargs.get("city") or "").strip() or "全国"
        page = max(1, int(kwargs.get("page") or 1))
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        if not keyword:
            return [{"error": "实习僧搜索需要提供 keyword（如 \"量化\"、\"投行\"）"}]

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, page=page)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, page, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"不是实习僧岗位 URL：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(url)
        if result.get("error") and url in _FALLBACK:
            result = dict(_FALLBACK[url])
            result["url"] = url
            result["_note"] = "详情页暂不可用，以下信息来自列表页快照"
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_jobs(
        self, keyword: str, city: str, page: int, limit: int
    ) -> list[dict[str, Any]]:
        params = {
            "type": "intern",
            "keyword": keyword,
            "publishTime": "mon",
            "city": city,
            "page": str(page),
        }
        try:
            page_html = _fetch_html(SEARCH_URL, params)
        except ScraperHttpError as exc:
            return [{"error": f"实习僧搜索页抓取失败：{exc}"}]

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in page_html.split('data-intern-id="')[1:]:
            item = _parse_card(chunk)
            if not item or item["url"] in seen:
                continue
            seen.add(item["url"])
            results.append(item)
            _remember(item)
            if len(results) >= limit:
                break

        if not results:
            return [
                {
                    "error": (
                        f"未找到与「{keyword}」相关的实习岗位"
                        "（实习僧只展示近一月刷新的实习；可换关键词或城市重试）"
                    ),
                    "keyword": keyword,
                    "city": city,
                }
            ]
        return results

    def _fetch_detail(self, url: str) -> dict[str, Any]:
        clean_url = _strip_query(url)
        try:
            page_html = _fetch_html(clean_url, None)
        except ScraperHttpError as exc:
            return {"error": f"实习僧详情页抓取失败：{exc}", "url": url}

        title = _clean_text(_first(_DETAIL_TITLE_RE, page_html))
        company = _clean_text(_first(_DETAIL_COMPANY_RE, page_html))
        if not company:
            company = str((_FALLBACK.get(url) or {}).get("company") or "")
        if not title and not company:
            return {"error": "详情页结构已变化，未解析到岗位信息", "url": url}

        description = _block_text(_first(_DETAIL_DESCRIPTION_RE, page_html))
        requirements = _requirements_text(page_html)
        benefits = _span_texts(_first(_DETAIL_BENEFITS_RE, page_html))
        salary = _clean_salary(_first(_DETAIL_SALARY_RE, page_html))
        city = _clean_text(_first(_DETAIL_CITY_RE, page_html))
        address = _clean_text(_first(_DETAIL_ADDRESS_RE, page_html))
        degree = _clean_text(_first(_DETAIL_DEGREE_RE, page_html))
        refresh = _clean_text(_first(_DETAIL_REFRESH_RE, page_html))

        if not description and not requirements:
            return {
                "error": "详情页未解析到岗位描述（可能需登录或页面改版）",
                "url": url,
            }

        detail = {
            "title": title,
            "company": company,
            "location": city,
            "address": address,
            "salary": salary,
            "degree": degree,
            "description": description,
            "requirements": requirements,
            "benefits": benefits,
            "job_type": "实习",
            "source": "shixiseng",
            "url": url,
            "updated_at": refresh,
        }
        return {key: value for key, value in detail.items() if value}


def _fetch_html(url: str, params: dict[str, str] | None) -> str:
    with make_client(timeout=30.0) as client:
        response = client.get(url, params=params, headers={"Referer": REFERER})
    if response.status_code >= 400:
        raise ScraperHttpError(f"HTTP {response.status_code}: {url}")
    response.encoding = "utf-8"
    return response.text


def _parse_card(chunk: str) -> dict[str, Any] | None:
    job_id = chunk.split('"', 1)[0].strip()
    if not job_id.startswith("inn_"):
        return None

    title = _clean_text(_first(_TITLE_RE, chunk))
    company = _clean_text(_first(_COMPANY_RE, chunk))
    if not title or not company:
        return None

    city = _clean_text(_first(_CITY_RE, chunk))
    salary = _clean_salary(_first(_SALARY_RE, chunk))
    industry = _clean_text(_first(_INDUSTRY_RE, chunk))
    url = f"{BASE_URL}/intern/{job_id}"

    summary_parts = [part for part in (industry, salary) if part]
    return {
        "title": title,
        "url": url,
        "company": company,
        "location": city,
        "salary": salary,
        "department": industry,
        "summary": " · ".join(summary_parts),
        "job_type": "实习",
        "job_id": job_id,
        "source": "shixiseng",
    }


def _requirements_text(page_html: str) -> str:
    deadline = _DEADLINE_RE.search(page_html)
    parts: list[str] = []
    marker = page_html.find("投递要求")
    if marker >= 0:
        block = page_html[marker : marker + 1200]
        cut = block.find('<div class="con-job', 10)
        if cut > 0:
            block = block[:cut]
        text = _block_text(block)
        if text:
            parts.append(text)
    if deadline and "截止日期" not in "".join(parts):
        parts.append(f"截止日期：{deadline.group(1)}")
    return "\n".join(parts).strip()


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["url"]] = {
        "title": item.get("title", ""),
        "company": item.get("company", ""),
        "location": item.get("location", ""),
        "salary": item.get("salary", ""),
        "department": item.get("department", ""),
        "summary": item.get("summary", ""),
        "job_type": "实习",
        "source": "shixiseng",
    }


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(1) if match else ""


def _block_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = _TAG_RE.sub("", text)
    text = _PUA_RE.sub("", _html.unescape(text)).replace("\r", "")
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _span_texts(value: str) -> str:
    return "、".join(
        text
        for text in (_clean_text(item) for item in re.findall(r"<span[^>]*>(.*?)</span>", value or "", re.S))
        if text
    )


def _clean_text(value: str) -> str:
    text = _TAG_RE.sub("", value or "")
    text = _PUA_RE.sub("", _html.unescape(text))
    return _SPACE_RE.sub(" ", text).strip()


def _clean_salary(value: str) -> str:
    """薪资含私有区字符时数字不可还原；无数字的残缺文本也留空。"""
    text = _TAG_RE.sub("", value or "")
    unescaped = _html.unescape(text)
    if _PUA_RE.search(unescaped):
        return ""
    text = _SPACE_RE.sub(" ", unescaped).strip()
    if not re.search(r"\d", text) and not any(word in text for word in ("面议", "元", "万")):
        return ""
    return text


def _strip_query(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
