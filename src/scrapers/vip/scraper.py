"""唯品会社会招聘 Scraper。

唯品会使用 Moka 的独立租户域名 ``app-tc.mokahr.com``：
- 列表接口返回明文 ``data.jobs``，但字段很少（title/id/deptId）；
- 详情接口为 Moka AES 加密响应，包含地点与完整 JD。

因此不复用 ``MokaScraper`` 的列表实现，只复用其详情解密和文本清洗工具；
搜索时按需补抓详情，保证返回符合框架规范的字段。
"""

from __future__ import annotations

import re
from typing import Any

from .._platforms.moka import (
    MokaScraper,
    _decrypt_payload,
    _extract_job_id,
    _html_to_text,
    _locations,
)
from ..http_utils import ScraperHttpError, make_client, request_json

_REQUIREMENT_RE = re.compile(r"(?:任职资格|任职要求|岗位要求|职位要求|任职条件)\s*[:：]?\s*")


class Scraper(MokaScraper):
    """唯品会社会招聘。"""

    COMPANY_SLUG = "vip"
    COMPANY_NAME = "唯品会"
    PAGE_URL = "https://app-tc.mokahr.com/social-recruitment/vipshophr/10038"
    ORG_ID = "vipshophr"
    SITE_ID = 10038
    MODULE_ID = "5397619910"

    API_BASE = "https://app-tc.mokahr.com"
    PAGE_SIZE = 50
    MAX_PAGES = 10

    def _fetch_jobs(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        offset = 0
        page_size = min(self.PAGE_SIZE, max(limit, 10))
        try:
            with make_client() as client:
                iv = self._fetch_aes_iv(client)
                for _ in range(self.MAX_PAGES):
                    if len(collected) >= limit:
                        break
                    body = {
                        "keyword": keyword,
                        "limit": page_size,
                        "offset": offset,
                        "departmentIds": [],
                        "siteId": self.SITE_ID,
                        "orgId": self.ORG_ID,
                        "needGroupType": "list",
                        "moduleId": self.MODULE_ID,
                        "jobEnableFields": ["location"],
                        "enableBrandIcon": False,
                        "websitePageId": None,
                        "locale": "zh-CN",
                    }
                    payload = request_json(
                        client,
                        "POST",
                        f"{self.API_BASE}/api/outer/ats-apply/website/jobs/module",
                        json_body=body,
                        headers={"Referer": self.PAGE_URL},
                    )
                    data = payload.get("data") or {}
                    rows = data.get("jobs") or []
                    if not rows:
                        break

                    for row in rows:
                        item = self._detail_for(client, iv, str(row.get("id") or ""))
                        if item.get("error"):
                            item = self._format_list_row(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            break

                    total = int((data.get("jobStats") or {}).get("total") or 0)
                    offset += len(rows)
                    if total and offset >= total:
                        break
                    if len(rows) < page_size:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"{self.COMPANY_NAME}接口请求失败：{exc}"}]
        except (TypeError, ValueError, KeyError) as exc:
            return [{"error": f"{self.COMPANY_NAME}接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        job_id = _extract_job_id(url)
        if not job_id:
            return {"error": f"无法从 URL 提取 jobId：{url}"}

        cache = self._make_cache("detail")
        key = self._cache_key(url=url)
        cached = cache.get(key)
        if cached is not None:
            return cached

        try:
            with make_client() as client:
                iv = self._fetch_aes_iv(client)
                result = self._detail_for(client, iv, job_id)
        except ScraperHttpError as exc:
            return {"error": f"{self.COMPANY_NAME}详情请求失败：{exc}", "url": url}
        except (TypeError, ValueError, KeyError) as exc:
            return {"error": f"{self.COMPANY_NAME}详情返回格式异常：{exc}", "url": url}

        if not result.get("error"):
            result["url"] = url
            cache.set(key, result)
        return result

    def _detail_for(self, client: Any, iv: bytes, job_id: str) -> dict[str, Any]:
        url = self._job_url(job_id)
        cache = self._make_cache("detail")
        cached = cache.get(url)
        if cached is not None:
            return cached

        payload = request_json(
            client,
            "POST",
            f"{self.API_BASE}/api/outer/ats-apply/website/job",
            json_body={
                "orgId": self.ORG_ID,
                "jobId": job_id,
                "siteId": self.SITE_ID,
                "locale": "zh-CN",
            },
            headers={"Referer": self.PAGE_URL},
        )
        data = _decrypt_payload(payload, iv).get("data") or {}
        result = self._format_detail(data, url)
        if not result.get("error"):
            cache.set(url, result)
        return result

    def _format_detail(self, data: dict[str, Any], url: str) -> dict[str, Any]:
        description, requirements = _split_description(
            _html_to_text(str(data.get("jobDescription") or ""))
        )
        return {
            "title": data.get("title", ""),
            "company": self.COMPANY_NAME,
            "location": _locations(data.get("locations")),
            "department": str(data.get("department") or ""),
            "salary": str(data.get("salary") or ""),
            "description": description,
            "requirements": requirements,
            "job_type": str(data.get("commitment") or ""),
            "job_id": str(data.get("id") or ""),
            "url": url,
            "source": self.COMPANY_SLUG,
        }

    def _format_list_row(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id") or "")
        return {
            "title": row.get("title", ""),
            "company": self.COMPANY_NAME,
            "location": "",
            "department": "",
            "summary": "",
            "job_id": job_id,
            "url": self._job_url(job_id),
            "source": self.COMPANY_SLUG,
        }

    def _job_url(self, job_id: str) -> str:
        return f"{self.PAGE_URL}#/job/{job_id}"


def _split_description(text: str) -> tuple[str, str]:
    match = _REQUIREMENT_RE.search(text)
    if not match:
        return text.strip(), ""
    return text[: match.start()].strip(), text[match.end() :].strip()
