"""工具层共享的 JSON 解析与序列化辅助。"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import InvalidJsonError

# markdown code fence：```json {...}``` 或 ``` {...}```（DOTALL 支持多行）
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _scan_first_object(text: str) -> str | None:
    """字符串感知扫描：提取首个平衡的 {...} 片段。

    正确处理引号内的花括号与转义（"a{b}" 不会被当成结构字符），
    找不到平衡对象返回 None。禁止 eval、禁止语义修复（如补逗号）。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _json_candidates(raw: str) -> list[str]:
    """按可靠度排列的解析候选：原文 → 围栏内容 → 首个平衡对象。"""
    candidates = [raw]
    candidates.extend(m.strip() for m in _FENCE_RE.findall(raw))
    obj = _scan_first_object(raw)
    if obj is not None:
        candidates.append(obj)
    # 原文去重（fence 内容可能等于原文）
    seen: set[str] = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _parse_json_param(raw: Any, field_name: str = "参数") -> dict:
    """多策略解析 JSON 参数，失败时抛出 InvalidJsonError。

    策略链：直接 json.loads → markdown code fence → 首个平衡 {...}。
    覆盖 LLM 常见退化输出（前后带解释文字、代码块包裹），仍失败时
    抛 InvalidJsonError 并给出明确重试指引；非对象 JSON（数组/标量）
    单独报错，不做语义猜测。
    """
    if not isinstance(raw, str):
        raise InvalidJsonError(
            f"{field_name} 必须是字符串，收到的是 {type(raw).__name__}",
            {"raw": str(raw)[:200]},
        )
    if not raw.strip():
        raise InvalidJsonError(
            f"{field_name} 为空——请提供 JSON 对象后重试",
            {"raw": ""},
        )

    parse_errors: list[str] = []
    non_object: type | None = None
    for candidate in _json_candidates(raw):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            parse_errors.append(str(exc))
            continue
        if isinstance(data, dict):
            return data
        non_object = type(data)

    if non_object is not None:
        raise InvalidJsonError(
            f"{field_name} 必须是 JSON 对象（dict），收到的是 {non_object.__name__}",
            {"raw": raw[:200]},
        )
    raise InvalidJsonError(
        f"{field_name} JSON 解析失败（已尝试原文/代码块/对象提取）：\n"
        "请只返回一个 JSON 对象，不要夹解释文字，键用双引号，无尾逗号。",
        {"raw": raw[:200], "attempts": len(parse_errors)},
    )


def _json(obj: Any) -> str:
    """将对象序列化为 JSON 字符串。

    MCP 工具返回类型必须是 str，返回 dict 会触发 FastMCP schema 校验失败。
    所有工具的结构化返回值必须经过本函数。
    """
    return json.dumps(obj, ensure_ascii=False, indent=2)
