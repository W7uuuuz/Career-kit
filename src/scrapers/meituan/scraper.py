"""美团招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：POST https://zhaopin.meituan.com/api/official/job/getJobList
- 详情：https://zhaopin.meituan.com/web/position/detail?jobUnionId=<id>

列表响应已包含岗位职责与要求；详情接口为前端页面，get_detail 优先使用
搜索时缓存的列表快照。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://zhaopin.meituan.com/api/official/job/getJobList"
DETAIL = "https://zhaopin.meituan.com/web/position/detail?jobUnionId="
PAGE_SIZE = 100
MAX_PAGES = 5

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """美团招聘 Scraper。"""

    COMPANY_SLUG = "meituan"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"后端\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），服务端过滤并做本地兜底"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "zhaopin.meituan.com" in url

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
                for page_no in range(1, MAX_PAGES + 1):
                    body = {
                        "page": {"pageNo": page_no, "pageSize": PAGE_SIZE},
                        "keywords": keyword,
                        "jobShareType": "1",
                        "jobType": [{"code": "3", "subCode": []}],
                        "cityList": [{"name": city}] if city else [],
                        "department": [],
                        "jfJgList": [],
                        "typeCode": [],
                        "specialCode": [],
                    }
                    payload = request_json(
                        client,
                        "POST",
                        API,
                        json_body=body,
                        headers={"Referer": "https://zhaopin.meituan.com/web/social"},
                    )
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
                    total = int((data.get("page") or {}).get("totalCount") or 0)
                    if total and page_no * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"美团接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"美团接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jobUnionId：{url}"}

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
        job_id = str(row.get("jobUnionId", ""))
        location = _names(row.get("cityList"))
        department = _names(row.get("department"))
        summary = "\n".join(
            part
            for part in (
                f"部门: {department}" if department else "",
                f"序列: {row.get('jobFamily', '')}" if row.get("jobFamily") else "",
                f"经验: {row.get('workYear', '')}" if row.get("workYear") else "",
                str(row.get("jobDuty") or ""),
                str(row.get("jobRequirement") or ""),
            )
            if part
        )
        return {
            "title": row.get("name", ""),
            "url": f"{DETAIL}{job_id}",
            "company": "美团",
            "location": location,
            "department": department,
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "source": "meituan",
        }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "美团",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "meituan",
    }


def _names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return "/".join(names)


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("jobUnionId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
