"""哔哩哔哩招聘 Scraper——浏览器 XHR（接口带 csrf / lunar-id 头）。

接口：
- 页面：https://jobs.bilibili.com/social/positions
- 列表：POST https://jobs.bilibili.com/api/srs/position/positionList
- 详情：列表响应已包含岗位描述；get_detail 使用搜索时缓存的列表快照。

接口请求头由页面 JS 生成，这里用 Playwright 打开页面并拦截列表响应；
搜索关键词通过页面搜索框触发。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper

SEARCH_URL = "https://jobs.bilibili.com/social/positions"
DETAIL = "https://jobs.bilibili.com/social/positions/{id}"
PAGE_SIZE = 10
MAX_PAGES = 3
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """哔哩哔哩社会招聘 Scraper。"""

    COMPANY_SLUG = "bilibili"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"算法\"）"},
        "city": {"required": False, "description": "城市名（如 \"上海\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 10，最大 30（每页 10 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "jobs.bilibili.com" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 10), 30))

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
            return [{"error": "B站源需要 Playwright：pip install playwright && playwright install chromium"}]

        payloads: list[dict[str, Any]] = []

        def _on_response(response: Any) -> None:
            if "/api/srs/position/positionList" not in response.url:
                return
            try:
                data = response.json()
            except Exception:
                return
            if isinstance(data, dict):
                payloads.append(data)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(user_agent=UA, locale="zh-CN")
                page = context.new_page()
                page.on("response", _on_response)
                try:
                    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(12000)

                    if keyword:
                        search_input = page.locator("input[placeholder='搜索职位']").first
                        if search_input.count() == 0:
                            return [{"error": "B站页面未找到搜索框，页面结构可能已变化"}]
                        search_input.fill(keyword)
                        search_input.press("Enter")
                        page.wait_for_timeout(8000)

                    if not payloads:
                        return [{"error": "B站接口未返回数据，页面结构或请求头逻辑可能已变化"}]

                    collected = self._parse_payload(payloads[-1], city, limit)
                    seen = len(payloads)
                    page_no = 1
                    while len(collected) < limit and page_no < MAX_PAGES:
                        if not _click_next(page):
                            break
                        page.wait_for_timeout(5000)
                        if len(payloads) <= seen:
                            break
                        seen = len(payloads)
                        collected.extend(self._parse_payload(payloads[-1], city, limit - len(collected)))
                        page_no += 1

                    if not collected:
                        return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
                    return collected[:limit]
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 — 浏览器失败要可诊断
            return [{"error": f"B站浏览器抓取失败：{exc}"}]

    def _parse_payload(self, payload: dict[str, Any], city: str, limit: int) -> list[dict[str, Any]]:
        data = payload.get("data") or {}
        rows = data.get("list") or []
        collected: list[dict[str, Any]] = []
        for row in rows:
            item = self._format_post(row)
            if city and city not in item.get("location", ""):
                continue
            collected.append(item)
            _remember(item)
            if len(collected) >= limit:
                break
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取岗位 id：{url}"}

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
        return {
            "title": row.get("positionName", ""),
            "url": DETAIL.format(id=job_id),
            "company": "哔哩哔哩",
            "location": row.get("workLocation", ""),
            "department": row.get("postCodeName", ""),
            "summary": _truncate(str(row.get("positionDescription") or ""), 800),
            "job_id": job_id,
            "job_type": row.get("positionTypeName", ""),
            "publish_time": row.get("pushTime", ""),
            "source": "bilibili",
        }


def _click_next(page: Any) -> bool:
    selectors = (
        ".ant-pagination-next:not(.ant-pagination-disabled)",
        "li[title='下一页']:not(.ant-pagination-disabled)",
    )
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        button = locator.first
        try:
            if button.is_enabled():
                button.click()
                return True
        except Exception:
            continue
    return False


def _remember(item: dict[str, Any]) -> None:
    if len(_FALLBACK) > 500:
        _FALLBACK.clear()
    _FALLBACK[item["job_id"]] = {
        "title": item.get("title", ""),
        "company": "哔哩哔哩",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "bilibili",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[-1].isdigit():
        return parts[-1]
    query = parse_qs(parsed.query)
    return (query.get("id") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
