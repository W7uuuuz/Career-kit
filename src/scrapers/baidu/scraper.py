"""百度招聘 Scraper——公开 JSON 接口（表单编码）。

参考实现：
- https://github.com/Enzoding/JobHunt-CLI （recruitType / 分页约束）
- https://github.com/HA7CH/job-pro （同一接口的字段映射）

接口：
- 列表：POST https://talent.baidu.com/httservice/getPostListNew
- 详情：GET  https://talent.baidu.com/httservice/getPostDetail

列表响应已包含 workContent / serviceCondition，详情接口失败时可回退列表数据。
pageSize 服务端硬上限 20。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API_ROOT = "https://talent.baidu.com"
LIST_API = f"{API_ROOT}/httservice/getPostListNew"
DETAIL_API = f"{API_ROOT}/httservice/getPostDetail"
LIST_PAGE = f"{API_ROOT}/jobs/list"

SCOPE_TO_TYPE = {
    "social": "SOCIAL",
    "campus": "GRADUATE",
    "intern": "INTERN",
}

_TYPE_TO_SCOPE = {v: k for k, v in SCOPE_TO_TYPE.items()}
MAX_PAGE_SIZE = 20

# 列表页已带完整 JD；详情接口偶发「发布中」，用列表数据兜底
_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """百度招聘 Scraper。"""

    COMPANY_SLUG = "baidu"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"算法\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "scope": {"required": False, "description": "招聘类型：social=社招(默认), campus=校招, intern=实习"},
        "limit": {"required": False, "description": "返回数量上限，默认 20"},
    }

    def supports_url(self, url: str) -> bool:
        return "talent.baidu.com" in url

    # ------------------------------------------------------------------ search

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        scope = (kwargs.get("scope") or "social").strip().lower()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        recruit_type = SCOPE_TO_TYPE.get(scope)
        if recruit_type is None:
            return [{"error": f"scope 必须是 social/campus/intern，收到：{scope}"}]

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, scope=scope, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._search_pages(keyword, city, recruit_type, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _search_pages(
        self, keyword: str, city: str, recruit_type: str, limit: int
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page = 1
        max_pages = 10 if city else 1

        try:
            with make_client() as client:
                while len(collected) < limit and page <= max_pages:
                    form = {
                        "recruitType": recruit_type,
                        "keyWord": keyword,
                        "curPage": page,
                        "pageSize": MAX_PAGE_SIZE,
                    }
                    payload = request_json(
                        client,
                        "POST",
                        LIST_API,
                        data=form,
                        headers={"Referer": LIST_PAGE},
                    )
                    if payload.get("status") != "ok":
                        return [{"error": f"百度接口返回错误：{payload.get('message')}"}]

                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_post(row, recruit_type)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        _remember(item)
                        if len(collected) >= limit:
                            break

                    if not data.get("hasNextPage"):
                        break
                    page += 1
        except ScraperHttpError as exc:
            return [{"error": f"百度接口请求失败：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    # ------------------------------------------------------------------ detail

    def get_detail(self, url: str) -> dict[str, Any]:
        post_id, recruit_type = self._parse_url(url)
        if not post_id:
            return {"error": f"无法从 URL 提取 postId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(post_id, recruit_type, url)
        if result.get("error"):
            fallback = _FALLBACK.get(post_id)
            if fallback:
                result = dict(fallback)
                result["url"] = url
                result["_note"] = "详情接口暂不可用，内容来自列表快照"
        if result and not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_detail(
        self, post_id: str, recruit_type: str, url: str
    ) -> dict[str, Any]:
        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "GET",
                    DETAIL_API,
                    params={"postId": post_id, "recruitType": recruit_type},
                    headers={"Referer": f"{API_ROOT}/jobs/detail/{recruit_type}/{post_id}"},
                )
        except ScraperHttpError as exc:
            return {"error": f"百度详情请求失败：{exc}"}

        if payload.get("status") != "ok":
            return {"error": f"百度详情返回错误：{payload.get('message')}"}
        data = payload.get("data") or {}
        if not data:
            return {"error": "百度详情返回空数据"}
        return self._format_detail(data, recruit_type, url)

    # ------------------------------------------------------------------ format

    def _format_post(self, row: dict[str, Any], recruit_type: str) -> dict[str, Any]:
        post_id = str(row.get("postId", ""))
        return {
            "title": row.get("name", ""),
            "url": f"{API_ROOT}/jobs/detail/{recruit_type}/{post_id}",
            "company": "百度",
            "location": row.get("workPlace", ""),
            "department": row.get("bgShortName", ""),
            "summary": _truncate(row.get("workContent", ""), 500),
            "post_id": post_id,
            "post_type": row.get("postType", ""),
            "source": "baidu",
        }

    def _format_detail(
        self, row: dict[str, Any], recruit_type: str, url: str
    ) -> dict[str, Any]:
        post_id = str(row.get("postId", ""))
        return {
            "title": row.get("name", ""),
            "company": "百度",
            "location": row.get("workPlace", ""),
            "salary": "",
            "description": row.get("workContent", ""),
            "requirements": row.get("serviceCondition", ""),
            "benefits": "",
            "department": row.get("bgShortName", ""),
            "post_type": row.get("postType", ""),
            "recruit_type": _TYPE_TO_SCOPE.get(recruit_type, recruit_type),
            "url": url or f"{API_ROOT}/jobs/detail/{recruit_type}/{post_id}",
            "source": "baidu",
        }

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str]:
        """支持 /jobs/detail/<recruitType>/<postId> 与 ?postId=...&recruitType=...。"""
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if "detail" in parts:
            idx = parts.index("detail")
            tail = parts[idx + 1:]
            if len(tail) >= 2:
                return tail[1], tail[0]
            if len(tail) == 1:
                return tail[0], "SOCIAL"
        query = parse_qs(parsed.query)
        post_id = (query.get("postId") or [""])[0]
        recruit_type = (query.get("recruitType") or ["SOCIAL"])[0]
        return post_id, recruit_type


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["post_id"]] = {
        "title": item.get("title", ""),
        "company": "百度",
        "location": item.get("location", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "department": item.get("department", ""),
        "source": "baidu",
    }


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
