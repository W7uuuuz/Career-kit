"""工具层共享的 JSON 解析与序列化辅助。"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import InvalidJsonError

# markdown code fence：```json {...}``` 或 ``` {...}```（DOTALL 支持多行）
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _scan_first_object(text: str, start_from: int = 0) -> str | None:
    """字符串感知扫描：提取首个平衡的 {...} 片段。

    正确处理引号内的花括号与转义（"a{b}" 不会被当成结构字符），
    找不到平衡对象返回 None。禁止 eval、禁止语义修复（如补逗号）。
    """
    start = text.find("{", start_from)
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


def _scan_all_objects(text: str, limit: int = 8) -> list[str]:
    """扫描全部平衡 {...} 片段（跳过解析失败候选的位置继续向后找）。

    用途：夹解释文字的输出里可能混入形如 ``{x}`` 的假象片段，
    只取首个会漏掉后面的真实对象；逐位置推进有限次，防文本爆量：
    上限 limit 个候选（后出现的通常更可能是最终结果，保持出现顺序）。
    """
    found: list[str] = []
    pos = 0
    while len(found) < limit:
        obj = _scan_first_object(text, pos)
        if obj is None:
            break
        found.append(obj)
        pos = text.find(obj, pos) + len(obj)
    return found


def _json_candidates(raw: str) -> list[str]:
    """按可靠度排列的解析候选：原文 → 围栏内容 → 全部平衡对象片段。"""
    candidates = [raw]
    candidates.extend(m.strip() for m in _FENCE_RE.findall(raw))
    candidates.extend(_scan_all_objects(raw))
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
    empty_dict: dict | None = None
    for candidate in _json_candidates(raw):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            parse_errors.append(str(exc))
            continue
        if isinstance(data, dict):
            if data:
                return data
            # 空对象 {} 先搁置——可能只是散文里的假象片段，
            # 继续尝试后面的候选；若全链只有它能 parse 才返回
            empty_dict = empty_dict or data
        else:
            non_object = type(data)

    if empty_dict is not None:
        return empty_dict
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
