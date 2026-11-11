"""结论引用记录工具——事实、从业者经验、推断都必须带来源与适用范围。

路线图通过 claim id 引用这些结论；交付时展示来源、置信度与局限。
没有来源的断言只能记为 inference，不能包装成事实。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..mcp_app import mcp
from ..models import Claim, ClaimSource
from .errors import InvalidJsonError, error_response
from .profile import load_profile, save_profile
from .tool_helpers import _json, _parse_json_param

CLAIM_TYPES = ("fact", "practitioner_experience", "inference")
CONFIDENCE_LEVELS = ("high", "medium", "low")
_ID_RE = re.compile(r"^cl_(\d+)$")


def _next_claim_id(profile: Any) -> str:
    existing = 0
    for claim in profile.claims or []:
        match = _ID_RE.match(str(getattr(claim, "id", "") or ""))
        if match:
            existing = max(existing, int(match.group(1)))
    return f"cl_{existing + 1:03d}"


def _normalize_source(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"name": raw.strip()}
    if not isinstance(raw, dict):
        return {}
    source: dict[str, Any] = {}
    for key in ("type", "name", "url", "date", "sample_size"):
        if key in raw:
            source[key] = raw[key]
    return source


def _validate_date(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.fromisoformat(text[:10])
    except ValueError:
        raise InvalidJsonError(f"{field} 必须是 YYYY-MM-DD 格式：{text!r}") from None
    return text[:10]


@mcp.tool()
def record_claim(claim_json: str) -> str:
    """记录一条可引用结论（事实 / 从业者经验 / 推断）。

    何时调用：
    - 抓到 JD/面经/同背景案例，需要把结论沉淀成可引用依据；
    - 用户或 Agent 听到 HR、面试官、在职员工的经验，需要记录原话与适用范围；
    - 路线图阶段准备引用结论前，先确保 claim 已存在。

    Args:
        claim_json: JSON 字符串，包含：
            statement: 结论原话（必填）
            claim_type: fact | practitioner_experience | inference（必填）
            source: {type, name, url, date, sample_size}
                - fact 必须有 url 或 name；
                - practitioner_experience 必须有 name（说话人/渠道）。
            scope: 适用范围，如 {education: 双非本, role: 后端, channel: 校招}
            confidence: high | medium | low（默认按类型给）
            limitation: 局限说明（经验类建议填写）
            expires_at: 有效期（YYYY-MM-DD，可选）

    Returns:
        JSON：claim id、保存结果、下一步。
    """
    try:
        data = _parse_json_param(claim_json, "结论")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)
    if not isinstance(data, dict):
        return error_response(
            "INVALID_PARAM",
            "claim_json 必须是 JSON 对象。",
            {"received": type(data).__name__},
        )

    statement = str(data.get("statement") or "").strip()
    if not statement:
        return error_response("INVALID_PARAM", "statement 不能为空。", {})

    claim_type = str(data.get("claim_type") or "").strip()
    if claim_type not in CLAIM_TYPES:
        return error_response(
            "INVALID_PARAM",
            f"claim_type 必须是 {' / '.join(CLAIM_TYPES)}，当前值：{claim_type!r}",
            {"allowed": list(CLAIM_TYPES)},
        )

    source_data = _normalize_source(data.get("source"))
    try:
        source = ClaimSource.model_validate(source_data)
    except Exception as exc:  # noqa: BLE001 - 统一转成可读参数错误
        return error_response("INVALID_PARAM", f"source 字段不合法：{exc}", {})

    if claim_type == "fact" and not (source.url or source.name):
        return error_response(
            "INVALID_PARAM",
            "fact 必须有来源：source.url（抓取/导入）或 source.name（机构/文件）。",
            {"claim_type": claim_type},
        )
    if claim_type == "practitioner_experience" and not source.name:
        return error_response(
            "INVALID_PARAM",
            "从业者经验必须写清 source.name（如「阿里 HR」「某大厂面试官」）。",
            {"claim_type": claim_type},
        )

    scope = data.get("scope") or {}
    if not isinstance(scope, dict):
        return error_response("INVALID_PARAM", "scope 必须是 JSON 对象。", {})
    if claim_type == "practitioner_experience" and not scope:
        return error_response(
            "INVALID_PARAM",
            "从业者经验必须写 scope（适用范围，如 education/role/channel），不能外推到所有情况。",
            {},
        )

    confidence = str(data.get("confidence") or "").strip()
    if not confidence:
        confidence = "low" if claim_type == "inference" else "medium"
    if confidence not in CONFIDENCE_LEVELS:
        return error_response(
            "INVALID_PARAM",
            f"confidence 必须是 {' / '.join(CONFIDENCE_LEVELS)}。",
            {"allowed": list(CONFIDENCE_LEVELS)},
        )

    try:
        expires_at = _validate_date(str(data.get("expires_at") or ""), "expires_at")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    profile = load_profile()
    claim = Claim(
        id=_next_claim_id(profile),
        statement=statement,
        claim_type=claim_type,
        source=source,
        scope={str(key): str(value) for key, value in scope.items() if value},
        confidence=confidence,
        limitation=str(data.get("limitation") or "").strip(),
        expires_at=expires_at,
    )
    profile.claims.append(claim)
    profile.touch()
    save_profile(profile)

    notes: list[str] = []
    if claim_type == "practitioner_experience" and not claim.limitation:
        notes.append("这是经验规则，建议补 limitation（如「单一口述，未做统计」），避免被当成通用事实。")
    if claim_type == "inference":
        notes.append("推断类结论不会作为事实引用；需要升级时补真实来源并改为 fact。")

    return _json({
        "message": f"已记录结论 {claim.id}。",
        "claim": claim.model_dump(),
        "notes": notes,
        "total": len(profile.claims),
        "next_steps": ["list_claims", "generate_roadmap"],
    })


@mcp.tool()
def list_claims(query: str = "") -> str:
    """列出已记录的结论引用，可按关键词过滤。

    何时调用：生成路线图前确认有哪些证据可引用；用户问「这条依据哪来的」时核对来源。

    Args:
        query: 可选关键词，匹配结论内容、来源名称与适用范围。

    Returns:
        JSON：结论列表与总数；没有记录时给出 record_claim 提示。
    """
    profile = load_profile()
    claims = list(profile.claims or [])
    key = str(query or "").strip().lower()
    if key:
        filtered = []
        for claim in claims:
            haystack = " ".join([
                claim.statement,
                claim.source.name,
                claim.source.url,
                " ".join(str(value) for value in (claim.scope or {}).values()),
            ]).lower()
            if key in haystack:
                filtered.append(claim)
        claims = filtered

    items = [claim.model_dump() for claim in claims]
    return _json({
        "count": len(items),
        "items": items,
        "message": (
            f"共 {len(items)} 条结论。"
            if items
            else "还没有记录任何结论——先用 record_claim 记录事实或从业者经验。"
        ),
        "next_steps": ["record_claim", "generate_roadmap"],
    })


__all__ = ["list_claims", "record_claim"]
