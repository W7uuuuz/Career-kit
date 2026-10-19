"""阿里校招/实习 Scraper——campus-talent.alibaba.com。

参考实现：
- https://github.com/HA7CH/job-pro （CSRF、batch 发现、搜索/详情字段）
- https://github.com/Enzoding/JobHunt-CLI （阿里系站点矩阵）

范围：仅校招（graduate）与实习（internship）。阿里社招在另一套站点，暂不覆盖。
接口需要 XSRF-TOKEN：先 GET 校招页面拿 cookie，再带 X-XSRF-TOKEN 头 POST。
"""

from __future__ import annotations

from typing import Any

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API_ROOT = "https://campus-talent.alibaba.com"
CAMPUS_PAGE = f"{API_ROOT}/campus/position"
DEFAULT_CHANNEL = "new_campus_group_official_site"
SOURCE = "campus-talent.alibaba.com"

_BATCH_CACHE: list[dict[str, Any]] | None = None


class Scraper(CompanyScraper):
    """阿里校招/实习 Scraper。"""

    COMPANY_SLUG = "alibaba"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"后端\"）"},
        "city": {"required": False, "description": "城市名（如 \"杭州\"、\"北京\"）"},
        "scope": {"required": False, "description": "招聘类型：campus=校招(默认), intern=实习, all=全部"},
        "category": {"required": False, "description": "职位类别代码（可选，原样传给阿里 subCategories）"},
        "limit": {"required": False, "description": "返回数量上限，默认 20"},
    }

    def supports_url(self, url: str) -> bool:
        return "campus-talent.alibaba.com" in url

    # ------------------------------------------------------------------ search

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        scope = (kwargs.get("scope") or "campus").strip().lower()
        category = (kwargs.get("category") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        if scope not in ("campus", "intern", "all"):
            return [{"error": f"scope 必须是 campus/intern/all，收到：{scope}"}]

        cache = self._make_cache("search")
        key = self._cache_key(
            keyword=keyword, city=city, scope=scope, category=category, limit=limit
        )
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        try:
            results = self._search_with_client(keyword, city, scope, category, limit)
        except ScraperHttpError as exc:
            return [{"error": f"阿里接口请求失败：{exc}"}]
        except RuntimeError as exc:
            return [{"error": str(exc)}]

        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _search_with_client(
        self, keyword: str, city: str, scope: str, category: str, limit: int
    ) -> list[dict[str, Any]]:
        with make_client() as client:
            token = _acquire_token(client)
            batches = _list_batches(client, token)
            targets = _select_batches(batches, scope)
            if not targets:
                return [{"error": f"未找到 scope={scope} 对应的在招批次"}]

            body_base: dict[str, Any] = {
                "pageIndex": 1,
                "pageSize": min(limit, 100),
                "channel": DEFAULT_CHANNEL,
                "language": "zh",
            }
            if keyword:
                body_base["searchKey"] = keyword
            if city:
                body_base["regions"] = city
            if category:
                body_base["subCategories"] = category

            collected: list[dict[str, Any]] = []
            seen: set[str] = set()
            for batch in targets:
                if len(collected) >= limit:
                    break
                body = dict(body_base)
                body["batchId"] = batch["batchId"]
                body["pageSize"] = min(limit - len(collected), 100)
                payload = request_json(
                    client,
                    "POST",
                    f"{API_ROOT}/position/search",
                    json_body=body,
                    headers=_post_headers(token),
                )
                data = _data(payload)
                if not isinstance(data, dict):
                    continue
                for row in data.get("datas") or []:
                    item = self._format_post(row, batch)
                    if item["post_id"] in seen:
                        continue
                    seen.add(item["post_id"])
                    collected.append(item)
                    if len(collected) >= limit:
                        break

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    # ------------------------------------------------------------------ detail

    def get_detail(self, url: str) -> dict[str, Any]:
        post_id = _extract_id(url)
        if not post_id:
            return {"error": f"无法从 URL 提取岗位 ID：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                token = _acquire_token(client)
                payload = request_json(
                    client,
                    "POST",
                    f"{API_ROOT}/position/detail",
                    json_body={"id": _to_number(post_id)},
                    headers=_post_headers(token),
                )
        except ScraperHttpError as exc:
            return {"error": f"阿里详情请求失败：{exc}"}
        except RuntimeError as exc:
            return {"error": str(exc)}

        data = _data(payload)
        if not isinstance(data, dict):
            return {"error": "阿里详情返回空数据"}

        result = {
            "title": data.get("name", ""),
            "company": "阿里巴巴",
            "location": " / ".join(data.get("workLocations") or []),
            "salary": "",
            "description": (data.get("description") or "").strip(),
            "requirements": (data.get("requirement") or "").strip(),
            "benefits": "",
            "department": (data.get("circleNames") or [""])[0] if data.get("circleNames") else "",
            "category": data.get("categoryName", ""),
            "batch": data.get("batchName", ""),
            "url": url,
            "source": "alibaba",
        }
        if not result["description"] and not result["requirements"]:
            return {"error": "阿里详情缺少正文", "url": url}
        cache.set(key, result)
        return result

    # ------------------------------------------------------------------ format

    def _format_post(self, row: dict[str, Any], batch: dict[str, Any]) -> dict[str, Any]:
        post_id = str(row.get("id", ""))
        circles = row.get("circleNames") or []
        return {
            "title": row.get("name", ""),
            "url": f"{API_ROOT}/campus/positionDetail?positionId={post_id}",
            "company": "阿里巴巴",
            "location": " / ".join(row.get("workLocations") or []),
            "department": circles[0] if circles else "",
            "summary": " / ".join(
                x for x in (row.get("categoryName", ""), batch.get("batchName", "")) if x
            ),
            "post_id": post_id,
            "category": row.get("categoryName", ""),
            "recruit_type": row.get("categoryType", ""),
            "source": "alibaba",
        }


# ---------------------------------------------------------------------- helpers


def _acquire_token(client) -> str:
    """GET 校招页拿 XSRF-TOKEN；失败时给出可诊断错误。"""
    response = client.get(CAMPUS_PAGE, headers={"Referer": CAMPUS_PAGE})
    if response.status_code >= 400:
        raise RuntimeError(f"阿里校招页不可用：HTTP {response.status_code}")
    token = client.cookies.get("XSRF-TOKEN")
    if not token:
        raise RuntimeError("阿里接口未返回 XSRF-TOKEN（可能需要稍后重试或网络不可达）")
    return token


def _list_batches(client, token: str) -> list[dict[str, Any]]:
    global _BATCH_CACHE
    if _BATCH_CACHE is not None:
        return _BATCH_CACHE

    payload = request_json(
        client,
        "POST",
        f"{API_ROOT}/searchCondition/listBatch",
        json_body={"channel": DEFAULT_CHANNEL, "language": "zh"},
        headers=_post_headers(token),
    )
    data = _data(payload)
    if not isinstance(data, dict):
        raise RuntimeError("阿里批次列表返回格式异常")

    batches: list[dict[str, Any]] = []
    seen: set[int] = set()
    for section in ("graduate", "internship", "topTalentPlan"):
        for row in data.get(section) or []:
            batch_id = row.get("id")
            if not isinstance(batch_id, int) or batch_id in seen:
                continue
            seen.add(batch_id)
            batches.append(
                {
                    "batchId": batch_id,
                    "batchName": row.get("name", ""),
                    "category": section,
                    "recruitType": row.get("type", ""),
                }
            )
    if not batches:
        raise RuntimeError("阿里没有返回任何在招批次")
    _BATCH_CACHE = batches
    return batches


def _select_batches(batches: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    if scope == "all":
        return batches
    section = "graduate" if scope == "campus" else "internship"
    return [b for b in batches if b["category"] == section]


def _post_headers(token: str) -> dict[str, str]:
    return {
        "Referer": CAMPUS_PAGE,
        "X-XSRF-TOKEN": token,
        "Content-Type": "application/json",
    }


def _data(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False:
        return None
    code = payload.get("code")
    if code not in (None, 0, 200):
        return None
    if payload.get("data") is not None:
        return payload.get("data")
    return payload.get("content")


def _extract_id(url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(url).query)
    value = (query.get("positionId") or query.get("id") or [""])[0]
    if value:
        return value
    tail = [p for p in urlparse(url).path.split("/") if p]
    return tail[-1] if tail else ""


def _to_number(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value
