"""阿里巴巴社会招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：POST https://talent.alibaba.com/position/search
- 详情：https://talent.alibaba.com/off-campus/position-detail?positionId=<id>

接口有 stateless CSRF 校验：请求携带同值的 XSRF-TOKEN cookie 与
x-xsrf-token header 即可，不需要登录或会话。
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://talent.alibaba.com/position/search"
DETAIL = "https://talent.alibaba.com/off-campus/position-detail?positionId={id}"
PAGE_SIZE = 100
MAX_PAGES = 5

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """阿里巴巴社会招聘 Scraper。"""

    COMPANY_SLUG = "alibaba_social"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"AI\"）"},
        "city": {"required": False, "description": "城市名（如 \"杭州\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "talent.alibaba.com" in url

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
        token = str(uuid.uuid4())
        try:
            with make_client() as client:
                for page in range(1, MAX_PAGES + 1):
                    payload = request_json(
                        client,
                        "POST",
                        API,
                        json_body={
                            "channel": "group_official_site",
                            "language": "zh",
                            "batchId": "",
                            "categories": "",
                            "deptCodes": [],
                            "key": keyword,
                            "pageIndex": page,
                            "pageSize": PAGE_SIZE,
                            "regions": "",
                            "subCategories": "",
                        },
                        headers={
                            "Referer": "https://talent.alibaba.com/off-campus/position-list",
                            "Origin": "https://talent.alibaba.com",
                            "cookie": f"XSRF-TOKEN={token}",
                            "x-xsrf-token": token,
                        },
                    )
                    if payload.get("success") is False:
                        return [{"error": f"阿里社招接口返回错误：{payload.get('errorMsg') or payload.get('errorCode')}"}]
                    content = payload.get("content") or {}
                    rows = content.get("datas") or []
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
                    total = int(content.get("totalCount") or 0)
                    if total and page * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"阿里社招接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"阿里社招接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 positionId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get(job_id)
        if fallback:
            result = dict(fallback)
            result["url"] = url
            result["_note"] = "详情页为前端渲染，内容来自搜索列表快照"
        else:
            result = {
                "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
                "url": url,
            }

        if not result.get("error"):
            cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id", ""))
        summary = "\n".join(
            part
            for part in (
                str(row.get("description") or ""),
                str(row.get("requirement") or ""),
            )
            if part
        )
        experience = _format_experience(row.get("experience"))
        return {
            "title": row.get("name", ""),
            "url": DETAIL.format(id=job_id),
            "company": "阿里巴巴",
            "location": "/".join(str(x) for x in (row.get("workLocations") or []) if x),
            "department": "/".join(str(x) for x in (row.get("categories") or []) if x),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "experience": experience,
            "publish_time": row.get("publishTime", ""),
            "source": "alibaba_social",
        }


def _format_experience(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    start = value.get("from")
    end = value.get("to")
    if start is not None and end is not None:
        return f"{start}-{end}年"
    if start is not None:
        return f"{start}年以上"
    if end is not None:
        return f"{end}年以下"
    return ""


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "阿里巴巴",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "alibaba_social",
    }


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("positionId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
