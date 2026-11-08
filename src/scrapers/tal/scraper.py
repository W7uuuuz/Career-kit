"""好未来招聘 Scraper——公开 JSON 接口（无需登录）。

接口：
- 列表：POST https://job-api.100tal.com/sapi/activities/c/jobs/list
  请求体含 orgId=tal、route_code=kg8Meh、site=campus、keyword、limit、offset。
- 详情：POST https://job-api.100tal.com/sapi/activities/c/jobs/detail
  请求体含 orgId=tal、jobId；返回 HTML 描述的职位全文。
- 详情页：https://job.tal.com/campus/positions/<job_id>

列表响应已包含 HTML 描述；详情接口单独返回同一份全文。不公开薪资。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

API_BASE = "https://job-api.100tal.com/sapi/activities/c"
LIST_API = API_BASE + "/jobs/list"
DETAIL_API = API_BASE + "/jobs/detail"
DETAIL_PAGE = "https://job.tal.com/campus/positions/{job_id}"
ORG_ID = "tal"
ROUTE_CODE = "kg8Meh"
PAGE_SIZE = 20
MAX_PAGES = 10
REFERER = "https://job.tal.com/campus/positions"

_REQ_MARKERS = ("任职要求", "任职资格", "任职条件", "岗位要求", "职位要求")
_REQ_PREFIX_RE = re.compile(r"^\s*(?:[一二三四五六七八九十]+[、.．]\s*)?")


class Scraper(CompanyScraper):
    """好未来校园招聘/实习 Scraper。"""

    COMPANY_SLUG = "tal"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"AI\"、\"算法\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"北京\"），对结果做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "job.tal.com" in url or "job-api.100tal.com" in url

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

    def _fetch_jobs(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        offset = 0
        total = None
        try:
            with make_client() as client:
                headers = {"Referer": REFERER, "Origin": "https://job.tal.com"}
                for _ in range(MAX_PAGES):
                    body = {
                        "orgId": ORG_ID,
                        "route_code": ROUTE_CODE,
                        "limit": PAGE_SIZE,
                        "offset": offset,
                        "site": "campus",
                        "keyword": keyword,
                        "locations": [],
                        "commitments": [],
                        "zhinengIds": [],
                        "tag_ids": [],
                    }
                    payload = request_json(
                        client, "POST", LIST_API, json_body=body, headers=headers
                    )
                    if payload.get("code") != 200:
                        message = payload.get("msg") or payload.get("code")
                        return [{"error": f"好未来接口返回错误：{message}"}]

                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    if total is None:
                        total = int(data.get("total") or 0)
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_post(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected

                    offset += len(rows)
                    if total is not None and offset >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"好未来接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"好未来接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于好未来：{url}"}

        job_id = _extract_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取岗位 id：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                payload = request_json(
                    client,
                    "POST",
                    DETAIL_API,
                    json_body={"orgId": ORG_ID, "jobId": job_id},
                    headers={"Referer": REFERER, "Origin": "https://job.tal.com"},
                )
        except ScraperHttpError as exc:
            return {"error": f"好未来详情请求失败：{exc}"}
        except (TypeError, ValueError) as exc:
            return {"error": f"好未来详情返回格式异常：{exc}"}

        if payload.get("code") != 200:
            return {"error": f"好未来详情返回错误：{payload.get('msg') or payload.get('code')}"}

        row = payload.get("data") or {}
        text = _html_to_text(str(row.get("description") or ""))
        description, requirements = _split_requirements(text)

        result = {
            "title": str(row.get("title") or ""),
            "company": "好未来",
            "location": "/".join(str(x) for x in (row.get("Locations") or []) if x),
            "department": str(row.get("department_name") or ""),
            "salary": "",
            "description": description,
            "requirements": requirements,
            "job_id": job_id,
            "job_type": str(row.get("hire_mode") or ""),
            "commitment": str(row.get("commitment") or ""),
            "category": str((row.get("zhineng") or {}).get("name") or ""),
            "publish_time": str(row.get("created_at") or ""),
            "update_time": str(row.get("updated_at") or ""),
            "url": DETAIL_PAGE.format(job_id=job_id),
            "source": "tal",
        }
        cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("job_id") or "")
        summary = _html_to_text(str(row.get("description") or ""))
        return {
            "title": str(row.get("title") or ""),
            "url": DETAIL_PAGE.format(job_id=job_id),
            "company": "好未来",
            "location": "/".join(str(x) for x in (row.get("Locations") or []) if x),
            "department": str(row.get("department_name") or ""),
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "job_type": str(row.get("hire_mode") or ""),
            "commitment": str(row.get("commitment") or ""),
            "category": str((row.get("zhineng") or {}).get("name") or ""),
            "publish_time": str(row.get("created_at") or ""),
            "source": "tal",
        }


class _TextExtractor(HTMLParser):
    """把岗位描述 HTML 转成带换行的纯文本。"""

    _BLOCK_TAGS = {
        "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4",
        "tr", "table", "section", "article",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_to_text(raw: str) -> str:
    if not raw:
        return ""
    if "<" not in raw:
        return _normalize_text(raw)
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001 — 个别脏 HTML 不应阻断抓取
        return _normalize_text(raw)
    return _normalize_text("".join(parser.parts))


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    for line in lines:
        if not line and (not cleaned or not cleaned[-1]):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _split_requirements(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    for index, line in enumerate(lines):
        stripped = _REQ_PREFIX_RE.sub("", line).strip()
        for marker in _REQ_MARKERS:
            if stripped == marker or stripped.startswith(marker + "：") or stripped.startswith(marker + ":"):
                tail = stripped[len(marker):].lstrip("：: ")
                req_lines = ([tail] if tail else []) + lines[index + 1:]
                return "\n".join(lines[:index]).strip(), "\n".join(req_lines).strip()
    return text.strip(), ""


def _extract_id(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if re.fullmatch(r"[0-9a-zA-Z-]{16,}", url):
        return url
    parsed = urlparse(url)
    match = re.search(r"/positions/([0-9a-zA-Z-]+)", parsed.path)
    if match:
        return match.group(1)
    query = parse_qs(parsed.query)
    return (query.get("jobId") or query.get("job_id") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
