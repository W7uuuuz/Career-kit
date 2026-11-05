"""京东招聘 Scraper——公开列表接口（无需登录）。

接口：
- 列表：POST https://zhaopin.jd.com/web/job/job_list
- 详情：列表响应已包含岗位职责与任职要求；get_detail 使用搜索时缓存的列表快照。

列表接口返回 JSON 数组；分页从 1 开始，服务端每页 10 条。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

LIST_API = "https://zhaopin.jd.com/web/job/job_list"
LIST_PAGE = "https://zhaopin.jd.com/web/job/job_info_list/3"
PAGE_SIZE = 10
MAX_PAGES = 10

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """京东社会招聘 Scraper。"""

    COMPANY_SLUG = "jd"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"AI\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "zhaopin.jd.com" in url

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
                    form = {
                        "pageIndex": page,
                        "pageSize": PAGE_SIZE,
                        "workCityJson": "[]",
                        "jobTypeJson": "[]",
                        "jobSearch": keyword,
                        "depTypeJson": "[]",
                    }
                    payload = request_json(
                        client,
                        "POST",
                        LIST_API,
                        data=form,
                        headers={
                            "Referer": LIST_PAGE,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    )
                    if not isinstance(payload, list):
                        return [{"error": "京东接口返回格式异常：预期列表"}]
                    if not payload:
                        break
                    for row in payload:
                        item = self._format_post(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected
                    if len(payload) < PAGE_SIZE:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"京东接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"京东接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        requirement_id = _extract_id(url)
        if not requirement_id:
            return {"error": f"无法从 URL 提取 requirementId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get(requirement_id)
        if fallback:
            result = dict(fallback)
            result["url"] = url
            result["_note"] = "京东详情为列表内展开，内容来自搜索列表快照"
        else:
            result = {
                "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
                "url": url,
            }

        if not result.get("error"):
            cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        requirement_id = str(row.get("requirementId", ""))
        title = row.get("positionNameOpen") or row.get("positionName") or ""
        return {
            "title": title,
            "url": f"{LIST_PAGE}?requirementId={requirement_id}",
            "company": "京东",
            "location": row.get("workCity", ""),
            "department": row.get("positionDeptName", ""),
            "summary": _truncate(str(row.get("workContent") or ""), 800),
            "job_id": requirement_id,
            "job_type": row.get("jobType", ""),
            "publish_time": row.get("formatPublishTime", ""),
            "source": "jd",
        }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "京东",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "jd",
    }


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("requirementId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
