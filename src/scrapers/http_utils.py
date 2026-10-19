"""企业 scraper 共用 HTTP 层。

统一 UA / 超时 / JSON 解析 / 简单重试，便于测试 monkeypatch 单一入口。
不引入新依赖，复用 httpx。
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ScraperHttpError(Exception):
    """抓取层错误——调用方负责转成用户可读提示。"""


def make_client(timeout: float = 20.0) -> httpx.Client:
    """创建带默认配置的客户端。"""
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_UA},
    )


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int = 1,
) -> Any:
    """发送请求并解析 JSON；失败抛出 ScraperHttpError。"""
    last_error: Exception | None = None
    attempts = max(1, retries + 1)

    for attempt in range(attempts):
        try:
            response = client.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                headers=headers,
                timeout=timeout,
            )
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise ScraperHttpError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise ScraperHttpError(
                    f"响应不是合法 JSON: {response.text[:200]}"
                ) from exc
        except ScraperHttpError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.8 * (attempt + 1))
                continue

    raise ScraperHttpError(f"请求失败: {last_error}")
