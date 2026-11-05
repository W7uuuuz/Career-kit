"""小米招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：GET https://hr.xiaomi.com/website/api/agent/searchJobPage
- 详情：列表响应已包含岗位描述与要求；get_detail 使用搜索时缓存的列表快照。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://hr.xiaomi.com/website/api/agent/searchJobPage"
PAGE_SIZE = 10
MAX_PAGES = 10

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """小米社会招聘 Scraper。"""

    COMPANY_SLUG = "xiaomi"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"AI\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "hr.xiaomi.com" in url or "xiaomi.jobs.f.mioffice.cn" in url

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
                        "GET",
                        API,
                        params={
                            "keyword": keyword,
                            "cityZhNames": city,
                            "pageSize": PAGE_SIZE,
                            "pageNum": page,
                        },
                        headers={"Referer": "https://hr.xiaomi.com/website/opportunities.html"},
                    )
                    if payload.get("code") != 0:
                        return [{"error": f"小米接口返回错误：{payload.get('message') or payload.get('code')}"}]
                    data = payload.get("data") or {}
                    rows = data.get("list") or []
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
                    if len(rows) < PAGE_SIZE:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"小米接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"小米接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取岗位 id：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get(job_id)
        if fallback:
            result = dict(fallback)
            result["url"] = url
            result["_note"] = "详情页为外部招聘系统，内容来自搜索列表快照"
        else:
            result = {
                "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
                "url": url,
            }

        if not result.get("error"):
            cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("jobPostId") or row.get("jobId") or row.get("id") or "")
        summary = "\n".join(
            part
            for part in (
                str(row.get("description") or ""),
                str(row.get("requirement") or ""),
            )
            if part
        )
        return {
            "title": row.get("title", ""),
            "url": row.get("url", "") or f"https://hr.xiaomi.com/website/opportunities.html?jobId={job_id}",
            "company": "小米",
            "location": "/".join(str(x) for x in (row.get("cityZhNames") or []) if x),
            "department": row.get("levelOneDeptName", ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "publish_time": row.get("publishTime", ""),
            "source": "xiaomi",
        }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "小米",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "xiaomi",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        if part.isdigit():
            return part
    query = parse_qs(parsed.query)
    return (query.get("jobId") or query.get("jobPostId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
