"""蚂蚁集团社会招聘 Scraper——浏览器 XHR（页面接口带 bigfish ctoken）。

接口：
- 页面：https://talent.antgroup.com/off-campus-position
- 列表：POST https://hrcareersweb.antgroup.com/api/social/position/search?ctoken=...
- 详情：列表响应已包含岗位职责与要求；get_detail 使用搜索时缓存的列表快照。

页面由支付宝小程序容器渲染，ctoken 在页面 cookie 中；这里用 Playwright
打开页面，再在页面上下文内调用接口。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper

SEARCH_URL = "https://talent.antgroup.com/off-campus-position"
API = "https://hrcareersweb.antgroup.com/api/social/position/search"
DETAIL = "https://talent.antgroup.com/off-campus-position?positionId={id}"
PAGE_SIZE = 20
MAX_PAGES = 5
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """蚂蚁集团社会招聘 Scraper。"""

    COMPANY_SLUG = "ant"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"算法\"）"},
        "city": {"required": False, "description": "城市名（如 \"杭州\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "talent.antgroup.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._search_via_playwright(keyword, city, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _search_via_playwright(
        self, keyword: str, city: str, limit: int
    ) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return [{"error": "蚂蚁源需要 Playwright：pip install playwright && playwright install chromium"}]

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(user_agent=UA, locale="zh-CN")
                page = context.new_page()
                try:
                    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(12000)
                    ctoken = _find_cookie(context.cookies(), "ctoken")
                    if not ctoken:
                        return [{"error": "蚂蚁页面未拿到 ctoken，页面结构可能已变化"}]

                    collected: list[dict[str, Any]] = []
                    for page_no in range(1, MAX_PAGES + 1):
                        payload = page.evaluate(
                            """async ({api, ctoken, body}) => {
                                const resp = await fetch(`${api}?ctoken=${encodeURIComponent(ctoken)}`, {
                                    method: 'POST',
                                    credentials: 'include',
                                    headers: {'content-type': 'application/json'},
                                    body: JSON.stringify(body),
                                });
                                return await resp.json();
                            }""",
                            {
                                "api": API,
                                "ctoken": ctoken,
                                "body": {
                                    "channel": "group_official_site",
                                    "language": "zh",
                                    "key": keyword,
                                    "regions": "",
                                    "categories": "",
                                    "subCategories": "",
                                    "bgCode": "",
                                    "socialQrCode": "",
                                    "pageIndex": page_no,
                                    "pageSize": PAGE_SIZE,
                                },
                            },
                        )
                        if payload.get("success") is False:
                            return [{"error": f"蚂蚁接口返回错误：{payload.get('errorMsg') or payload.get('errorCode')}"}]
                        rows = payload.get("content") or []
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
                        total = int(payload.get("totalCount") or 0)
                        if total and page_no * PAGE_SIZE >= total:
                            break

                    if not collected:
                        return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
                    return collected[:limit]
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 — 浏览器失败要可诊断
            return [{"error": f"蚂蚁浏览器抓取失败：{exc}"}]

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 positionId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        fallback = _FALLBACK.get(job_id)
        if fallback:
            result = dict(fallback)
            result["url"] = url
            result["_note"] = "详情页为前端渲染，内容来自搜索列表快照"
        else:
            result = {
                "error": "未找到该岗位的列表快照，请先调用 search 获取岗位",
                "url": url,
            }

        if not result.get("error"):
            cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id", ""))
        summary = "\n".join(
            part
            for part in (
                str(row.get("description") or ""),
                str(row.get("requirement") or ""),
            )
            if part
        )
        return {
            "title": row.get("name", ""),
            "url": DETAIL.format(id=job_id),
            "company": "蚂蚁集团",
            "location": "/".join(str(x) for x in (row.get("workLocations") or []) if x),
            "department": "/".join(str(x) for x in (row.get("categories") or []) if x),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "publish_time": row.get("publishTime", ""),
            "source": "ant",
        }


def _find_cookie(cookies: list[dict[str, Any]], name: str) -> str:
    for cookie in cookies:
        if cookie.get("name") == name:
            return str(cookie.get("value") or "")
    return ""


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "蚂蚁集团",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "ant",
    }


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("positionId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
