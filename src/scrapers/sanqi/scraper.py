"""三七互娱招聘 Scraper——公开网页接口（无需登录）。

接口：
- 列表：GET https://zhaopin.37.com/index.php?m=Home&c=society&a=getIndexPage
  参数 category/key/post_type/place_type/page，返回 JSON。
- 详情：GET https://zhaopin.37.com/index.php?m=Home&c=society&a=post_info&id=<id>
  服务端渲染 HTML，详情页含职位描述与任职要求。

当前只接入社会招聘；校招页签仍指向旧的 Moka 门户，职位多为已停招状态，未接入。
不公开薪资。
"""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

BASE = "https://zhaopin.37.com"
LIST_PATH = "/index.php"
PAGE_SIZE = 8
MAX_PAGES = 20
LIST_REFERER = "https://zhaopin.37.com/index.php?m=Home&c=recruit&a=recruit&recruit=1"

class Scraper(CompanyScraper):
    """三七互娱招聘 Scraper。"""

    COMPANY_SLUG = "sanqi"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"策划\"、\"Java\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"广州\"、\"上海\"），服务端按工作地点筛选"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "zhaopin.37.com" in url

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

    def _fetch_jobs(
        self, keyword: str, city: str, limit: int
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        try:
            with make_client() as client:
                for page in range(1, MAX_PAGES + 1):
                    params = {
                        "m": "Home",
                        "c": "society",
                        "a": "getIndexPage",
                        "category": "",
                        "key": keyword,
                        "post_type": "",
                        "place_type": city,
                        "page": page,
                    }
                    payload = request_json(
                        client,
                        "GET",
                        BASE + LIST_PATH,
                        params=params,
                        headers={"Referer": LIST_REFERER, "X-Requested-With": "XMLHttpRequest"},
                    )
                    if payload.get("code") != 0:
                        message = payload.get("message") or payload.get("code")
                        return [{"error": f"三七互娱接口返回错误：{message}"}]

                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    if not rows:
                        break
                    for row in rows:
                        item = self._format_post(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected

                    page_count = int(data.get("pageCount") or 0)
                    if page_count and page >= page_count:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"三七互娱接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"三七互娱接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于三七互娱：{url}"}

        url = (url or "").strip()
        if not url:
            return {"error": "三七互娱详情 URL 为空"}
        if not url.startswith("http"):
            url = BASE + ("/" + url.lstrip("/"))

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                response = client.get(url, headers={"Referer": LIST_REFERER})
                if response.status_code >= 400:
                    raise ScraperHttpError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                body = response.text
        except ScraperHttpError as exc:
            return {"error": f"三七互娱详情请求失败：{exc}"}
        except Exception as exc:  # noqa: BLE001 — 网络错误要可诊断
            return {"error": f"三七互娱详情请求失败：{exc}"}

        title = _first(body, r'<div class="post-title">(.*?)</div>')
        location = _first(body, r"<div><span>工作地点：\s*</span>(.*?)</div>")
        description = _first(
            body,
            r"职位描述：\s*</div>\s*<div class=\"wordBorder\">\s*<pre[^>]*>(.*?)</pre>",
        )
        requirements = _first(
            body,
            r"任职要求：\s*</div>\s*<div class=\"d_top\">\s*<pre[^>]*>(.*?)</pre>",
        )

        title = re.sub(r"^【[^】]*】\s*", "", _clean(title))
        location = _clean(location)
        description = _clean(description)
        requirements = _clean(requirements)

        if not title and not description and not requirements:
            return {
                "error": "三七互娱详情解析失败：页面结构可能已变化",
                "url": url,
            }

        result = {
            "title": title,
            "company": "三七互娱",
            "location": location,
            "salary": "",
            "description": description,
            "requirements": requirements,
            "url": url,
            "source": "sanqi",
        }
        cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        raw_url = str(row.get("url") or "")
        job_id = _extract_id(raw_url)
        return {
            "title": _clean(str(row.get("name") or "")),
            "url": raw_url if raw_url.startswith("http") else BASE + raw_url,
            "company": "三七互娱",
            "location": _clean(str(row.get("work_place") or "")),
            "department": _clean(str(row.get("pname") or "")),
            "summary": _truncate(_clean(str(row.get("duty") or "")), 800),
            "job_id": job_id,
            "job_type": _clean(str(row.get("cate_name") or "")),
            "source": "sanqi",
        }


def _first(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "", re.S)
    return match.group(1) if match else ""


def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\r\n?", "\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _extract_id(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return (query.get("id") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
