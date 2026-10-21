"""腾讯招聘 Scraper——社招走 careers.tencent.com，校招/实习走 join.qq.com。

参考实现：
- https://github.com/HA7CH/job-pro （join.qq.com 校招接口与 scope 映射）
- https://github.com/Nanaeo/RecruitSpider （careers.tencent.com Query/ByPostId）

两个站点均为公开接口，无需登录：
- 社招：GET /tencentcareer/api/post/Query + /ByPostId
- 校招/实习：POST /api/v1/position/searchPosition + GET getJobDetailsByPostId

腾讯不公开薪资，salary 字段返回空字符串。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

SOCIAL_BASE = "https://careers.tencent.com"
SOCIAL_QUERY = f"{SOCIAL_BASE}/tencentcareer/api/post/Query"
SOCIAL_DETAIL = f"{SOCIAL_BASE}/tencentcareer/api/post/ByPostId"

CAMPUS_BASE = "https://join.qq.com"
CAMPUS_API = f"{CAMPUS_BASE}/api/v1"
CAMPUS_POSTS_PAGE = f"{CAMPUS_BASE}/post.html"
CAMPUS_DETAIL_PAGE = f"{CAMPUS_BASE}/post_detail.html"

# 社招站点城市 ID（实测：1=深圳 2=北京 3=上海 5=广州 6=武汉 7=杭州 8=成都 14=重庆）
SOCIAL_CITY_CODES: dict[str, str] = {
    "深圳": "1", "北京": "2", "上海": "3", "广州": "5",
    "武汉": "6", "杭州": "7", "成都": "8", "重庆": "14",
}

# 校招站点工作城市 ID
CAMPUS_CITY_CODES: dict[str, str] = {
    "深圳": "1", "北京": "2", "上海": "3", "广州": "5",
    "武汉": "6", "杭州": "7", "成都": "8", "南京": "11",
    "重庆": "14", "贵阳": "17", "长沙": "18", "厦门": "29",
    "合肥": "30", "天津": "31",
}


class Scraper(CompanyScraper):
    """腾讯招聘 Scraper。"""

    COMPANY_SLUG = "tencent"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"后端\"）"},
        "city": {"required": False, "description": "城市名（如 \"深圳\"、\"北京\"），未匹配时不加城市过滤"},
        "scope": {"required": False, "description": "招聘类型：social=社招(默认), campus=校招, intern=实习"},
        "limit": {"required": False, "description": "返回数量上限，默认 20"},
    }

    def supports_url(self, url: str) -> bool:
        return "careers.tencent.com" in url or "join.qq.com" in url

    # ------------------------------------------------------------------ search

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        scope = (kwargs.get("scope") or "social").strip().lower()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        if scope not in ("social", "campus", "intern", "all"):
            return [{"error": f"scope 必须是 social/campus/intern，收到：{scope}"}]

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, scope=scope, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        if scope == "social":
            results = self._search_social(keyword, city, limit)
        else:
            results = self._search_campus(keyword, city, scope, limit)

        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _search_social(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        city_code = SOCIAL_CITY_CODES.get(city, "")
        params = {
            "timestamp": _timestamp(),
            "countryId": "",
            "cityId": city_code,
            "bgIds": "",
            "productId": "",
            "categoryId": "",
            "parentCategoryId": "",
            "attrId": "1",
            "keyword": keyword,
            "pageIndex": "1",
            "pageSize": str(min(limit, 20)),
            "language": "zh-cn",
            "area": "cn",
        }
        try:
            with make_client() as client:
                payload = request_json(client, "GET", SOCIAL_QUERY, params=params)
        except ScraperHttpError as exc:
            return [{"error": f"腾讯社招接口请求失败：{exc}"}]

        if payload.get("Code") != 200:
            return [{"error": f"腾讯社招接口返回错误：{payload.get('Code')}"}]

        posts = (payload.get("Data") or {}).get("Posts") or []
        if not posts:
            return [{"error": "未找到相关岗位", "keyword": keyword}]
        return [self._format_social_post(p) for p in posts[:limit]]

    def _search_campus(
        self, keyword: str, city: str, scope: str, limit: int
    ) -> list[dict[str, Any]]:
        mapping_ids, error = self._resolve_mapping_ids(scope)
        if error:
            return [{"error": error}]

        city_code = CAMPUS_CITY_CODES.get(city, "")
        body = {
            "projectIdList": [],
            "projectMappingIdList": mapping_ids,
            "keyword": keyword,
            "bgList": [],
            "workCountryType": 0,
            "workCityList": [int(city_code)] if city_code.isdigit() else [],
            "recruitCityList": [],
            "positionFidList": [],
            "pageIndex": 1,
            "pageSize": min(limit, 100),
        }
        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "POST",
                    f"{CAMPUS_API}/position/searchPosition",
                    params={"timestamp": _timestamp()},
                    json_body=body,
                    headers={"Referer": CAMPUS_POSTS_PAGE, "Origin": CAMPUS_BASE},
                )
        except ScraperHttpError as exc:
            return [{"error": f"腾讯校招接口请求失败：{exc}"}]

        if payload.get("status") != 0:
            return [{"error": f"腾讯校招接口返回错误：{payload.get('message') or payload.get('status')}"}]

        rows = (payload.get("data") or {}).get("positionList") or []
        if not rows:
            return [{"error": "未找到相关岗位", "keyword": keyword}]
        return [self._format_campus_post(p) for p in rows[:limit]]

    def _resolve_mapping_ids(self, scope: str) -> tuple[list[int], str]:
        """把 campus/intern 映射为 join.qq.com 的 projectMappingIdList。"""
        if scope == "all":
            return [], ""
        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "GET",
                    f"{CAMPUS_API}/position/getProjectMapping",
                    params={"timestamp": _timestamp()},
                    headers={"Referer": CAMPUS_POSTS_PAGE, "Origin": CAMPUS_BASE},
                )
        except ScraperHttpError as exc:
            return [], f"腾讯校招项目映射获取失败：{exc}"

        groups = payload.get("data") if payload.get("status") == 0 else None
        if not isinstance(groups, list):
            return [], "腾讯校招项目映射返回格式异常"

        ids: list[int] = []
        for group in groups:
            recruit_type = group.get("recruitType")
            for sub in group.get("subProjectList") or []:
                mapping_id = sub.get("mappingId")
                if mapping_id is None:
                    continue
                name = sub.get("projectName") or ""
                if recruit_type == 2:
                    item_scope = "intern"
                elif recruit_type == 1:
                    item_scope = "campus"
                else:
                    item_scope = "intern" if "实习" in name else "campus"
                if item_scope == scope:
                    ids.append(int(mapping_id))

        if not ids:
            return [], f"未找到 scope={scope} 对应的腾讯校招项目"
        return ids, ""

    # ------------------------------------------------------------------ detail

    def get_detail(self, url: str) -> dict[str, Any]:
        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        if "join.qq.com" in url:
            result = self._detail_campus(url)
        elif "careers.tencent.com" in url:
            result = self._detail_social(url)
        else:
            return {"error": f"非腾讯招聘 URL：{url}"}

        if result and not result.get("error"):
            cache.set(key, result)
        return result

    def _detail_social(self, url: str) -> dict[str, Any]:
        post_id = _query_value(url, "postId") or _regex(r"/position/(\d+)", url)
        if not post_id:
            return {"error": f"无法从 URL 提取 postId：{url}"}

        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "GET",
                    SOCIAL_DETAIL,
                    params={
                        "timestamp": _timestamp(),
                        "postId": post_id,
                        "language": "zh-cn",
                    },
                )
        except ScraperHttpError as exc:
            return {"error": f"腾讯社招详情请求失败：{exc}"}

        data = payload.get("Data") if payload.get("Code") == 200 else None
        if not isinstance(data, dict):
            return {"error": "腾讯社招详情返回空数据"}

        return {
            "title": data.get("RecruitPostName", ""),
            "company": "腾讯",
            "location": data.get("LocationName", ""),
            "salary": "",
            "description": data.get("Responsibility", ""),
            "requirements": data.get("Requirement", ""),
            "benefits": "",
            "department": data.get("BGName", ""),
            "category": data.get("CategoryName", ""),
            "url": data.get("PostURL") or url,
            "source": "tencent",
        }

    def _detail_campus(self, url: str) -> dict[str, Any]:
        post_id = _query_value(url, "postid") or _query_value(url, "postId")
        if not post_id:
            return {"error": f"无法从 URL 提取 postId：{url}"}

        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "GET",
                    f"{CAMPUS_API}/jobDetails/getJobDetailsByPostId",
                    params={"postId": post_id, "timestamp": _timestamp()},
                    headers={
                        "Referer": f"{CAMPUS_DETAIL_PAGE}?postid={post_id}",
                        "Origin": CAMPUS_BASE,
                    },
                )
        except ScraperHttpError as exc:
            return {"error": f"腾讯校招详情请求失败：{exc}"}

        data = payload.get("data") if payload.get("status") == 0 else None
        if not isinstance(data, dict):
            return {"error": "腾讯校招详情返回空数据"}

        cities = data.get("workCityList") or []
        location = "、".join(
            str(c.get("name") or c.get("cityName") or c) if isinstance(c, dict) else str(c)
            for c in cities
        )
        return {
            "title": data.get("title", ""),
            "company": "腾讯",
            "location": location,
            "salary": "",
            "description": _first(data, "desc", "topicDetail", "introduction"),
            "requirements": _first(data, "request", "topicRequirement"),
            "benefits": "",
            "department": data.get("projectName", ""),
            "recruit_type": data.get("recruitLabelName", ""),
            "url": f"{CAMPUS_DETAIL_PAGE}?postid={post_id}",
            "source": "tencent",
        }

    # ------------------------------------------------------------------ format

    def _format_social_post(self, post: dict[str, Any]) -> dict[str, Any]:
        url = post.get("PostURL") or ""
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        return {
            "title": post.get("RecruitPostName", ""),
            "url": url,
            "company": "腾讯",
            "location": post.get("LocationName", ""),
            "department": post.get("BGName", ""),
            "summary": _truncate(post.get("Responsibility", ""), 200),
            "post_id": str(post.get("PostId", "")),
            "category": post.get("CategoryName", ""),
            "source": "tencent",
        }

    def _format_campus_post(self, post: dict[str, Any]) -> dict[str, Any]:
        post_id = str(post.get("postId", ""))
        return {
            "title": post.get("positionTitle", ""),
            "url": f"{CAMPUS_DETAIL_PAGE}?postid={post_id}" if post_id else CAMPUS_POSTS_PAGE,
            "company": "腾讯",
            "location": (post.get("workCities") or "").strip(),
            "department": (post.get("bgs") or "").strip(),
            "summary": " / ".join(
                dict.fromkeys(
                    x for x in (post.get("projectName", ""), post.get("recruitLabelName", "")) if x
                )
            ),
            "post_id": post_id,
            "source": "tencent",
        }


# ---------------------------------------------------------------------- utils


def _timestamp() -> str:
    import time

    return str(int(time.time() * 1000))


def _query_value(url: str, key: str) -> str:
    values = parse_qs(urlparse(url).query).get(key) or []
    return values[0] if values else ""


def _regex(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _first(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
