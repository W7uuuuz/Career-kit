"""滴滴招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：GET https://talent.didiglobal.com/recruit-portal-service/api/job/front/list
- 详情：https://talent.didiglobal.com/social/p/<jdId>

列表响应已包含岗位职责与任职要求；get_detail 优先使用搜索时缓存的列表快照。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://talent.didiglobal.com/recruit-portal-service/api/job/front/list"
DETAIL = "https://talent.didiglobal.com/social/p/{id}"
PAGE_SIZE = 10
MAX_PAGES = 10

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """滴滴社会招聘 Scraper。"""

    COMPANY_SLUG = "didi"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"AI\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "talent.didiglobal.com" in url

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
                        params={"jobName": keyword, "page": page, "size": PAGE_SIZE},
                        headers={"Referer": "https://talent.didiglobal.com/social/"},
                    )
                    if (payload.get("meta") or {}).get("code") != 0:
                        return [{"error": f"滴滴接口返回错误：{(payload.get('meta') or {}).get('message')}"}]
                    data = payload.get("data") or {}
                    rows = data.get("items") or []
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
                    total = int(data.get("total") or 0)
                    if total and page * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"滴滴接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"滴滴接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jdId：{url}"}

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
        job_id = str(row.get("jdId", ""))
        summary = "\n".join(
            part
            for part in (
                str(row.get("jobDuty") or ""),
                str(row.get("jobQualification") or ""),
            )
            if part
        )
        return {
            "title": row.get("jobName", ""),
            "url": DETAIL.format(id=job_id),
            "company": "滴滴",
            "location": row.get("workArea", ""),
            "department": row.get("deptName", ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "job_type": row.get("jobTypeName", ""),
            "publish_time": row.get("refreshTime", ""),
            "source": "didi",
        }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "滴滴",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "didi",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[-1].isdigit():
        return parts[-1]
    query = parse_qs(parsed.query)
    return (query.get("jdId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
