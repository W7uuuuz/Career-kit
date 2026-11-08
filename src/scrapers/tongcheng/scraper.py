"""同程旅行招聘 Scraper——公开 JSON 接口（无需登录）。

接口（均需请求体为 JSON，并带 ``companyId: 0583d`` 头）：
- 列表：POST https://mhr.ly.com/recruit-api/external/portal/job-list
- 详情：POST https://mhr.ly.com/recruit-api/external/portal/job-detail
- 详情页：https://mhr.ly.com/recruit/portal/#/socialDetail?id=<jobId>&type=4

queryType 口径：3-校园招聘 4-社会招聘 5-实习生招聘 6-外部推荐。
列表接口不按 workLocation 过滤，城市在本地按 workPlace 过滤。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API_LIST = "https://mhr.ly.com/recruit-api/external/portal/job-list"
API_DETAIL = "https://mhr.ly.com/recruit-api/external/portal/job-detail"
PAGE_URL = "https://mhr.ly.com/recruit/portal/"
DETAIL_URL = "https://mhr.ly.com/recruit/portal/#/socialDetail?id={id}&type=4"
QUERY_TYPE_SOCIAL = 4
PAGE_SIZE = 50
MAX_PAGES = 10

_COMMON_HEADERS = {
    "Referer": PAGE_URL,
    "Origin": "https://mhr.ly.com",
    "companyId": "0583d",
}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """同程旅行社会招聘 Scraper。"""

    COMPANY_SLUG = "tongcheng"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Agent\"、\"产品\"）；为空时拉取全量社招"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对工作地点做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "mhr.ly.com" in url

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
                        "queryType": QUERY_TYPE_SOCIAL,
                        "jobName": keyword,
                        "jobCategory": [],
                        "workLocation": [],
                        "pageNo": page_no,
                        "pageSize": PAGE_SIZE,
                    }
                    payload = request_json(
                        client,
                        "POST",
                        API_LIST,
                        json_body=body,
                        headers=_COMMON_HEADERS,
                    )
                    if payload.get("code") != 0:
                        return [{"error": f"同程旅行列表接口返回错误：{payload.get('message') or payload.get('code')}"}]
                    data = payload.get("data") or {}
                    rows = data.get("content") or []
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
                    total_pages = int(data.get("totalPages") or 0)
                    if total_pages and page_no >= total_pages:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"同程旅行接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"同程旅行接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于同程旅行：{url}"}

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
                    API_DETAIL,
                    json_body={"jobId": job_id, "queryType": QUERY_TYPE_SOCIAL, "userId": ""},
                    headers=_COMMON_HEADERS,
                )
        except ScraperHttpError as exc:
            return {"error": f"同程旅行详情请求失败：{exc}"}
        except (TypeError, ValueError) as exc:
            return {"error": f"同程旅行详情返回格式异常：{exc}"}

        if payload.get("code") != 0:
            return {"error": f"同程旅行详情接口返回错误：{payload.get('message') or payload.get('code')}"}
        data = payload.get("data") or {}
        if not data:
            fallback = _FALLBACK.get(job_id)
            if fallback:
                result = dict(fallback)
                result["url"] = url
                result["_note"] = "详情接口未返回内容，使用搜索列表快照"
                return result
            return {"error": "同程旅行详情为空，请先调用 search 获取岗位", "url": url}

        department = str(data.get("departmentName") or data.get("department") or "")
        result = {
            "title": data.get("jobName", ""),
            "company": "同程旅行",
            "location": data.get("addressName", ""),
            "department": department,
            "salary": _normalize_salary(data.get("salary")),
            "description": _html_to_text(data.get("duty")),
            "requirements": _html_to_text(data.get("qualifications")),
            "job_type": data.get("recruitmentTypeName", ""),
            "publish_time": data.get("publishTime", ""),
            "url": url,
            "source": "tongcheng",
        }
        cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("jobId", ""))
        salary = _normalize_salary(row.get("salaryRange"))
        summary_parts = [
            f"薪资: {salary}" if salary else "",
            f"工作地点: {row.get('workPlace', '')}" if row.get("workPlace") else "",
            str(row.get("employmentTypeName") or ""),
        ]
        return {
            "title": row.get("jobName", ""),
            "url": DETAIL_URL.format(id=job_id),
            "company": "同程旅行",
            "location": row.get("workPlace", ""),
            "salary": salary,
            "summary": _truncate(" | ".join(p for p in summary_parts if p), 800),
            "job_id": job_id,
            "job_type": row.get("employmentTypeName", ""),
            "publish_time": row.get("publishTime", ""),
            "source": "tongcheng",
        }


def _normalize_salary(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"0～0", "0~0", "0-0", "0—0"}:
        return ""
    return text


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "同程旅行",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": item.get("salary", ""),
        "description": "",
        "requirements": item.get("summary", ""),
        "source": "tongcheng",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    for part in reversed([p for p in parsed.path.split("/") if p]):
        if part.startswith("vuid"):
            return part
    query = parse_qs(parsed.query)
    if not query and parsed.fragment and "?" in parsed.fragment:
        query = parse_qs(parsed.fragment.split("?", 1)[1])
    return (query.get("id") or query.get("jobId") or [""])[0]


def _html_to_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
