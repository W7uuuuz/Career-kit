"""华为社会招聘 Scraper。

接口：
- 列表：POST https://apigw-dgg-b0.huawei.com/api/apig/channelhw/recruitmentPosition/pub/getJobPage
- 列表响应已包含岗位职责（mainBusiness）与任职要求（jobRequire）
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://apigw-dgg-b0.huawei.com/api/apig/channelhw/recruitmentPosition/pub/getJobPage"
DETAIL = "https://career.huawei.com/cn/social-recruitment-job-list?jobId={id}"
PAGE_SIZE = 50
MAX_PAGES = 12

_HEADERS = {
    "Referer": "https://career.huawei.com/",
    "x-hw-id": "app_000000035886",
    "x-jalor-tenantalias": "hcm",
    "x-language": "zh_CN",
    "x-referer": "https://career.huawei.com/cn",
    "x-alb-gray": "prod",
}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """华为社会招聘 Scraper。"""

    COMPANY_SLUG = "huawei"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"算法\"），对岗位名称/JD/部门做本地过滤"},
        "city": {"required": False, "description": "城市名（如 \"深圳\"），对工作地点做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "career.huawei.com" in url

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
                        API,
                        json_body={"curPage": page, "pageSize": PAGE_SIZE, "jobType": "SR"},
                        headers=_HEADERS,
                    )
                    if payload.get("status") != "SUCCESS":
                        return [{"error": f"华为接口返回错误：{payload.get('code') or payload.get('message')}"}]

                    data = payload.get("data") or {}
                    rows = data.get("result") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_job(row)
                        if keyword and keyword.lower() not in _search_text(item):
                            continue
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected

                    page_vo = data.get("pageVO") or {}
                    total_pages = int(page_vo.get("totalPages") or 0)
                    if total_pages and page >= total_pages:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"华为接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"华为接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("jobId", ""))
        duty = str(row.get("mainBusiness") or "")
        require = str(row.get("jobRequire") or "")
        summary = _truncate("\n".join(part for part in (duty, require) if part), 800)
        return {
            "title": row.get("jobName", ""),
            "url": DETAIL.format(id=job_id),
            "company": "华为",
            "location": row.get("workPlace", ""),
            "department": row.get("deptName") or row.get("firstDeptName") or "",
            "summary": summary,
            "description": duty,
            "requirements": require,
            "job_id": job_id,
            "job_family": row.get("jobFamilyName", ""),
            "experience": row.get("workYear", ""),
            "education": row.get("degree", ""),
            "publish_date": row.get("lastUpdateDate", ""),
            "source": "huawei",
        }

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jobId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get(job_id)
        if fallback:
            result = dict(fallback)
            result["url"] = url
            result["_note"] = "列表接口已包含完整 JD，内容来自搜索列表快照"
        else:
            result = {
                "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
                "url": url,
            }

        if not result.get("error"):
            cache.set(key, result)
        return result


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 1000:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "华为",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("description") or item.get("summary", ""),
        "requirements": item.get("requirements", ""),
        "job_family": item.get("job_family", ""),
        "experience": item.get("experience", ""),
        "source": "huawei",
    }


def _search_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "description", "requirements", "department", "job_family")
    ).lower()


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("jobId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\r", "").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
