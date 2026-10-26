"""GitHub 秋招/面经经验帖 Scraper——Search API 抓 offer 成功经验与面试复盘。

数据类型：成功经验/面经（experiences），写入 data/knowledge/experiences/github/

搜索策略：
- GitHub Search API (issues)：https://api.github.com/search/issues?q={query}&type=issue
- 标题里搜「秋招 OR 春招 OR 面经 OR offer」，按 issue 创建时间倒序
- 支持公司名/学历档位关键词拼接（双非/985/211 等），聚合层再按岗位职责二次打分
- 返回标题/URL/创建时间/摘要给 LLM，学历标签同时打标（src.education）

限流说明：未认证搜索 10 次/分钟；如设置了 GITHUB_TOKEN 环境变量则携带认证
（30 次/分钟）。HTTP 客户端的 User-Agent 已在 http_utils 统一。
"""

from __future__ import annotations

import os
from typing import Any

from ...education import normalize_education_tag
from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

SEARCH_URL = "https://api.github.com/search/issues"

# 意图词：将「经验帖」与闲聊 repo issue 区分开。
# 注意：GitHub Search API 限制最多 5 个 AND/OR/NOT 运算符——
# 全量拼接（6 个意图词 + keyword + education + company）必炸 422，
# 因此只取前 3 个意图词，education/company 二选一补充时最多 6 段 = 5 个 OR。
_INTENT_WORDS = ("秋招", "春招", "面经")


class Scraper(CompanyScraper):
    """GitHub 经验帖 Scraper。

    search: Search API 拉经验帖列表（无需登录/无 WAF）
    get_detail: issue 详情（body 全文）
    缓存: 搜索 1 小时，详情 24 小时
    知识库写入: experiences/github/*.json（泛型 JSON 存储）
    """

    COMPANY_SLUG = "github"
    DATA_TYPE = "experiences"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": True, "description": "搜索关键词（如 \"AI Agent\"、\"后端\"）+ 自动拼秋招/面经/offer 意图词"},
        "education": {"required": False, "description": "学历档位词（如 \"双非\"、\"985硕\"），拼进搜索与打标"},
        "filter_company": {"required": False, "description": "公司名（如 \"字节\"），拼接到搜索词"},
        "order": {"required": False, "description": "排序：created=最新(默认), best=综合相关"},
        "page": {"required": False, "description": "页码，默认 1"},
        "limit": {"required": False, "description": "返回数量上限，默认 20"},
    }

    search_cache_ttl = 3600
    detail_cache_ttl = 86400

    def __init__(self, cookie: str = ""):
        self._token = os.environ.get("GITHUB_TOKEN", "")

    def supports_url(self, url: str) -> bool:
        return "github.com" in url and "/issues/" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        """搜索 GitHub 秋招/面经经验帖。

        Args:
            keyword: 岗位/方向关键词（必填）
            education: 学历档位词（可选，如 "双非"）
            filter_company: 公司名（可选）
            order: created=最新 / best=综合
            page / limit: 分页
        """
        keyword = str(kwargs.get("keyword") or "").strip()
        education = str(kwargs.get("education") or "").strip()
        company = str(kwargs.get("filter_company") or "").strip()
        order = kwargs.get("order") or "created"
        page = int(kwargs.get("page") or 1)
        limit = min(int(kwargs.get("limit") or 20), 30)
        if not keyword:
            return [{"error": "搜索关键词不能为空"}]

        query_parts = [keyword]
        query_parts.extend(_INTENT_WORDS)
        if education and (education not in keyword):
            query_parts.append(education)
        elif company and (company not in keyword):
            query_parts.append(f'"{company}"')
        query = " OR ".join(query_parts)
        q = f"{query} type:issue"

        search_cache = self._make_cache("search")
        key = self._cache_key(q=q, order=order, page=page)
        cached = search_cache.get(key)
        if cached is not None:
            return cached[:limit]

        # 完整查询失败（尤其 422 布尔运算符超限）时，降级为单一关键词重搜
        try:
            raw = self._search_api(q=q, order=order if order != "best" else "", page=page)
        except ScraperHttpError as e:
            if "422" not in str(e):
                return [{"error": str(e)}]
            try:
                raw = self._search_api(
                    q=f"{keyword} type:issue", order=order if order != "best" else "", page=page
                )
            except ScraperHttpError as e2:
                return [{
                    "error": (
                        f"完整查询与降级查询均失败（query={q}）：{e}；"
                        f"降级（仅 keyword）仍失败：{e2}"
                    ),
                    "query": q,
                }]

        items = raw.get("items") or []
        if not items:
            return [{"error": "未找到相关经验帖", "query": q}]

        formatted = []
        for it in items[:limit]:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            body = (it.get("body") or "").strip()
            edu = normalize_education_tag(f"{title} {body[:800]}")
            formatted.append({
                "title": title[:200],
                "url": it.get("html_url", ""),
                "snippet": body[:300].replace("\n", " "),
                "date": (it.get("created_at") or "")[:10],
                "company": "",
                "position": "",
                "education_tag": edu["tag"],
                "year_tag": edu["year"],
                "reactions": (it.get("reactions") or {}).get("total_count", 0),
                "repository": (it.get("repository_url") or "").rsplit("/", 1)[-1],
                "source": "github",
            })

        results = formatted or [{"error": "GitHub 返回的数据为空", "query": q}]
        if not results[0].get("error"):
            search_cache.set(key, results)
        return results[:limit]

    def get_detail(self, url: str) -> dict[str, Any]:
        """获取 issue 详情全文。"""
        if not self.supports_url(url):
            return {"error": f"非 GitHub issue URL: {url}"}

        detail_cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = detail_cache.get(key)
        if cached is not None:
            return cached

        try:
            raw = self._request(url)
        except ScraperHttpError as e:
            return {"error": str(e)}

        title = (raw.get("title") or "").strip()
        content = (raw.get("body") or "").strip()
        if not content and not title:
            return {"error": "issue 内容为空", "url": url}

        edu = normalize_education_tag(f"{title} {content[:1500]}")
        result = {
            "title": title or "无标题",
            "company": "",
            "position": "",
            "content": content,
            "education_tag": edu["tag"],
            "year_tag": edu["year"],
            "date": (raw.get("created_at") or "")[:10],
            "source": "github",
            "url": url,
        }
        detail_cache.set(key, result)
        return result

    # === API 层 ===

    def _search_api(self, q: str, order: str, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {"q": q, "type": "issue", "per_page": 30}
        if page > 1:
            params["page"] = page
        if order:
            params["sort"] = order
            params["order"] = "desc"
        return self._request(SEARCH_URL, params=params)

    def _request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with make_client(timeout=20) as client:
            headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            try:
                return request_json(client, "GET", url, params=params, headers=headers)
            except ScraperHttpError as e:
                msg = str(e)
                if "403" in msg and "rate limit" in msg.lower():
                    raise ScraperHttpError(
                        "GitHub 搜索限流（未认证 10 次/分钟）——设置 GITHUB_TOKEN 环境变量可达 30 次/分钟"
                    ) from e
                if "422" in msg:
                    raise ScraperHttpError(f"搜索词过于复杂，换更简短的 keyword 重试：{msg}") from e
                raise
