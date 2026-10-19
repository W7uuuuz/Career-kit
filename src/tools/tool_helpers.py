"""工具层共享的 JSON 解析与序列化辅助。"""

from __future__ import annotations

import json
from typing import Any

from .errors import InvalidJsonError


def _parse_json_param(raw: str, field_name: str = "参数") -> dict:
    """解析 JSON 字符串参数，失败时抛出 InvalidJsonError。"""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidJsonError(
            f"{field_name} JSON 解析失败：{exc}",
            {"raw": raw[:200]},
        ) from exc
    if not isinstance(data, dict):
        raise InvalidJsonError(
            f"{field_name} 必须是 JSON 对象（dict），收到的是 {type(data).__name__}",
            {"raw": raw[:200]},
        )
    return data


def _json(obj: Any) -> str:
    """将对象序列化为 JSON 字符串。

    MCP 工具返回类型必须是 str，返回 dict 会触发 FastMCP schema 校验失败。
    所有工具的结构化返回值必须经过本函数。
    """
    return json.dumps(obj, ensure_ascii=False, indent=2)
