"""米哈游招聘 Scraper——公开 ATS JSON 接口（无需登录）。

接口：
- 列表：POST https://ats.openout.mihoyo.com/ats-portal/v1/job/list
  请求体含 competencyTypes、pageNo、pageSize、jobName、addressIds、channelDetailIds、hireType。
- 详情：POST https://ats.openout.mihoyo.com/ats-portal/v1/job/info
  请求体含 id、channelDetailIds、hireType；返回职位描述与任职要求。
- 城市枚举：POST https://ats.openout.mihoyo.com/ats-portal/v2/common/enum_tree/get

当前接入社会招聘（hireType=0）。不公开薪资。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

ATS_BASE = "https://ats.openout.mihoyo.com/ats-portal"
LIST_API = ATS_BASE + "/v1/job/list"
INFO_API = ATS_BASE + "/v1/job/info"
ENUM_TREE_API = ATS_BASE + "/v2/common/enum_tree/get"
DETAIL_PAGE = "https://jobs.mihoyo.com/position#/position/{job_id}"
REFERER = "https://jobs.mihoyo.com/"
COMPETENCY_TYPES = ["1", "2", "3", "4", "5", "6", "7", "8"]
PAGE_SIZE = 50
MAX_PAGES = 10


class Scraper(CompanyScraper):
    """米哈游社会招聘 Scraper。"""

    COMPANY_SLUG = "mihoyo"

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "岗位名称关键词（如 \"原画\"、\"后端\"）；为空时拉取全量"},
        "city": {"required": False, "description": "城市名（如 \"上海\"、\"北京\"），优先服务端按地点筛选"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        return "jobs.mihoyo.com" in url or "ats.openout.mihoyo.com" in url

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
        total: int | None = None
        try:
            with make_client() as client:
                headers = {"Referer": REFERER, "Origin": "https://jobs.mihoyo.com"}
                address_ids = _resolve_address_ids(client, city, headers) if city else []

                for page in range(1, MAX_PAGES + 1):
                    body: dict[str, Any] = {
                        "competencyTypes": COMPETENCY_TYPES,
                        "pageNo": page,
                        "pageSize": PAGE_SIZE,
                        "channelDetailIds": [1],
                        "hireType": 0,
                    }
                    if keyword:
                        body["jobName"] = keyword
                    if address_ids:
                        body["addressIds"] = address_ids

                    payload = request_json(
                        client, "POST", LIST_API, json_body=body, headers=headers
                    )
                    if payload.get("code") != 0:
                        message = payload.get("message") or payload.get("code")
                        return [{"error": f"米哈游接口返回错误：{message}"}]

                    data = payload.get("data") or {}
                    rows = data.get("list") or []
                    if total is None:
                        total = int(data.get("total") or 0)
                    if not rows:
                        break

                    for row in rows:
                        item = self._format_post(row)
                        if city and not address_ids and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected

                    if total is not None and page * PAGE_SIZE >= total:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"米哈游接口请求失败：{exc}"}]
        except (TypeError, ValueError) as exc:
            return [{"error": f"米哈游接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于米哈游：{url}"}

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
                    INFO_API,
                    json_body={"id": job_id, "channelDetailIds": [1], "hireType": 0},
                    headers={"Referer": REFERER, "Origin": "https://jobs.mihoyo.com"},
                )
        except ScraperHttpError as exc:
            return {"error": f"米哈游详情请求失败：{exc}"}
        except (TypeError, ValueError) as exc:
            return {"error": f"米哈游详情返回格式异常：{exc}"}

        if payload.get("code") != 0:
            return {"error": f"米哈游详情返回错误：{payload.get('message') or payload.get('code')}"}

        row = payload.get("data") or {}
        description = str(row.get("description") or "").strip()
        requirements = str(row.get("jobRequire") or "").strip()
        addition = str(row.get("addition") or "").strip()
        if addition:
            description = (description + "\n\n附加信息\n" + addition).strip()

        result = {
            "title": str(row.get("title") or ""),
            "company": "米哈游",
            "location": _locations(row.get("addressDetailList")),
            "department": str(row.get("competencyType") or ""),
            "salary": "",
            "description": description,
            "requirements": requirements,
            "job_id": job_id,
            "job_type": str(row.get("jobNature") or ""),
            "job_nature_id": row.get("jobNatureId"),
            "project": str(row.get("projectName") or ""),
            "hire_type": str(row.get("hireTypeName") or ""),
            "tags": [str(x) for x in (row.get("tagList") or [])],
            "url": DETAIL_PAGE.format(job_id=job_id),
            "source": "mihoyo",
        }
        cache.set(key, result)
        return result

    def _format_post(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id") or "")
        location = _locations(row.get("addressDetailList"))
        department = str(row.get("competencyType") or "")
        project = str(row.get("projectName") or "")
        tags = [str(x) for x in (row.get("tagList") or [])]
        summary_parts = [
            str(row.get("jobSummary") or "").strip(),
            " / ".join(tags),
            " | ".join(part for part in (department, row.get("jobNature"), project) if part),
        ]
        summary = "\n".join(part for part in summary_parts if part)
        return {
            "title": str(row.get("title") or ""),
            "url": DETAIL_PAGE.format(job_id=job_id),
            "company": "米哈游",
            "location": location,
            "department": department,
            "summary": _truncate(summary, 800),
            "job_id": job_id,
            "job_type": str(row.get("jobNature") or ""),
            "project": project,
            "tags": tags,
            "source": "mihoyo",
        }


def _locations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return "/".join(
        str(item.get("addressDetail") or "")
        for item in value
        if isinstance(item, dict) and item.get("addressDetail")
    )


def _resolve_address_ids(client: Any, city: str, headers: dict[str, str]) -> list[str]:
    """把城市名解析成 ATS 的地址 id；解析失败时返回空列表，由本地过滤兜底。"""
    try:
        payload = request_json(
            client,
            "POST",
            ENUM_TREE_API,
            json_body={
                "key": "JobAddressEnum",
                "channelDetailIds": [1],
                "hireType": 0,
            },
            headers=headers,
        )
    except Exception:  # noqa: BLE001 — 城市枚举失败不应阻断搜索
        return []
    if payload.get("code") != 0:
        return []

    target = city.strip()
    target_short = target[:-1] if target.endswith("市") else target
    matches: list[str] = []
    for node in payload.get("data") or []:
        _collect_address(node, target, target_short, matches)
    return matches[:1]


def _collect_address(node: Any, target: str, target_short: str, matches: list[str]) -> None:
    if not isinstance(node, dict):
        return
    label = str(node.get("label") or "")
    value = str(node.get("value") or "")
    short = label[:-1] if label.endswith("市") else label
    if value and (label == target or short == target_short) and value not in matches:
        matches.append(value)
    for child in node.get("children") or []:
        _collect_address(child, target, target_short, matches)


def _extract_id(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.isdigit():
        return url

    parsed = urlparse(url)
    if parsed.fragment:
        fragment_path = parsed.fragment.split("?")[0]
        parts = [p for p in fragment_path.split("/") if p]
        if parts and parts[-1].isdigit():
            return parts[-1]

    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        if part.isdigit():
            return part

    query = parse_qs(parsed.query)
    return (query.get("id") or query.get("jobId") or [""])[0]


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
