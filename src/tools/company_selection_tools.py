"""阶段 6 MCP 工具——目标企业筛选（推荐 / 确认 CompanyPool）。"""

from __future__ import annotations

from typing import Any

from ..core.adapters.legacy_profile import target_spec
from ..core.artifacts.store import ArtifactStore
from ..core.stages import target_companies
from ..core.stages.base import StageContext, StageResult
from ..mcp_app import mcp
from .errors import error_response
from .profile import get_active_profile_name, load_profile
from .state_gate import require_state
from .tool_helpers import _json


@mcp.tool()
def select_target_companies(
    target_tiers: str = "",
    bridge_tiers: str = "",
    city: str = "",
    role: str = "",
    industry: str = "互联网",
    include: str = "",
    exclude: str = "",
    confirmed: bool = False,
) -> str:
    """筛选并确认目标企业池（阶段 6）。

    何时调用：目标岗位方向已确定，需要把方向落成具体目标企业池时。
    本工具只做目录筛选与确认门禁，不抓取 JD、不统计需求。

    Args:
        target_tiers: 目标档位，支持 JSON 数组或逗号/顿号/空格分隔；空则读档案（默认 大厂）
        bridge_tiers: 桥接档位；空则读档案（默认 中厂）
        city: 目标城市；空则读档案
        role: 目标岗位；空则读档案
        industry: 目标行业；空则默认 互联网
        include: 额外纳入的企业（id/名称/别名），支持 JSON 数组或分隔符
        exclude: 排除的企业，支持 JSON 数组或分隔符；同一企业同时出现时 include 优先
        confirmed: 用户已确认名单时传 true；未确认只生成推荐池，不允许下游

    Returns:
        JSON 字符串：状态、artifact id、按档位分组的企业、可抓/不可抓、
        数据缺口与下一步建议。
    """
    profile_name = get_active_profile_name()
    profile = load_profile(profile_name)
    gate = require_state(profile, "select_target_companies")
    if isinstance(gate, str):
        return gate
    spec = target_spec(profile)

    inputs: dict[str, Any] = {
        "target_spec": spec.model_dump(),
        "target_tiers": target_tiers,
        "bridge_tiers": bridge_tiers,
        "city": city,
        "role": role,
        "industry": industry,
        "include": include,
        "exclude": exclude,
        "confirmed": confirmed,
    }
    store = ArtifactStore()
    ctx = StageContext(profile_name=profile_name, store=store, user_confirmed=confirmed)
    result = target_companies.run(ctx, inputs)

    if result.status in {"failed", "insufficient_data"}:
        return error_response(
            "COMPANY_SELECTION_FAILED" if result.status == "failed" else "INSUFFICIENT_DATA",
            result.message,
            {"artifact_id": result.artifact_id, "warnings": result.warnings},
        )

    artifact = store.load(result.artifact_id)
    if artifact is None:
        return error_response(
            "ARTIFACT_NOT_FOUND",
            "目标企业池已生成但无法从 artifact 存储读取",
            {"artifact_id": result.artifact_id},
        )
    return _json(_summarize(artifact, result, profile_name))


def _summarize(artifact: dict[str, Any], result: StageResult, profile_name: str) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    meta_inputs = meta.get("inputs") if isinstance(meta.get("inputs"), dict) else {}
    validation = meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
    target = artifact.get("target_spec") if isinstance(artifact.get("target_spec"), dict) else {}
    counts = artifact.get("counts") if isinstance(artifact.get("counts"), dict) else {}

    companies = [item for item in artifact.get("companies") or [] if isinstance(item, dict)]
    selected = [item for item in companies if item.get("status") != "excluded"]
    excluded = [str(item.get("name") or "") for item in companies if item.get("status") == "excluded"]

    by_tier: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        tier = str(item.get("tier") or "未收录")
        by_tier.setdefault(tier, []).append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "scrapable": bool(item.get("scrapable")),
                "scrapers": list(item.get("scrapers") or []),
                "reason": str(item.get("reason") or ""),
            }
        )
    scrapable = [str(item.get("name") or "") for item in selected if item.get("scrapable")]
    not_scrapable = [str(item.get("name") or "") for item in selected if not item.get("scrapable")]

    confirmed = validation.get("confirmed") is True
    total = int(counts.get("total") or len(selected))
    if result.status == "ok":
        summary = f"已确认目标企业池：{total} 家（可抓 {len(scrapable)} / 未接入 {len(not_scrapable)}）。"
        next_tool = "collect_company_evidence"
        next_step = "调用 collect_company_evidence 批量抓取 JD 与面经（阶段 7）。"
    elif result.status == "needs_confirmation":
        summary = (
            f"已生成推荐企业池：{total} 家（可抓 {len(scrapable)} / 未接入 {len(not_scrapable)}），"
            "尚未确认。"
        )
        next_tool = "select_target_companies"
        next_step = "向用户展示名单并确认；用户确认后以 confirmed=true 重新调用本工具。"
    else:
        summary = result.message
        next_tool = "select_target_companies"
        next_step = "调整档位、行业或 include/exclude 后重试。"

    unscrapable_note = ""
    if not_scrapable:
        unscrapable_note = (
            "以下企业未接入自动抓取，阶段 7 将跳过；需用户手动投递或后续补充 scraper："
            + "、".join(not_scrapable)
        )

    return {
        "status": result.status,
        "artifact_id": result.artifact_id,
        "profile_name": profile_name,
        "summary": summary,
        "confirmed": confirmed,
        "target": {
            "role": str(target.get("role") or ""),
            "direction": str(target.get("direction") or ""),
            "city": str(target.get("city") or ""),
            "target_tiers": list(target.get("target_tiers") or []),
            "bridge_tiers": list(target.get("bridge_tiers") or []),
            "industry": str(meta_inputs.get("industry") or ""),
        },
        "counts": dict(counts),
        "by_tier": by_tier,
        "scrapable": scrapable,
        "not_scrapable": not_scrapable,
        "unscrapable_note": unscrapable_note,
        "excluded": excluded,
        "gaps": list(artifact.get("gaps") or []),
        "warnings": list(result.warnings),
        "next_tool": next_tool,
        "next_step": next_step,
    }


__all__ = ["select_target_companies"]
