"""Shopee 招聘 Scraper——Workatsea ATS 公开接口（无需登录/签名）。

接口（Playwright 抓包 + 前端 JS 确认）：
- 列表：GET https://ats.workatsea.com/ats/api/v1/user/job/list/
  参数：limit / offset / search_content / city_ids / department_ids / employment_ids
- 详情：GET https://ats.workatsea.com/ats/api/v1/user/job/?job_id=<J 开头的字符串 id>
- 元数据：GET https://ats.workatsea.com/ats/api/v1/user/meta/slice/
  用于把 city_id / region_id / department_id 映射成可读名称
- 详情页：https://careers.shopee.cn/job-detail/<job_id>/1

列表响应已包含 job_description 与 requirements；get_detail 优先调详情接口。
"""

from __future__ import annotations

import html as _html
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

BASE = "https://ats.workatsea.com/ats/api/v1/user"
LIST_API = f"{BASE}/job/list/"
DETAIL_API = f"{BASE}/job/"
META_API = f"{BASE}/meta/slice/"
PORTAL = "https://careers.shopee.cn"
META_FLAGS = 2147851120
PAGE_SIZE = 50
MAX_PAGES = 10

# 前端会过滤掉 region_id=28（Taipei 独立站），这里保持一致
_EXCLUDED_REGION_IDS = {28}

# 常见中文城市到 Workatsea city_name 的对照（接口客户端名为英文）
CITY_ALIASES: dict[str, str] = {
    "上海": "Shanghai",
    "深圳": "Shenzhen",
    "北京": "Beijing",
    "广州": "Guangzhou",
    "香港": "Hong Kong",
    "新加坡": "Singapore",
    "台北": "Taipei",
    "吉隆坡": "Kuala Lumpur",
    "曼谷": "Bangkok",
    "雅加达": "Jakarta",
}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """Shopee（Workatsea ATS）招聘 Scraper。"""

    COMPANY_SLUG = "shopee"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"engineer\"、\"Python\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"Shanghai\"、\"上海\"），自动映射为 city_ids"},
        "department": {"required": False, "description": "部门名（如 \"Engineering and Technology\"），自动映射为 department_ids"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100（接口每页 50 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "careers.shopee.cn" in url or "ats.workatsea.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        department = (kwargs.get("department") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, department=department, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs(keyword, city, department, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _fetch_jobs(
        self, keyword: str, city: str, department: str, limit: int
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        try:
            with make_client() as client:
                cities, regions, depts = _fetch_meta(client)
                city_id = _resolve_city_id(city, cities)
                dept_id = _resolve_dept_id(department, depts)

                offset = 0
                for _ in range(MAX_PAGES):
                    params: dict[str, Any] = {
                        "limit": PAGE_SIZE,
                        "offset": offset,
                    }
                    if keyword:
                        params["search_content"] = keyword
                    if city_id:
                        params["city_ids"] = city_id
                    if dept_id:
                        params["department_ids"] = dept_id

                    payload = request_json(
                        client,
                        "GET",
                        LIST_API,
                        params=params,
                        headers={"Referer": f"{PORTAL}/jobs"},
                    )
                    if payload.get("code") != 0:
                        return [{"error": f"Shopee 接口返回错误：{payload.get('message') or payload.get('code')}"}]

                    data = payload.get("data") or {}
                    rows = data.get("job_list") or []
                    total = int(data.get("total_count") or 0)
                    if not rows:
                        break

                    for row in rows:
                        if int(row.get("region_id") or 0) in _EXCLUDED_REGION_IDS:
                            continue
                        item = self._format_post(row, cities, regions, depts)
                        if city and not city_id and not _matches_city(item, city):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected[:limit]

                    offset += PAGE_SIZE
                    if total and offset >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"Shopee 接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"Shopee 接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于Shopee：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 Shopee 岗位 id：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "GET",
                    DETAIL_API,
                    params={"job_id": job_id},
                    headers={"Referer": f"{PORTAL}/jobs"},
                )
                data = payload.get("data") or {}
                if payload.get("code") == 0 and data.get("job_id"):
                    cities, regions, depts = _fetch_meta(client)
                    result = _detail_from_record(data, url, cities, regions, depts)
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

    def _format_post(
        self,
        row: dict[str, Any],
        cities: dict[str, str],
        regions: dict[str, str],
        depts: dict[str, str],
    ) -> dict[str, Any]:
        job_id = str(row.get("job_id") or "")
        summary = "\n".join(
            part
            for part in (
                _clean_text(row.get("job_description") or ""),
                _clean_text(row.get("requirements") or ""),
            )
            if part
        )
        return {
            "title": row.get("job_name", ""),
            "url": f"{PORTAL}/job-detail/{job_id}/1",
            "company": "Shopee",
            "location": _location(row, cities, regions),
            "department": depts.get(str(row.get("department_id") or ""), ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "source": "shopee",
        }


def _fetch_meta(client: Any) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    payload = request_json(
        client,
        "GET",
        META_API,
        params={"flags": META_FLAGS, "from_career": "true"},
        headers={"Referer": f"{PORTAL}/jobs"},
    )
    data = payload.get("data") or {}

    cities: dict[str, str] = {}
    regions: dict[str, str] = {}
    for loc in data.get("flat_locations") or []:
        cid = loc.get("city_id")
        cname = loc.get("city_name")
        if cid is not None and cname:
            cities[str(cid)] = str(cname)
        rid = loc.get("region_id")
        rname = loc.get("region_name")
        if rid is not None and rname:
            regions[str(rid)] = str(rname)

    depts: dict[str, str] = {}
    for dept in data.get("dept_list") or []:
        did = dept.get("dept_id")
        dname = dept.get("dept_name")
        if did is not None and dname:
            depts[str(did)] = str(dname)

    return cities, regions, depts


def _detail_from_record(
    row: dict[str, Any],
    url: str,
    cities: dict[str, str],
    regions: dict[str, str],
    depts: dict[str, str],
) -> dict[str, Any]:
    requirements = "\n".join(
        part
        for part in (
            _clean_text(row.get("requirements") or ""),
            _clean_text(row.get("sub_team_description") or ""),
        )
        if part
    )
    return {
        "title": row.get("job_name", ""),
        "company": "Shopee",
        "location": _location(row, cities, regions),
        "department": depts.get(str(row.get("department_id") or ""), ""),
        "salary": "",
        "description": _clean_text(row.get("job_description") or ""),
        "requirements": requirements,
        "url": url,
        "source": "shopee",
    }


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "Shopee",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "shopee",
    }


def _resolve_city_id(city: str, cities: dict[str, str]) -> str:
    if not city:
        return ""
    target = CITY_ALIASES.get(city, city).strip().lower()
    for cid, name in cities.items():
        if name.strip().lower() == target:
            return cid
    for cid, name in cities.items():
        if target in name.strip().lower():
            return cid
    return ""


def _resolve_dept_id(department: str, depts: dict[str, str]) -> str:
    if not department:
        return ""
    target = department.strip().lower()
    for did, name in depts.items():
        if name.strip().lower() == target:
            return did
    for did, name in depts.items():
        if target in name.strip().lower():
            return did
    return ""


def _location(row: dict[str, Any], cities: dict[str, str], regions: dict[str, str]) -> str:
    city = cities.get(str(row.get("city_id") or ""), "")
    region = regions.get(str(row.get("region_id") or ""), "")
    parts = []
    if city:
        parts.append(city)
    if region and region != city:
        parts.append(region)
    return ", ".join(parts)


def _matches_city(item: dict[str, Any], city: str) -> bool:
    target = CITY_ALIASES.get(city, city).strip().lower()
    return target in (item.get("location") or "").lower()


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    job_id = (query.get("job_id") or query.get("jobId") or [""])[0]
    if job_id:
        return job_id
    parts = [p for p in parsed.path.split("/") if p]
    for part in parts:
        if part.upper().startswith("J") and part[1:].isdigit():
            return part
    for part in reversed(parts):
        if part.isdigit() and len(part) >= 5:
            return part
    return ""


def _clean_text(raw: str) -> str:
    """把接口返回的 HTML 正文转成可读纯文本。"""
    if not raw:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    text = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6]|tr|blockquote)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
