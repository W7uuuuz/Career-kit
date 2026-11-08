"""SHEIN 招聘 Scraper——公开 JSON 接口（无需登录/签名）。

接口（Playwright 抓包确认）：
- 列表：POST https://careers.shein.com/api/v1/open/grw/front/jobPage
- 详情：列表响应已含完整 description；get_detail 用 jobIds 过滤重新拉取单条
- 详情页：列表记录里的 jobDetailUrl（自有 Avature 或 Greenhouse 落地页）

请求体为 JSON，无需签名，直接 POST 即可。langCode 固定 EN（SHEIN 全球站）。
"""

from __future__ import annotations

import html as _html
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API = "https://careers.shein.com/api/v1/open/grw/front/jobPage"
PORTAL = "https://careers.shein.com/All-Jobs"
LANG = "EN"
PAGE_SIZE = 10
MAX_PAGES = 20

# job_type 入参归一化：中文/英文别名 -> SHEIN jobTypeId
JOB_TYPES: dict[str, str] = {
    "social": "SOCIAL",
    "社招": "SOCIAL",
    "专业": "SOCIAL",
    "campus": "CAMPUS",
    "校招": "CAMPUS",
    "应届": "CAMPUS",
    "intern": "PRACTICE",
    "practice": "PRACTICE",
    "实习": "PRACTICE",
}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """SHEIN 全球招聘 Scraper。"""

    COMPANY_SLUG = "shein"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"engineer\"、\"算法\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"Shanghai\"、\"深圳市\"），服务端按 cityName 过滤"},
        "job_type": {
            "required": False,
            "description": "招聘类型：social/社招、campus/校招、intern/实习；为空时全部",
        },
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100（每页 10 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "careers.shein.com" in url or "job-boards.greenhouse.io/shein" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        job_type = _normalize_job_type(kwargs.get("job_type"))
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, job_type=job_type, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, job_type, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _fetch_jobs(
        self, keyword: str, city: str, job_type: str, limit: int
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        try:
            with make_client() as client:
                for page in range(1, MAX_PAGES + 1):
                    body = {
                        "current": page,
                        "cityName": city,
                        "jobCategoryIds": [],
                        "countryIds": [],
                        "cityIds": [],
                        "jobTypeIds": [job_type] if job_type else [],
                        "jobIds": [],
                        "key": keyword,
                        "langCode": LANG,
                        "size": PAGE_SIZE,
                    }
                    payload = request_json(
                        client,
                        "POST",
                        API,
                        json_body=body,
                        headers={
                            "Referer": PORTAL,
                            "Origin": "https://careers.shein.com",
                        },
                    )
                    if str(payload.get("code")) != "0":
                        return [{"error": f"SHEIN 接口返回错误：{payload.get('msg') or payload.get('code')}"}]

                    info = payload.get("info") or {}
                    rows = info.get("records") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_post(row)
                        if city and not _matches_city(item, city):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected[:limit]

                    total = int(info.get("total") or 0)
                    if total and page * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"SHEIN 接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"SHEIN 接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于SHEIN：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 SHEIN 岗位 id：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        # 优先用 jobIds 过滤实时拉取单条，拿最新正文
        try:
            with make_client() as client:
                body = {
                    "current": 1,
                    "cityName": "",
                    "jobCategoryIds": [],
                    "countryIds": [],
                    "cityIds": [],
                    "jobTypeIds": [],
                    "jobIds": [job_id],
                    "key": "",
                    "langCode": LANG,
                    "size": 10,
                }
                payload = request_json(
                    client,
                    "POST",
                    API,
                    json_body=body,
                    headers={"Referer": PORTAL, "Origin": "https://careers.shein.com"},
                )
                rows = (payload.get("info") or {}).get("records") or []
                if rows:
                    result = _detail_from_row(rows[0], url)
                    cache.set(key, result)
                    return result
        except ScraperHttpError:
            pass

        snapshot = _FALLBACK.get(job_id)
        if snapshot:
            result = dict(snapshot)
            result["url"] = url
            result["_note"] = "详情接口不可用，内容来自搜索列表快照"
            cache.set(key, result)
            return result

        return {
            "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
            "url": url,
        }

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("jobId") or "")
        summary = _clean_text(row.get("description") or "")
        detail_url = row.get("jobDetailUrl") or PORTAL
        return {
            "title": row.get("jobTitle", ""),
            "url": detail_url,
            "company": "SHEIN",
            "location": _location(row),
            "department": row.get("jobCategoryName", ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "job_type": row.get("jobTypeId", ""),
            "publish_time": row.get("releaseDate", ""),
            "source": "shein",
        }


def _detail_from_row(row: dict[str, Any], url: str) -> dict[str, Any]:
    description = _clean_text(row.get("description") or "")
    return {
        "title": row.get("jobTitle", ""),
        "company": "SHEIN",
        "location": _location(row),
        "department": row.get("jobCategoryName", ""),
        "salary": "",
        "description": description,
        "requirements": "",
        "url": url,
        "source": "shein",
    }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "SHEIN",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "shein",
    }


def _normalize_job_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return JOB_TYPES.get(text, text.upper())


def _location(row: dict[str, Any]) -> str:
    cities = [
        str(c.get("cityName"))
        for c in (row.get("cityInfos") or [])
        if isinstance(c, dict) and c.get("cityName")
    ]
    country = str(row.get("countryName") or "")
    parts = []
    if cities:
        parts.append("/".join(cities))
    if country:
        parts.append(country)
    return ", ".join(parts)


def _matches_city(item: dict[str, Any], city: str) -> bool:
    return city.lower() in (item.get("location") or "").lower()


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    job_id = (query.get("jobId") or query.get("id") or [""])[0]
    if job_id:
        return job_id
    for part in reversed([p for p in parsed.path.split("/") if p]):
        if part.isdigit():
            return part
    return ""


def _clean_text(raw: str) -> str:
    """把接口返回的 HTML 正文转成可读纯文本。"""
    if not raw:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    text = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
