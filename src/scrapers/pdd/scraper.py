"""拼多多招聘 Scraper——浏览器 XHR（接口需要 anti_content 风控参数）。

接口：
- 页面：https://careers.pddglobalhr.com/jobs
- 列表：POST /api/recruit/position/list
- 详情：POST /api/recruit/position/detail

接口需要页面 JS 生成的 anti_content，因此使用 Playwright 打开页面并拦截响应。
需要先执行 `playwright install chromium`。
"""

from __future__ import annotations

import contextlib
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper

JOBS_URL = "https://careers.pddglobalhr.com/jobs"
DETAIL_URL = "https://careers.pddglobalhr.com/jobs/detail?code={code}"
DETAIL_LINK = "https://careers.pddglobalhr.com/jobs/detail?code={code}"
PAGE_SIZE = 10
MAX_PAGES = 3
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class Scraper(CompanyScraper):
    """拼多多社会招聘 Scraper。"""

    COMPANY_SLUG = "pdd"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"算法\"）"},
        "city": {"required": False, "description": "城市名（如 \"上海\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 10，最大 30（每页 10 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "careers.pddglobalhr.com" in url or "careers.pinduoduo.com" in url

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
            return [{"error": "拼多多源需要 Playwright：pip install playwright && playwright install chromium"}]

        payloads: list[dict[str, Any]] = []

        def _on_response(response: Any) -> None:
            if "/api/recruit/position/list" not in response.url:
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
                    page.goto(JOBS_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(12000)

                    if keyword:
                        with contextlib.suppress(Exception):
                            page.wait_for_selector("input[placeholder='搜索职位名称']", timeout=15000)
                        search_input = page.locator("input[placeholder='搜索职位名称']").first
                        if search_input.count() == 0:
                            search_input = page.locator("input[placeholder='请输入关键词查询职位']").first
                        if search_input.count() == 0:
                            return [{"error": "拼多多页面未找到搜索框，页面结构可能已变化"}]
                        search_input.fill(keyword)
                        search_input.press("Enter")
                        page.wait_for_timeout(10000)

                    if not payloads:
                        return [{"error": "拼多多接口未返回数据，页面结构或风控逻辑可能已变化"}]

                    collected = self._parse_payload(payloads[-1], city, limit)
                    seen = len(payloads)
                    page_no = 1
                    while len(collected) < limit and page_no < MAX_PAGES:
                        if not _click_next(page):
                            break
                        page.wait_for_timeout(4000)
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
            return [{"error": f"拼多多浏览器抓取失败：{exc}"}]

    def _parse_payload(self, payload: dict[str, Any], city: str, limit: int) -> list[dict[str, Any]]:
        result = payload.get("result") or {}
        rows = result.get("list") or []
        collected: list[dict[str, Any]] = []
        for row in rows:
            item = self._format_post(row)
            if city and city not in item.get("location", ""):
                continue
            collected.append(item)
            if len(collected) >= limit:
                break
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        code = _extract_code(url)
        if not code:
            return {"error": f"无法从 URL 提取岗位 code：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(code, url)
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_detail(self, code: str, url: str) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"error": "拼多多源需要 Playwright：pip install playwright && playwright install chromium"}

        payloads: list[dict[str, Any]] = []

        def _on_response(response: Any) -> None:
            if "/api/recruit/position/detail" not in response.url:
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
                    page.goto(DETAIL_URL.format(code=code), wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(12000)
                    if not payloads:
                        return {"error": "拼多多详情接口未返回数据，页面结构或风控逻辑可能已变化"}
                    data = payloads[-1].get("result") or {}
                    return self._format_detail(data, url)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"拼多多详情抓取失败：{exc}"}

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        code = str(row.get("code", ""))
        return {
            "title": row.get("name", ""),
            "url": DETAIL_LINK.format(code=code),
            "company": "拼多多",
            "location": row.get("workLocation", ""),
            "department": row.get("job", ""),
            "summary": row.get("job", ""),
            "job_id": code,
            "publish_time": row.get("updateTime", ""),
            "source": "pdd",
        }

    def _format_detail(self, row: dict[str, Any], url: str) -> dict[str, Any]:
        code = str(row.get("code", ""))
        return {
            "title": row.get("name", ""),
            "company": "拼多多",
            "location": row.get("workLocation", ""),
            "salary": "",
            "description": _html_to_text(row.get("jobDuty")),
            "requirements": _html_to_text(row.get("serveRequirement")),
            "benefits": _html_to_text(row.get("bonus")),
            "department": row.get("recruitType", ""),
            "job_id": code,
            "publish_time": row.get("updateTime", ""),
            "url": url or DETAIL_LINK.format(code=code),
            "source": "pdd",
        }


def _click_next(page: Any) -> bool:
    selectors = (
        ".rocket-pagination-next:not(.rocket-pagination-disabled)",
        "li[title='下一页']:not(.rocket-pagination-disabled)",
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


def _html_to_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>\s*<p[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _extract_code(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return (query.get("code") or [""])[0]
