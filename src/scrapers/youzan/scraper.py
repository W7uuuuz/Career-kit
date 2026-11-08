"""有赞招聘 Scraper——Supabase 公开 function（无需登录）。

接口（POST JSON）：
- https://rassfvy0pfpl2qutpu6v.db.superun.com/functions/v1/careers-portal
  - 列表：{"action": "list", "keyword": "", "city": "", "category": "",
           "publishedWithinDays": "all", "urgentOnly": false, "page": 1, "pageSize": 20}
  - 详情：{"action": "detail", "jobId": "<uuid>"}
- 详情页：https://job.youzan.com/careers/jobs/<jobId>

列表响应已包含岗位描述与要求；get_detail 优先调用详情接口，失败时回退列表快照。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://rassfvy0pfpl2qutpu6v.db.superun.com/functions/v1/careers-portal"
PAGE_URL = "https://job.youzan.com/careers"
DETAIL_URL = "https://job.youzan.com/careers/jobs/{id}"
PAGE_SIZE = 20
MAX_PAGES = 10

_HEADERS = {"Referer": PAGE_URL, "Origin": "https://job.youzan.com"}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """有赞社会招聘 Scraper。"""

    COMPANY_SLUG = "youzan"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"后端\"、\"产品经理\"）"},
        "city": {"required": False, "description": "城市名（如 \"杭州市\"），服务端过滤并做本地兜底"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "job.youzan.com" in url

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
                    body = {
                        "action": "list",
                        "keyword": keyword,
                        "publishedWithinDays": "all",
                        "category": "",
                        "city": city,
                        "urgentOnly": False,
                        "page": page,
                        "pageSize": PAGE_SIZE,
                    }
                    payload = request_json(client, "POST", API, json_body=body, headers=_HEADERS)
                    if not payload.get("ok"):
                        return [{"error": f"有赞列表接口返回错误：{payload.get('message') or payload.get('code')}"}]
                    rows = payload.get("items") or []
                    if not rows:
                        break
                    for row in rows:
                        item = self._format_post(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected
                    total = int(payload.get("total") or 0)
                    if len(rows) < PAGE_SIZE or (total and page * PAGE_SIZE >= total):
                        break
        except ScraperHttpError as exc:
            return [{"error": f"有赞接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"有赞接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于有赞：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jobId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "POST",
                    API,
                    json_body={"action": "detail", "jobId": job_id},
                    headers=_HEADERS,
                )
        except ScraperHttpError as exc:
            return {"error": f"有赞详情请求失败：{exc}"}
        except (TypeError, ValueError) as exc:
            return {"error": f"有赞详情返回格式异常：{exc}"}

        job = payload.get("job") if payload.get("ok") else None
        if not isinstance(job, dict) or not job:
            fallback = _FALLBACK.get(job_id)
            if fallback:
                result = dict(fallback)
                result["url"] = url
                result["_note"] = "详情接口未返回内容，使用搜索列表快照"
                return result
            message = payload.get("message") or payload.get("code") or "详情为空"
            return {"error": f"有赞详情接口返回错误：{message}", "url": url}

        result = {
            "title": job.get("title", ""),
            "company": "有赞",
            "location": _location(job),
            "department": job.get("department", ""),
            "salary": _normalize_salary(job.get("salaryText")),
            "description": str(job.get("description") or "").strip(),
            "requirements": str(job.get("requirements") or "").strip(),
            "job_type": job.get("jobType", ""),
            "category": job.get("category", ""),
            "publish_time": job.get("publishedAt", ""),
            "url": url,
            "source": "youzan",
        }
        cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id", ""))
        return {
            "title": row.get("title", ""),
            "url": DETAIL_URL.format(id=job_id),
            "company": "有赞",
            "location": _location(row),
            "department": row.get("department", ""),
            "salary": _normalize_salary(row.get("salaryText")),
            "summary": _truncate(str(row.get("description") or ""), 800),
            "job_id": job_id,
            "job_type": row.get("jobType", ""),
            "is_urgent": bool(row.get("isUrgent")),
            "publish_time": row.get("publishedAt", ""),
            "source": "youzan",
        }


def _location(row: dict[str, Any]) -> str:
    cities = [str(c) for c in (row.get("cities") or []) if c]
    if cities:
        return "/".join(cities)
    return str(row.get("city") or row.get("locationText") or "")


def _normalize_salary(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "面议"} else text


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "有赞",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": item.get("salary", ""),
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "youzan",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        if re.fullmatch(r"[0-9a-fA-F-]{16,}", part):
            return part
    query = parse_qs(parsed.query)
    return (query.get("jobId") or query.get("id") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
