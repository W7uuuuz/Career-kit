"""OPPO 招聘 Scraper——官网公开 JSON 接口（无需登录/签名）。

接口（Playwright 抓包 + 前端 JS 确认）：
- 列表：POST https://careers.oppo.com/openapi/position/pageNew
  请求体：pageNum / pageSize / positionName / projectList /
          positionTypeList / workCityCodeList / shareId
- 详情：GET https://careers.oppo.com/openapi/position/detail?id=<idRecruitPosition>
- 城市：GET https://careers.oppo.com/openapi/offer/office/location/chnCityList
  用于把城市名映射成 workCityCode
- 详情页：https://careers.oppo.com/university/oppo/campus/post/<id>

说明：OPPO 官网当前对外公开可抓的岗位列表即 `pageNew` 接口返回的这批岗位
（校园招聘/国际化招聘/博士生等招聘项目，共 200+ 条），列表响应已含完整职责与要求。
"""

from __future__ import annotations

import re
from typing import Any

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

OPENAPI = "https://careers.oppo.com/openapi"
LIST_API = f"{OPENAPI}/position/pageNew"
DETAIL_API = f"{OPENAPI}/position/detail"
CITY_API = f"{OPENAPI}/offer/office/location/chnCityList"
PORTAL = "https://careers.oppo.com/university/oppo/campus/post"
PAGE_SIZE = 20
MAX_PAGES = 15

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """OPPO 官方招聘 Scraper。"""

    COMPANY_SLUG = "oppo"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"算法\"、\"软件\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"深圳市\"、\"东莞市\"），自动映射为 workCityCode"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100（接口每页 20 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "careers.oppo.com" in url

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
                city_code = _resolve_city_code(client, city)
                for page in range(1, MAX_PAGES + 1):
                    body = {
                        "pageNum": page,
                        "pageSize": PAGE_SIZE,
                        "positionName": keyword,
                        "projectList": [],
                        "positionTypeList": [],
                        "workCityCodeList": [city_code] if city_code else [],
                        "shareId": "",
                    }
                    payload = request_json(
                        client,
                        "POST",
                        LIST_API,
                        json_body=body,
                        headers={"Referer": PORTAL, "Origin": "https://careers.oppo.com"},
                    )
                    if payload.get("code") != 0:
                        return [{"error": f"OPPO 接口返回错误：{payload.get('message') or payload.get('code')}"}]

                    data = payload.get("data") or {}
                    rows = data.get("records") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_post(row)
                        if city and not city_code and not _matches_city(item, city):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            return collected[:limit]

                    total = int(data.get("total") or 0)
                    if total and page * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"OPPO 接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"OPPO 接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于OPPO：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 OPPO 岗位 id：{url}"}

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
                    params={"id": job_id},
                    headers={"Referer": _detail_url(job_id)},
                )
                data = payload.get("data") or {}
                if payload.get("code") == 0 and data.get("positionName"):
                    result = _detail_from_record(data, url)
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
        job_id = str(row.get("idRecruitPosition") or "")
        summary = "\n".join(
            part
            for part in (
                str(row.get("positionDesc") or ""),
                str(row.get("knowledgeSkill") or ""),
            )
            if part
        )
        return {
            "title": row.get("positionName", ""),
            "url": _detail_url(job_id),
            "company": "OPPO",
            "location": row.get("workCityName", ""),
            "department": row.get("positionTypeName", "") or row.get("projectName", ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "project": row.get("projectName", ""),
            "recruitment_type": row.get("recruitmentTypeName", ""),
            "publish_time": row.get("releaseTime", ""),
            "source": "oppo",
        }


def _detail_from_record(row: dict[str, Any], url: str) -> dict[str, Any]:
    requirements = "\n".join(
        part
        for part in (
            str(row.get("positionRequire") or ""),
            str(row.get("knowledgeSkill") or ""),
            str(row.get("bonusItem") or ""),
        )
        if part
    )
    return {
        "title": row.get("positionName", ""),
        "company": "OPPO",
        "location": row.get("workCityName", ""),
        "department": row.get("positionTypeName", "") or row.get("projectName", ""),
        "salary": "",
        "description": str(row.get("positionDesc") or ""),
        "requirements": requirements,
        "project": row.get("projectName", ""),
        "recruitment_type": row.get("recruitmentTypeName", ""),
        "url": url,
        "source": "oppo",
    }


def _resolve_city_code(client: Any, city: str) -> str:
    if not city:
        return ""
    payload = request_json(
        client,
        "GET",
        CITY_API,
        headers={"Referer": PORTAL},
    )
    rows = payload.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("list") or rows.get("records") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("cityName") or "")
        code = str(row.get("cityCode") or "")
        if name and code and name == city:
            return code
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("cityName") or "")
        code = str(row.get("cityCode") or "")
        if name and code and city in name:
            return code
    return ""


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "OPPO",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "oppo",
    }


def _detail_url(job_id: str) -> str:
    return f"{PORTAL}/{job_id}"


def _matches_city(item: dict[str, Any], city: str) -> bool:
    return city in (item.get("location") or "")


def _extract_id(url: str) -> str:
    for part in reversed([p for p in url.split("?")[0].split("/") if p]):
        if part.isdigit():
            return part
    match = re.search(r"[?&]id=(\d+)", url)
    return match.group(1) if match else ""


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
