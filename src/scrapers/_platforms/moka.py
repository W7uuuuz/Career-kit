"""Moka 招聘门户通用适配。

Moka 公开接口返回 AES-CBC 加密数据：
- 页面 HTML 中的 ``window.TurboApply.data.aesIv`` 是 IV
- 响应体 ``necromancer`` 是密钥，``data`` 是 Base64 密文
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from ..base import CompanyScraper
from ..http_utils import ScraperHttpError, make_client, request_json

_AES_IV_RE = re.compile(r"aesIv(?:&quot;|\\\"|)\s*:\s*(?:&quot;|\\\"|)\s*([0-9a-f]{16})")
_REQUIREMENT_RE = re.compile(r"(?:二、|三、|四、|五、)?(?:任职要求|岗位要求|职位要求)")


class MokaScraper(CompanyScraper):
    """Moka 社招门户的通用实现。"""

    COMPANY_NAME = ""
    PAGE_URL = ""
    ORG_ID = ""
    SITE_ID = 0
    MODULE_ID = ""

    PARAMS: dict[str, dict[str, Any]] = {
        "keyword": {"required": False, "description": "搜索关键词（如 \"硬件\"、\"算法\"），服务端过滤"},
        "city": {"required": False, "description": "城市名（如 \"合肥\"），对工作地点做本地过滤"},
        "limit": {"required": False, "description": "返回数量上限，默认 20，最大 100"},
    }

    def supports_url(self, url: str) -> bool:
        if not super().supports_url(url):
            return False
        return self.ORG_ID in url and str(self.SITE_ID) in url

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
        try:
            with make_client() as client:
                iv = self._fetch_aes_iv(client)
                while len(collected) < limit:
                    page_size = min(100, limit - len(collected))
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
                        "https://app.mokahr.com/api/outer/ats-apply/website/jobs/module",
                        json_body=body,
                        headers={"Referer": self.PAGE_URL},
                    )
                    data = _decrypt_payload(payload, iv)
                    jobs = (data.get("data") or {}).get("jobs") or []
                    if not jobs:
                        break

                    for row in jobs:
                        item = self._format_job(row)
                        if city and city not in item.get("location", ""):
                            continue
                        collected.append(item)
                        if len(collected) >= limit:
                            return collected

                    offset += len(jobs)
                    if len(jobs) < page_size:
                        break
        except ScraperHttpError as exc:
            return [{"error": f"{self.COMPANY_NAME}接口请求失败：{exc}"}]
        except (TypeError, ValueError, KeyError) as exc:
            return [{"error": f"{self.COMPANY_NAME}接口返回格式异常：{exc}"}]

        if not collected:
            return [{"error": "未找到相关岗位", "keyword": keyword, "city": city}]
        return collected

    def _format_job(self, row: dict[str, Any]) -> dict[str, Any]:
        job_id = str(row.get("id", ""))
        return {
            "title": row.get("title", ""),
            "url": f"{self.PAGE_URL}#/job/{job_id}",
            "company": self.COMPANY_NAME,
            "location": _locations(row.get("locations")),
            "department": "",
            "summary": "",
            "job_id": job_id,
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

        try:
            with make_client() as client:
                iv = self._fetch_aes_iv(client)
                payload = request_json(
                    client,
                    "POST",
                    "https://app.mokahr.com/api/outer/ats-apply/website/job",
                    json_body={
                        "orgId": self.ORG_ID,
                        "jobId": job_id,
                        "siteId": self.SITE_ID,
                        "locale": "zh-CN",
                    },
                    headers={"Referer": self.PAGE_URL},
                )
        except ScraperHttpError as exc:
            return {"error": f"{self.COMPANY_NAME}详情请求失败：{exc}"}
        except (TypeError, ValueError, KeyError) as exc:
            return {"error": f"{self.COMPANY_NAME}详情返回格式异常：{exc}"}

        try:
            data = _decrypt_payload(payload, iv).get("data") or {}
        except (TypeError, ValueError, KeyError) as exc:
            return {"error": f"{self.COMPANY_NAME}详情解密失败：{exc}"}
        description, requirements = _split_description(
            _html_to_text(str(data.get("jobDescription") or ""))
        )
        result = {
            "title": data.get("title", ""),
            "company": self.COMPANY_NAME,
            "location": _locations(data.get("locations")),
            "department": "",
            "salary": "",
            "description": description,
            "requirements": requirements,
            "job_type": data.get("commitment", ""),
            "url": url,
            "source": self.COMPANY_SLUG,
        }
        if not result.get("error"):
            cache.set(key, result)
        return result

    def _fetch_aes_iv(self, client: Any) -> bytes:
        response = client.get(self.PAGE_URL, headers={"Referer": self.PAGE_URL})
        if response.status_code >= 400:
            raise ScraperHttpError(f"HTTP {response.status_code}: 页面加载失败")
        match = _AES_IV_RE.search(response.text)
        if not match:
            raise ScraperHttpError("未找到 Moka aesIv，页面结构可能已变化")
        return match.group(1).encode()


def _decrypt_payload(payload: dict[str, Any], iv: bytes) -> dict[str, Any]:
    key = str(payload.get("necromancer") or "").encode()
    raw = base64.b64decode(payload.get("data") or "")
    if not key:
        raise ValueError("响应缺少 necromancer")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return json.loads(plain.decode("utf-8"))


def _locations(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    names = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("cityName") or item.get("provinceName") or ""
        if name:
            names.append(str(name))
    return "/".join(names)


def _extract_job_id(url: str) -> str:
    match = re.search(r"#/job/([^/?#]+)", url)
    if match:
        return match.group(1)
    query = parse_qs(urlparse(url).query)
    return (query.get("jobId") or [""])[0]


def _html_to_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_description(text: str) -> tuple[str, str]:
    match = _REQUIREMENT_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.end() :].strip()
