"""旷视科技社会招聘 Scraper——Moka 公开接口（无需登录）。

站点 ``https://www.megvii.com/join_us`` 的「社会招聘」实际跳转到 Moka 独立 ATS：
``https://app.mokahr.com/social-recruitment/megviihr/38641``。

接口（AES-CBC 加密，IV 取自门户页 ``aesIv``）：
- 列表：POST https://app.mokahr.com/api/outer/ats-apply/website/jobs/module
- 详情：POST https://app.mokahr.com/api/outer/ats-apply/website/job

该租户列表接口只返回 id/title，工作地点、部门与描述需逐条取详情补齐。
"""

from __future__ import annotations

from typing import Any

from .._platforms.moka import (
    MokaScraper,
    _decrypt_payload,
    _extract_job_id,
    _html_to_text,
    _split_description,
)
from ..http_utils import ScraperHttpError, make_client, request_json

DETAIL_API = "https://app.mokahr.com/api/outer/ats-apply/website/job"
LIST_API = "https://app.mokahr.com/api/outer/ats-apply/website/jobs/module"
PAGE_SIZE = 50
MAX_PAGES = 5
MAX_SCAN = 150


class Scraper(MokaScraper):
    """旷视科技社会招聘 Scraper。"""

    COMPANY_SLUG = "megvii"
    COMPANY_NAME = "旷视科技"
    PAGE_URL = "https://app.mokahr.com/social-recruitment/megviihr/38641"
    ORG_ID = "megviihr"
    SITE_ID = 38641
    MODULE_ID = "7777704419"

    def supports_url(self, url: str) -> bool:
        return "megviihr" in url

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        keyword = (kwargs.get("keyword") or "").strip()
        city = (kwargs.get("city") or "").strip()
        limit = max(1, min(int(kwargs.get("limit") or 20), 100))

        cache = self._make_cache("search")
        key = self._cache_key(keyword=keyword, city=city, limit=limit)
        cached = cache.get(key)
        if cached is not None:
            return cached[:limit]

        results = self._fetch_jobs_enriched(keyword, city, limit)
        if results and not (len(results) == 1 and results[0].get("error")):
            cache.set(key, results)
        return results[:limit]

    def _fetch_jobs_enriched(self, keyword: str, city: str, limit: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        scanned = 0
        try:
            with make_client() as client:
                iv = self._fetch_aes_iv(client)
                for page_no in range(MAX_PAGES):
                    offset = page_no * PAGE_SIZE
                    body = {
                        "keyword": keyword,
                        "limit": PAGE_SIZE,
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
                        LIST_API,
                        json_body=body,
                        headers={"Referer": self.PAGE_URL},
                    )
                    data = _decrypt_payload(payload, iv)
                    rows = (data.get("data") or {}).get("jobs") or []
                    if not rows:
                        break

                    for row in rows:
                        scanned += 1
                        job_id = str(row.get("id", ""))
                        if not job_id:
                            continue
                        url = f"{self.PAGE_URL}#/job/{job_id}"
                        detail = self.get_detail(url)
                        item = self._format_enriched(row, url, detail)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected
                        if scanned >= MAX_SCAN:
                            break

                    if scanned >= MAX_SCAN or len(rows) < PAGE_SIZE:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"旷视科技接口请求失败：{exc}"}]
        except (TypeError, ValueError, KeyError) as exc:
            return [{"error": f"旷视科技接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def get_detail(self, url: str) -> dict[str, Any]:
        if not self.supports_url(url):
            return {"error": f"URL 不属于旷视科技：{url}"}

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
                payload = request_json(
                    client,
                    "POST",
                    DETAIL_API,
                    json_body={
                        "orgId": self.ORG_ID,
                        "jobId": job_id,
                        "siteId": self.SITE_ID,
                        "locale": "zh-CN",
                    },
                    headers={"Referer": self.PAGE_URL},
                )
        except ScraperHttpError as exc:
            return {"error": f"旷视科技详情请求失败：{exc}"}
        except (TypeError, ValueError, KeyError) as exc:
            return {"error": f"旷视科技详情返回格式异常：{exc}"}

        try:
            data = _decrypt_payload(payload, iv).get("data") or {}
        except (TypeError, ValueError, KeyError) as exc:
            return {"error": f"旷视科技详情解密失败：{exc}"}
        if not data:
            return {"error": "旷视科技详情为空，请先调用 search 获取岗位", "url": url}

        description, requirements = _split_description(
            _html_to_text(str(data.get("jobDescription") or ""))
        )
        result = {
            "title": data.get("title", ""),
            "company": self.COMPANY_NAME,
            "location": _location(data),
            "department": _department(data),
            "salary": str(data.get("salaryText") or ""),
            "description": description,
            "requirements": requirements,
            "job_type": str(data.get("commitment") or ""),
            "publish_time": data.get("publishedAt", ""),
            "url": url,
            "source": self.COMPANY_SLUG,
        }
        cache.set(key, result)
        return result

    def _format_enriched(self, row: dict[str, Any], url: str, detail: dict[str, Any]) -> dict[str, Any]:
        if detail.get("error"):
            return {
                "title": row.get("title", ""),
                "url": url,
                "company": self.COMPANY_NAME,
                "location": "",
                "department": "",
                "summary": "",
                "job_id": str(row.get("id", "")),
                "source": self.COMPANY_SLUG,
            }
        return {
            "title": detail.get("title") or row.get("title", ""),
            "url": url,
            "company": self.COMPANY_NAME,
            "location": detail.get("location", ""),
            "department": detail.get("department", ""),
            "summary": _truncate(detail.get("description", ""), 800),
            "job_id": str(row.get("id", "")),
            "job_type": detail.get("job_type", ""),
            "source": self.COMPANY_SLUG,
        }


def _location(data: dict[str, Any]) -> str:
    names: list[str] = []
    for loc in data.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        city = str(loc.get("cityName") or "").strip()
        province = str(loc.get("provinceName") or "").strip()
        if province and city and province != city and province not in city:
            label = f"{province}{city}"
        else:
            label = city or province
        if label and label not in names:
            names.append(label)
    return "/".join(names)


def _department(data: dict[str, Any]) -> str:
    names: list[str] = []
    for item in [data.get("department")] + list(data.get("departments") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return "/".join(names)


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
