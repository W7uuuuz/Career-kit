"""大易（Dayee）招聘门户通用适配。

适用站点：``*.hotjob.cn`` 的 PB 模板社招列表。
- 列表：``POST /wecruit/positionInfo/listPosition/<suiteKey>``
- 详情：``POST /wecruit/positionInfo/listPositionDetail/<suiteKey>``
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json


class DayeeScraper(CompanyScraper):
    """大易 PB 模板社招接口的通用实现。"""

    COMPANY_NAME = ""
    BASE_HOST = ""
    SUITE_KEY = ""
    PAGE_SIZE = 50
    MAX_PAGES = 10

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"工艺\"、\"电气\"），对岗位名称/类别/公司做本地过滤"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对工作地点做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return bool(self.SUITE_KEY) and self.SUITE_KEY.lower() in url.lower()

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
        url = (
            f"{self.BASE_HOST}/wecruit/positionInfo/listPosition/{self.SUITE_KEY}"
            "?iSaJAx=isAjax&request_locale=zh_CN"
        )
        headers = {"Referer": f"{self.BASE_HOST}/{self.SUITE_KEY}/pb/social.html"}
        try:
            with make_client() as client:
                for page in range(1, self.MAX_PAGES + 1):
                    payload = request_json(
                        client,
                        "POST",
                        url,
                        data={
                            "isFrompb": "true",
                            "recruitType": "2",
                            "pageSize": str(self.PAGE_SIZE),
                            "currentPage": str(page),
                        },
                        headers=headers,
                    )
                    if str(payload.get("state")) != "200":
                        return [{"error": f"{self.COMPANY_NAME}接口返回错误：{payload.get('state') or payload.get('type')}"}]

                    page_form = (payload.get("data") or {}).get("pageForm") or {}
                    rows = page_form.get("pageData") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_job(row)
                        if keyword and keyword.lower() not in _search_text(item):
                            continue
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected

                    total_page = int(page_form.get("totalPage") or 0)
                    if total_page and page >= total_page:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"{self.COMPANY_NAME}接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"{self.COMPANY_NAME}接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("postId", ""))
        post_type = str(row.get("postType", ""))
        summary = " / ".join(
            part
            for part in (
                str(row.get("postTypeName") or ""),
                str(row.get("educationStr") or ""),
                f"招聘 {row.get('recruitNumStr')}" if row.get("recruitNumStr") else "",
            )
            if part
        )
        return {
            "title": row.get("postName", ""),
            "url": f"{self.BASE_HOST}/{self.SUITE_KEY}/pb/posDetail.html?postId={job_id}&postType={post_type}",
            "company": self.COMPANY_NAME,
            "location": row.get("workPlaceStr", ""),
            "department": row.get("company") or row.get("orgName") or "",
            "summary": summary,
            "job_id": job_id,
            "job_type": row.get("postTypeName", ""),
            "education": row.get("educationStr", ""),
            "publish_date": row.get("publishDate", ""),
            "source": self.COMPANY_SLUG,
        }

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_query(url, "postId")
        if not job_id:
            return {"error": f"无法从 URL 提取 postId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        detail_url = (
            f"{self.BASE_HOST}/wecruit/positionInfo/listPositionDetail/{self.SUITE_KEY}"
            "?iSaJAx=isAjax&request_locale=zh_CN"
        )
        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "POST",
                    detail_url,
                    data={"postId": job_id, "recruitType": "2"},
                    headers={"Referer": url},
                )
        except ScraperHttpError as exc:
            return {"error": f"{self.COMPANY_NAME}详情请求失败：{exc}"}
        except (TypeError, ValueError) as exc:
            return {"error": f"{self.COMPANY_NAME}详情返回格式异常：{exc}"}

        if str(payload.get("state")) != "200":
            return {"error": f"{self.COMPANY_NAME}详情接口返回错误：{payload.get('state') or payload.get('type')}"}

        data = payload.get("data") or {}
        result = {
            "title": data.get("postName", ""),
            "company": self.COMPANY_NAME,
            "location": data.get("workPlaceStr", ""),
            "department": data.get("orgName") or data.get("company") or "",
            "salary": data.get("salary") or "",
            "description": data.get("workContent", ""),
            "requirements": data.get("serviceCondition", ""),
            "education": data.get("education", ""),
            "job_type": data.get("postTypeName", ""),
            "publish_date": data.get("publishDate", ""),
            "url": url,
            "source": self.COMPANY_SLUG,
        }
        if not result.get("error"):
            cache.set(key, result)
        return result


def _search_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "job_type", "department", "location")
    ).lower()


def _extract_query(url: str, name: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get(name) or [""])[0]
