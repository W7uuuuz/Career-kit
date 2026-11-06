"""北森（Beisen）招聘门户通用适配。

适用站点：``<tenant>.zhiye.com`` 的社招列表接口
``POST /api/Jobad/GetJobAdPageList``。列表响应已包含岗位职责（Duty）
与任职要求（Require），无需再请求详情接口。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

_FALLBACK: dict[tuple[str, str], dict[str, Any]] = {}


class BeisenScraper(CompanyScraper):
    """北森标准社招接口的通用实现。"""

    COMPANY_NAME = ""
    BASE_HOST = ""
    PORTAL_PATH = "/social/jobs"
    PAGE_SIZE = 30
    MAX_PAGES = 6
    CATEGORY: list[Any] = ["1"]

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"工艺\"）；为空时拉取最新岗位"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return super().supports_url(url)

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
                for page in range(self.MAX_PAGES):
                    body = {
                        "PageIndex": page,
                        "PageSize": self.PAGE_SIZE,
                        "Category": self.CATEGORY,
                        "KeyWords": keyword,
                        "SpecialType": 0,
                        "DisplayFields": [
                            "JobAdId",
                            "LocId",
                            "LocNames",
                            "Org",
                            "HeadCount",
                            "PostDate",
                            "Salary",
                            "Degree",
                        ],
                    }
                    payload = request_json(
                        client,
                        "POST",
                        f"{self.BASE_HOST}/api/Jobad/GetJobAdPageList",
                        json_body=body,
                        headers={"Referer": f"{self.BASE_HOST}{self.PORTAL_PATH}"},
                    )
                    if int(payload.get("Code") or 0) != 200:
                        return [{"error": f"{self.COMPANY_NAME}接口返回错误：{payload.get('Message') or payload.get('Code')}"}]

                    rows = payload.get("Data") or []
                    if not isinstance(rows, list) or not rows:
                        break

                    for row in rows:
                        item = self._format_job(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(self.COMPANY_SLUG, item)
                        if len(collected) >= limit:
                            return collected

                    count = int(payload.get("Count") or 0)
                    if count and (page + 1) * self.PAGE_SIZE >= count:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"{self.COMPANY_NAME}接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"{self.COMPANY_NAME}接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("Id") or row.get("JobAdId") or "")
        loc_names = row.get("LocNames") or []
        location = "/".join(str(name) for name in loc_names if name)
        duty = str(row.get("Duty") or "")
        require = str(row.get("Require") or "")
        summary = _truncate("\n".join(part for part in (duty, require) if part), 800)
        return {
            "title": row.get("JobAdName", ""),
            "url": f"{self.BASE_HOST}{self.PORTAL_PATH}?jobAdId={job_id}",
            "company": self.COMPANY_NAME,
            "location": location,
            "department": row.get("Org") or row.get("ClassificationOne") or "",
            "summary": summary,
            "description": duty,
            "requirements": require,
            "job_id": job_id,
            "salary": row.get("Salary") or "",
            "education": row.get("Degree") or "",
            "source": self.COMPANY_SLUG,
        }

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_query(url, "jobAdId") or _extract_query(url, "jobId")
        if not job_id:
            return {"error": f"无法从 URL 提取 jobAdId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get((self.COMPANY_SLUG, job_id))
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


def _remember(slug: str, item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 1000:
        _FALLBACK.clear()
    _FALLBACK[(slug, item["job_id"])] = {
        "title": item.get("title", ""),
        "company": item.get("company", ""),
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": item.get("salary", ""),
        "description": item.get("description") or item.get("summary", ""),
        "requirements": item.get("requirements", ""),
        "education": item.get("education", ""),
        "source": slug,
    }


def _extract_query(url: str, name: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get(name) or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\r", "").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
