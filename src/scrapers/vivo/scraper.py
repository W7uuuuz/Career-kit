"""vivo 社会招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：POST https://hr.vivo.com/api/social/webSite/portal/page
- 详情：POST https://hr.vivo.com/api/social/webSite/portal/job/detail

列表响应已包含岗位职责与岗位要求（job_desc），详情接口返回同一份正文。
页面上岗位详情地址形如：
https://hr.vivo.com/job-detail?_irjc=<job_category_id>&_irjid=<job_id>&_collect=false
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

LIST_API = "https://hr.vivo.com/api/social/webSite/portal/page"
DETAIL_API = "https://hr.vivo.com/api/social/webSite/portal/job/detail"
DETAIL_URL = "https://hr.vivo.com/job-detail?_irjc={category}&_irjid={job_id}&_collect=false"
PAGE_SIZE = 50
MAX_PAGES = 10

_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://hr.vivo.com/jobs",
    "Origin": "https://hr.vivo.com",
}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """vivo 社会招聘 Scraper。"""

    COMPANY_SLUG = "vivo"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"算法\"、\"Android\"、\"产品\"），由接口按标题/JD 检索"},
        "city": {"required": False, "description": "城市名（如 \"深圳\"、\"东莞\"、\"上海\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "hr.vivo.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _fetch_jobs(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        try:
            with make_client() as client:
                for page in range(1, MAX_PAGES + 1):
                    payload = request_json(
                        client,
                        "POST",
                        LIST_API,
                        json_body={
                            "city_code_list": [],
                            "company_id": 1,
                            "group_id": 1,
                            "user_id": None,
                            "job_category_id_list": [],
                            "keyword": keyword,
                            "max_results": PAGE_SIZE,
                            "page": page,
                            "yoe_list": [],
                            "loading": True,
                        },
                        headers=_HEADERS,
                    )
                    if payload.get("code") != 0:
                        return [{"error": f"vivo 接口返回错误：{payload.get('message') or payload.get('code')}"}]

                    data = payload.get("data") or []
                    if not data:
                        break

                    for row in data:
                        item = self._format_job(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected

                    meta = payload.get("meta") or {}
                    total_pages = int(meta.get("page_count") or 0)
                    if total_pages and page >= total_pages:
                        break
                    if len(data) < PAGE_SIZE:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"vivo 接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"vivo 接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于vivo：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 vivo 岗位 id：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(job_id, url)
        if result.get("error") and job_id in _FALLBACK:
            result = dict(_FALLBACK[job_id])
            result["url"] = url
            result["_note"] = "详情接口不可用，内容来自搜索列表快照"
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_detail(self, job_id: str, url: str) -> dict[str, Any]:
        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "POST",
                    DETAIL_API,
                    json_body={"job_id": job_id},
                    headers=_HEADERS,
                )
            if payload.get("code") != 0:
                return {"error": f"vivo 详情接口返回错误：{payload.get('message') or payload.get('code')}", "url": url}
            data = payload.get("data") or {}
            if not data:
                return {"error": "vivo 详情接口未返回岗位内容", "url": url}
            return self._format_detail(data, url)
        except ScraperHttpError as exc:
            return {"error": f"vivo 详情接口请求失败：{exc}", "url": url}
        except (TypeError, ValueError) as exc:
            return {"error": f"vivo 详情接口返回格式异常：{exc}", "url": url}

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("job_id") or "")
        category_id = str(row.get("job_category_id") or "")
        description, requirements = _split_desc(str(row.get("job_desc") or ""))
        return {
            "title": row.get("job_title", ""),
            "url": DETAIL_URL.format(category=category_id, job_id=job_id),
            "company": "vivo",
            "location": _join_locations(row.get("job_location_list")),
            "department": row.get("requirement_org_name", ""),
            "summary": _truncate(str(row.get("job_desc") or ""), 800),
            "description": description,
            "requirements": requirements,
            "job_id": job_id,
            "job_category": row.get("job_category", ""),
            "education": row.get("degree_range_name", ""),
            "experience": _format_experience(row.get("yoe_min"), row.get("yoe_max")),
            "source": "vivo",
        }

    def _format_detail(self, row: dict[str, Any], url: str) -> dict[str, Any]:
        job_id = str(row.get("job_id") or "")
        category_id = str(row.get("job_category_id") or "")
        description, requirements = _split_desc(str(row.get("job_desc") or ""))
        publish = row.get("publish_timestamp")
        return {
            "title": row.get("job_title", ""),
            "company": "vivo",
            "location": _join_locations(row.get("job_location_list")),
            "department": row.get("requirement_org_name", ""),
            "salary": "",
            "description": description,
            "requirements": requirements,
            "job_id": job_id,
            "job_category": row.get("job_category", ""),
            "education": row.get("degree_range_name", ""),
            "experience": _format_experience(row.get("yoe_min"), row.get("yoe_max")),
            "publish_time": _format_timestamp(publish),
            "url": url or DETAIL_URL.format(category=category_id, job_id=job_id),
            "source": "vivo",
        }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "vivo",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("description") or item.get("summary", ""),
        "requirements": item.get("requirements", ""),
        "job_category": item.get("job_category", ""),
        "education": item.get("education", ""),
        "experience": item.get("experience", ""),
        "source": "vivo",
    }


def _split_desc(text: str) -> tuple[str, str]:
    text = (text or "").replace("\r", "").strip()
    if not text:
        return "", ""
    markers = ("岗位要求：", "岗位要求:", "任职要求：", "任职要求:", "职位要求：", "职位要求:")
    positions = [(text.find(marker), marker) for marker in markers if text.find(marker) >= 0]
    if not positions:
        return text, ""
    index, marker = min(positions, key=lambda item: item[0])
    description = text[:index].strip()
    requirements = text[index + len(marker):].strip()
    for prefix in ("岗位职责：", "岗位职责:", "工作职责：", "工作职责:"):
        if description.startswith(prefix):
            description = description[len(prefix):].strip()
            break
    return description, requirements


def _join_locations(locations: Any) -> str:
    if not isinstance(locations, list):
        return ""
    cities: list[str] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        city = str(loc.get("city") or "").strip()
        if city and city not in cities:
            cities.append(city)
    return "/".join(cities)


def _format_experience(yoe_min: Any, yoe_max: Any) -> str:
    try:
        low = int(yoe_min)
    except (TypeError, ValueError):
        low = 0
    try:
        high = int(yoe_max)
    except (TypeError, ValueError):
        high = -1
    if low <= 0 and high < 0:
        return ""
    if high < 0:
        return f"{low}年以上"
    if low <= 0:
        return f"{high}年以下"
    return f"{low}-{high}年"


def _format_timestamp(value: Any) -> str:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    from datetime import datetime

    try:
        return datetime.fromtimestamp(millis / 1000).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for name in ("_irjid", "job_id", "jobId"):
        value = (query.get(name) or [""])[0]
        if value:
            return value
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        if part.startswith("M") and part[1:].isdigit():
            return part
    return ""


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\r", "").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
