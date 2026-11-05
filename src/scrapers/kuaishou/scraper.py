"""快手招聘 Scraper——浏览器 XHR（接口需要前端签名）。

接口：
- 页面：https://zhaopin.kuaishou.cn/recruit/e/#/official/social/
- 列表：GET /recruit/e/api/v1/open/positions/simple（需 sign / signtimestamp）
- 详情：列表响应已包含岗位描述与要求；get_detail 使用搜索时缓存的列表快照。

由于接口签名由页面 JS 生成，这里用 Playwright 打开页面并拦截列表响应；
搜索关键词通过页面搜索框触发。需要先执行 `playwright install chromium`。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper

SEARCH_URL = "https://zhaopin.kuaishou.cn/recruit/e/#/official/social/"
DETAIL = "https://zhaopin.kuaishou.cn/recruit/e/#/official/social/?positionId={id}"
PAGE_SIZE = 10
MAX_PAGES = 3

_CITY_CODES = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "天津": "Tianjin",
    "杭州": "Hangzhou",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "烟台": "Yantai",
    "西安": "Xian",
    "无锡": "Wuxi",
    "淮安": "Huaian",
    "铜仁": "Tongren",
    "吉首": "Jishou",
    "香港": "HongKong",
    "澄迈": "Chengmai",
}
_CITY_NAMES = {v: k for k, v in _CITY_CODES.items()}

_FALLBACK: dict[str, dict[str, Any]] = {}


class Scraper(CompanyScraper):
    """快手社会招聘 Scraper。"""

    COMPANY_SLUG = "kuaishou"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"Java\"、\"算法\"）"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 10，最大 30（每页 10 条）"},
    }

    def supports_url(self, url: str) -> bool:
        return "zhaopin.kuaishou.cn" in url

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
            return [{"error": "快手源需要 Playwright：pip install playwright && playwright install chromium"}]

        payloads: list[dict[str, Any]] = []

        def _on_response(response: Any) -> None:
            if "/api/v1/open/positions/simple" not in response.url:
                return
            try:
                data = response.json()
            except Exception:
                return
            if isinstance(data, dict):
                data["_url"] = response.url
                payloads.append(data)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.on("response", _on_response)
                try:
                    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(8000)

                    if keyword:
                        search_input = page.locator("input[placeholder='搜索职位']").first
                        if search_input.count() == 0:
                            return [{"error": "快手页面未找到搜索框，页面结构可能已变化"}]
                        search_input.fill(keyword)
                        search_input.press("Enter")
                        page.wait_for_timeout(6000)

                    if not payloads:
                        return [{"error": "快手接口未返回数据，页面结构或签名逻辑可能已变化"}]

                    chosen = payloads[-1]
                    if keyword:
                        for payload in reversed(payloads):
                            if "name=" in payload.get("_url", ""):
                                chosen = payload
                                break

                    collected = self._parse_payload(chosen, keyword, city, limit)
                    seen = len(payloads)
                    page_no = 1
                    while len(collected) < limit and page_no < MAX_PAGES:
                        if not _click_next(page):
                            break
                        page.wait_for_timeout(4000)
                        if len(payloads) <= seen:
                            break
                        seen = len(payloads)
                        collected.extend(
                            self._parse_payload(payloads[-1], keyword, city, limit - len(collected))
                        )
                        page_no += 1

                    if not collected:
                        return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
                    return collected[:limit]
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 — 浏览器失败要可诊断
            return [{"error": f"快手浏览器抓取失败：{exc}"}]

    def _parse_payload(
        self, payload: dict[str, Any], keyword: str, city: str, limit: int
    ) -> list[dict[str, Any]]:
        result = payload.get("result") or {}
        rows = result.get("list") or []
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
            result["_note"] = "详情为列表内展开，内容来自搜索列表快照"
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
        codes = row.get("workLocationsCode") or []
        code = str(codes[0]) if codes else str(row.get("workLocationCode") or "")
        location = _CITY_NAMES.get(code, code)
        summary = "\n".join(
            part
            for part in (
                str(row.get("description") or ""),
                str(row.get("positionDemand") or ""),
            )
            if part
        )
        return {
            "title": row.get("name", ""),
            "url": DETAIL.format(id=job_id),
            "company": "快手",
            "location": location,
            "department": row.get("departmentName") or "",
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "job_type": row.get("positionCategoryCode", ""),
            "experience": row.get("workExperienceCode", ""),
            "source": "kuaishou",
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
        "company": "快手",
        "location": item.get("location", ""),
        "department": item.get("department", ""),
        "salary": "",
        "description": item.get("summary", ""),
        "requirements": "",
        "source": "kuaishou",
    }


def _extract_id(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if not query and parsed.fragment and "?" in parsed.fragment:
        query = parse_qs(parsed.fragment.split("?", 1)[1])
    return (query.get("positionId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
