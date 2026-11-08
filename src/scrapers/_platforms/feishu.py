"""飞书招聘（Feishu SaaS ATS）门户通用适配。

适用站点：``<tenant>.jobs.feishu.cn`` 及其自定义域名（如
``career.papegames.com``）的社招门户（``portal_type=6``）。

接口：
- 搜索：``POST /api/v1/search/job/posts``
- 详情：``GET  /api/v1/job/posts/<job_id>``

两个接口的 ``_signature`` 由页面前端 acrawler SDK 生成，且与请求参数绑定，
无法在会话间复用。因此这里用 Playwright 打开门户页面，捕获页面自身发起的
官方 API 响应，不做签名逆向。列表响应已包含 ``description`` / ``requirement``，
无需登录，门户不公开薪资。浏览器优先使用系统默认 Chrome / Edge，未检测到时
回退 Playwright Chromium。
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from ..base import CompanyScraper
from ..browser import launch_browser

_SEARCH_API = "/api/v1/search/job/posts"
_JOB_ID_RE = re.compile(r"/position/([0-9A-Za-z]+)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BROWSER_HINT = (
    "浏览器优先使用系统默认 Chrome / Edge；未检测到时执行 "
    "playwright install chromium 使用内置 Chromium"
)


class FeishuScraper(CompanyScraper):
    """飞书招聘社招门户的通用实现。"""

    COMPANY_NAME = ""
    PORTAL_URL = ""
    PORTAL_HOST = ""
    PORTAL_TYPE = 6
    DETAIL_URL_TEMPLATE = ""

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100
    MAX_PAGES = 5
    RESPONSE_TIMEOUT_MS = 20000
    PAGE_LOAD_TIMEOUT_MS = 60000

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"算法\"、\"客户端\"），服务端过滤"},
        "city": {"required": False, "description": "城市名（如 \"上海\"、\"北京\"），对工作地点做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        if super().supports_url(url):
            return True
        hostname = urlparse(url).hostname or ""
        return bool(self.PORTAL_HOST) and (
            hostname == self.PORTAL_HOST or hostname.endswith(f".{self.PORTAL_HOST}")
        )

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or self.DEFAULT_LIMIT), self.MAX_LIMIT))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._search_via_browser(keyword, city, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _search_via_browser(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return [{"error": f"{self.COMPANY_NAME}源需要 Playwright：pip install playwright"}]

        collected: list[dict[str, Any]] = []
        try:
            with sync_playwright() as p:
                try:
                    browser = launch_browser(p, headless=True)
                except Exception as exc:
                    return [{"error": f"{self.COMPANY_NAME}浏览器启动失败：{exc}（{_BROWSER_HINT}）"}]

                try:
                    context = browser.new_context(locale="zh-CN")
                    page = context.new_page()
                    page_no = 1
                    while page_no <= self.MAX_PAGES and len(collected) < limit:
                        payloads: list[dict[str, Any]] = []

                        def _on_response(response: Any, bucket: list[dict[str, Any]] = payloads) -> None:
                            if _SEARCH_API not in response.url or response.status != 200:
                                return
                            try:
                                body = response.json()
                            except Exception:
                                return
                            if isinstance(body, dict):
                                bucket.append(body)

                        page.on("response", _on_response)
                        try:
                            page.goto(
                                self._search_url(keyword, page_no, limit),
                                wait_until="domcontentloaded",
                                timeout=self.PAGE_LOAD_TIMEOUT_MS,
                            )
                        except Exception as exc:
                            page.remove_listener("response", _on_response)
                            return [{"error": f"{self.COMPANY_NAME}门户加载失败：{exc}"}]

                        payload = _wait_payload(page, payloads, self.RESPONSE_TIMEOUT_MS)
                        page.remove_listener("response", _on_response)
                        if payload is None:
                            if not collected:
                                return [{"error": f"{self.COMPANY_NAME}未捕获到搜索接口响应，门户结构或签名机制可能已变化"}]
                            break

                        if payload.get("code") not in (0, None):
                            return [{"error": f"{self.COMPANY_NAME}搜索接口返回错误：{payload.get('message') or payload.get('code')}"}]

                        data = payload.get("data") or {}
                        rows = data.get("job_post_list") or []
                        if not rows:
                            break

                        for row in rows:
                            item = self._format_job(row)
                            if city and city not in item.get("location", ""):
                                continue
                            collected.append(item)
                            if len(collected) >= limit:
                                break

                        total = int(data.get("count") or 0)
                        if total and (page_no - 1) * limit + len(rows) >= total:
                            break
                        if len(rows) < limit:
                            break
                        page_no += 1
                finally:
                    browser.close()
        except Exception as exc:
            return [{"error": f"{self.COMPANY_NAME}浏览器抓取失败：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected[:limit]

    def _search_url(self, keyword: str, page_no: int, limit: int) -> str:
        separator = "&" if "?" in self.PORTAL_URL else "?"
        query = urlencode({"keywords": keyword, "current": page_no, "limit": limit})
        return f"{self.PORTAL_URL}{separator}{query}"

    def _detail_url(self, job_id: str) -> str:
        if self.DETAIL_URL_TEMPLATE:
            return self.DETAIL_URL_TEMPLATE.format(job_id=job_id)
        return f"{self.PORTAL_URL.rstrip('/')}/position/{job_id}/detail"

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id") or "")
        description = _clean_text(row.get("description"))
        requirement = _clean_text(row.get("requirement"))
        return {
            "title": row.get("title", ""),
            "url": self._detail_url(job_id),
            "company": self.COMPANY_NAME,
            "location": _locations(row.get("city_list")),
            "department": _category_name(row.get("job_category")),
            "summary": _truncate(description or requirement, 300),
            "description": description,
            "requirements": requirement,
            "job_id": job_id,
            "job_type": _category_name(row.get("recruit_type")),
            "publish_date": _format_date(row.get("publish_time")),
            "source": self.COMPANY_SLUG,
        }

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_job_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jobId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        result = self._fetch_detail(job_id, url)
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_detail(self, job_id: str, url: str) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"error": f"{self.COMPANY_NAME}源需要 Playwright：pip install playwright"}

        payloads: list[dict[str, Any]] = []
        try:
            with sync_playwright() as p:
                try:
                    browser = launch_browser(p, headless=True)
                except Exception as exc:
                    return {"error": f"{self.COMPANY_NAME}浏览器启动失败：{exc}（{_BROWSER_HINT}）"}

                try:
                    context = browser.new_context(locale="zh-CN")
                    page = context.new_page()

                    def _on_response(response: Any) -> None:
                        if f"/api/v1/job/posts/{job_id}" not in response.url:
                            return
                        if response.status != 200:
                            return
                        try:
                            body = response.json()
                        except Exception:
                            return
                        if isinstance(body, dict):
                            payloads.append(body)

                    page.on("response", _on_response)
                    try:
                        page.goto(
                            self._detail_url(job_id),
                            wait_until="domcontentloaded",
                            timeout=self.PAGE_LOAD_TIMEOUT_MS,
                        )
                    except Exception as exc:
                        return {"error": f"{self.COMPANY_NAME}详情页加载失败：{exc}", "url": url}

                    payload = _wait_payload(page, payloads, self.RESPONSE_TIMEOUT_MS)
                    if payload is None:
                        return {"error": f"{self.COMPANY_NAME}未捕获到详情接口响应，门户结构可能已变化", "url": url}
                finally:
                    browser.close()
        except Exception as exc:
            return {"error": f"{self.COMPANY_NAME}详情抓取失败：{exc}", "url": url}

        if payload.get("code") not in (0, None):
            return {"error": f"{self.COMPANY_NAME}详情接口返回错误：{payload.get('message') or payload.get('code')}", "url": url}

        data = (payload.get("data") or {}).get("job_post_detail") or {}
        if not isinstance(data, dict) or not data:
            return {"error": f"{self.COMPANY_NAME}详情接口未返回岗位数据", "url": url}

        return self._format_detail(data, url)

    def _format_detail(self, data: dict[str, Any], url: str) -> dict[str, Any]:
        info = data.get("job_post_info") or {}
        salary = ""
        if isinstance(info, dict) and (info.get("min_salary") or info.get("max_salary")):
            salary = f"{info.get('min_salary') or ''}-{info.get('max_salary') or ''}".strip("-")
        return {
            "title": data.get("title", ""),
            "company": self.COMPANY_NAME,
            "location": _locations(data.get("city_list")),
            "department": _category_name(data.get("job_category")),
            "salary": salary,
            "description": _clean_text(data.get("description")),
            "requirements": _clean_text(data.get("requirement")),
            "job_type": _category_name(data.get("recruit_type")),
            "publish_date": _format_date(data.get("publish_time")),
            "job_id": str(data.get("id") or ""),
            "url": url,
            "source": self.COMPANY_SLUG,
        }


def _wait_payload(page: Any, payloads: list[dict[str, Any]], timeout_ms: int) -> dict[str, Any] | None:
    waited = 0
    while waited < timeout_ms and not payloads:
        page.wait_for_timeout(500)
        waited += 500
    return payloads[-1] if payloads else None


def _extract_job_id(url: str) -> str:
    match = _JOB_ID_RE.search(url)
    if match:
        return match.group(1)
    query = parse_qs(urlparse(url).query)
    for name in ("job_id", "jobId", "positionId"):
        value = (query.get(name) or [""])[0]
        if value:
            return value
    return ""


def _locations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names = [str(item["name"]) for item in value if isinstance(item, dict) and item.get("name")]
    return "/".join(names)


def _category_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("name") or value.get("i18n_name") or "")


def _format_date(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def _clean_text(value: Any) -> str:
    text = _HTML_TAG_RE.sub("", str(value or ""))
    text = html_lib.unescape(text).replace("\r", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str, max_len: int) -> str:
    text = " ".join((text or "").split())
    return text[:max_len] + "..." if len(text) > max_len else text
