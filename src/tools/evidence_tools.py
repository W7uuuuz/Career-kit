"""阶段 7 MCP 工具：批量采集目标企业的岗位 JD 与面经证据。"""

from __future__ import annotations

from typing import Any

from ..core.artifacts.store import ArtifactStore
from ..core.stages import evidence
from ..core.stages.base import StageContext, StageResult
from ..mcp_app import mcp
from .errors import error_response
from .profile import get_active_profile_name
from .tool_helpers import _json


@mcp.tool()
async def collect_company_evidence(
    company_pool_id: str = "",
    per_company_limit: int = 5,
    max_companies: int = 15,
    max_jd: int = 50,
    max_interviews: int = 30,
    refresh: bool = False,
) -> str:
    """采集目标企业的岗位 JD 与面经，生成 EvidenceRun 与证据池报告（阶段 7）。

    何时调用：目标企业池已确认（select_target_companies）之后。
    本工具只采集事实：抓取、城市硬筛、详情补抓、去重、来源状态与置信度；
    LLM 不参与，不编造缺失内容。单源失败不影响整批，失败原因写入 source_status 与 gaps。

    Args:
        company_pool_id: 目标企业池 artifact id；空串取当前档案最新且已确认的企业池
        per_company_limit: 每家企业的 JD 抓取上限
        max_companies: 本次最多抓取的企业数
        max_jd: 最终保留的 JD 上限
        max_interviews: 最终保留的面经上限
        refresh: true 时不复用 profile.research 中 7 天内的历史样本

    Returns:
        JSON 字符串：artifact id、样本统计、置信度、来源状态、数据缺口、
        报告完整路径与下一步 analyze_company_requirements。
    """
    profile_name = get_active_profile_name()
    store = ArtifactStore()
    ctx = StageContext(profile_name=profile_name, store=store)
    result = await evidence.run_async(
        ctx,
        {
            "company_pool_id": company_pool_id,
            "per_company_limit": per_company_limit,
            "max_companies": max_companies,
            "max_jd": max_jd,
            "max_interviews": max_interviews,
            "refresh": refresh,
        },
    )
    if result.status in {"failed", "insufficient_data"}:
        code = "EVIDENCE_COLLECTION_FAILED" if result.status == "failed" else "INSUFFICIENT_DATA"
        return error_response(
            code,
            result.message,
            {"artifact_id": result.artifact_id, "warnings": result.warnings},
        )

    artifact = store.load(result.artifact_id)
    if artifact is None:
        return error_response(
            "ARTIFACT_NOT_FOUND",
            "证据池已生成但无法从 artifact 存储读取",
            {"artifact_id": result.artifact_id},
        )
    return _json(_summarize(artifact, result, profile_name))


def _summarize(
    artifact: dict[str, Any], result: StageResult, profile_name: str
) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    counts = artifact.get("counts") if isinstance(artifact.get("counts"), dict) else {}
    confidence = (
        artifact.get("confidence") if isinstance(artifact.get("confidence"), dict) else {}
    )
    source_status = [item for item in meta.get("source_status") or [] if isinstance(item, dict)]
    failed = [item for item in source_status if item.get("status") == "failed"]
    report_paths = (
        artifact.get("report_paths") if isinstance(artifact.get("report_paths"), dict) else {}
    )
    return {
        "status": result.status,
        "artifact_id": str(meta.get("id") or result.artifact_id),
        "profile_name": profile_name,
        "message": result.message,
        "counts": dict(counts),
        "confidence": dict(confidence),
        "source_status": source_status,
        "failed_sources": [
            {"source": item.get("source"), "error": item.get("error")} for item in failed
        ],
        "gaps": list(artifact.get("gaps") or []),
        "report_paths": {key: str(value) for key, value in report_paths.items()},
        "next_tool": "analyze_company_requirements",
        "next_step": (
            "调用 analyze_company_requirements（可传 evidence_run_id="
            f"{meta.get('id') or result.artifact_id}）进入阶段 8 企业需求分析。"
        ),
    }


__all__ = ["collect_company_evidence"]
