"""阶段 7 MCP 工具：批量采集目标企业的岗位 JD 与面经证据。"""

from __future__ import annotations

import sys
from typing import Any

from ..core.artifacts.store import ArtifactStore
from ..core.stages import evidence
from ..core.stages.base import StageContext, StageResult
from ..guidance import login_action
from ..mcp_app import mcp
from ..scrapers.boss.auth import (
    describe_ttl as boss_describe_ttl,
    has_valid_cookies as boss_has_valid_cookies,
)
from .errors import error_response
from .profile import get_active_profile_name, load_profile
from .state_gate import require_state
from .tool_helpers import _json


@mcp.tool()
async def collect_company_evidence(
    company_pool_id: str = "",
    per_company_limit: int = 5,
    max_companies: int = 15,
    max_jd: int = 50,
    max_interviews: int = 30,
    refresh: bool = False,
    include_boss: bool = False,
    boss_confirmed: bool = False,
    company_ids: str = "",
    batch_size: int = 3,
    resume: bool = True,
    include_outside_pool: bool = False,
) -> str:
    """采集目标企业的岗位 JD 与面经，生成 EvidenceRun 与证据池报告（阶段 7）。

    何时调用：目标企业池已确认（select_target_companies）之后。
    本工具只采集事实：抓取、城市硬筛、详情补抓、去重、来源状态与置信度；
    LLM 不参与，不编造缺失内容。单源失败不影响整批，失败原因写入 source_status 与 gaps。

    分批续跑（默认开启）：
    - 单次调用只处理 batch_size 家企业，每完成一家写入检查点；
    - 还有企业未完成时返回 status=partial，不会生成 EvidenceRun；
    - 再次调用本工具会自动从检查点续跑，直到全部完成才生成证据池。

    BOSS 直聘纪律（include_boss=True 时）：
    - BOSS 是跨公司补充源，只补充薪资与广度，不能替代目标企业池；
    - 抓取前只问一次是否把 BOSS 纳入采集，用户同意后传 boss_confirmed=true；
    - 未确认返回 CONFIRMATION_REQUIRED；确认但未登录返回 LOGIN_REQUIRED +
      next_tool=boss_login，直接调用 boss_login(action="login")，不再追问第二次；
    - 登录成功后窗口常驻、切成功页、不自动关闭；命令仅作兜底，
      绝不把登录失败直接当抓取失败。

    Args:
        company_pool_id: 目标企业池 artifact id；空串取当前档案最新且已确认的企业池
        per_company_limit: 每家企业的 JD 抓取上限
        max_companies: 本次最多抓取的企业数（BOSS 不占该名额）
        max_jd: 最终保留的 JD 上限
        max_interviews: 最终保留的面经上限
        refresh: true 时不复用 profile.research 中 7 天内的历史样本，也不复用检查点
        include_boss: 是否把 BOSS 直聘作为补充证据源（默认关闭）
        boss_confirmed: 用户已确认抓取 BOSS 时为 true；未确认会返回 CONFIRMATION_REQUIRED
        company_ids: 只采集指定企业（逗号/顿号/空格分隔的 id 或名称）；空串表示全部
        batch_size: 单次调用最多处理的企业数（默认 3，范围 1-10）
        resume: 是否复用未完成检查点续跑（默认 true）
        include_outside_pool: 是否保留企业池外的复用样本（默认 false，直接丢弃）

    Returns:
        JSON 字符串：artifact id、样本统计（含 BOSS 条数）、置信度、来源状态、
        数据缺口、报告完整路径与下一步 analyze_company_requirements；
        status=partial 时返回检查点 id、本批进度与续跑指引。
    """
    gate = require_state(load_profile(), "collect_company_evidence")
    if isinstance(gate, str):
        return gate

    if include_boss and not boss_confirmed:
        return error_response(
            "CONFIRMATION_REQUIRED",
            "采集范围包含 BOSS 直聘：同意抓取即可，若尚未登录我会直接打开登录窗口"
            f"（登录态 {boss_describe_ttl()}有效），你只需扫码。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "login_tool": "boss_login",
                "question": (
                    "是否把 BOSS 直聘纳入本次采集？如需登录我会直接打开登录窗口，"
                    "你只需扫码。"
                ),
                "options": [
                    "同意：带 include_boss=true、boss_confirmed=true 重新调用；"
                    "若未登录先调用 boss_login(action=\"login\")",
                    "不同意：不带 include_boss 重新调用，只采集目标企业池",
                ],
                "rule": "只问一次；同意后未登录时直接调用 boss_login(action=\"login\")，"
                        "不得静默跳过 BOSS",
            },
        )

    if include_boss and boss_confirmed and not boss_has_valid_cookies():
        return error_response(
            "LOGIN_REQUIRED",
            "BOSS 直聘已确认采集但尚未登录：直接调用 boss_login(action=\"login\") 扫码，"
            "登录成功后浏览器保持常开，再重试；也可以不带 include_boss 只采集目标企业池。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "action": "boss_login",
                "reason": "not_logged_in",
                "next_tool": "boss_login",
                "after_login": (
                    "登录完成后带 include_boss=true、boss_confirmed=true "
                    "重新调用 collect_company_evidence"
                ),
                "alternative": "不想登录时不传 include_boss 重跑，只采集目标企业池",
                "rule": "用户已同意采集 BOSS，直接调用 boss_login(action=\"login\")，"
                        "不要再问第二次是否登录；不得把登录失败直接当抓取失败宣布",
            },
        )

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
            "include_boss": include_boss,
            "boss_confirmed": boss_confirmed,
            "company_ids": company_ids,
            "batch_size": batch_size,
            "resume": resume,
            "include_outside_pool": include_outside_pool,
        },
    )
    if result.status == "partial":
        return _json(_partial_summary(store, result))
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


def _partial_summary(store: ArtifactStore, result: StageResult) -> dict[str, Any]:
    """分批未完成：返回检查点进度，提示继续调用本工具续跑。"""
    checkpoint = store.load(result.artifact_id)
    counts = (
        checkpoint.get("counts")
        if isinstance(checkpoint, dict) and isinstance(checkpoint.get("counts"), dict)
        else {}
    )
    details = result.details if isinstance(result.details, dict) else {}
    return {
        "status": "partial",
        "artifact_id": result.artifact_id,
        "checkpoint_id": result.artifact_id,
        "message": result.message,
        "progress": {
            "done": int(details.get("done") or 0),
            "total": int(details.get("total") or 0),
            "remaining": int(details.get("remaining") or 0),
        },
        "counts": dict(counts),
        "next_tool": "collect_company_evidence",
        "next_step": "继续调用本工具，默认自动续跑",
    }


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
    boss_status = next(
        (
            item
            for item in source_status
            if item.get("source") == "boss" and item.get("scope") == "jd"
        ),
        None,
    )
    boss_jd_count = sum(
        1
        for item in artifact.get("jd_items") or []
        if isinstance(item, dict) and item.get("source") == "boss"
    )
    report_paths = (
        artifact.get("report_paths") if isinstance(artifact.get("report_paths"), dict) else {}
    )
    gaps = list(artifact.get("gaps") or [])
    batch = (
        result.details.get("batch")
        if isinstance(result.details.get("batch"), dict)
        else {}
    )
    summary = {
        "status": result.status,
        "artifact_id": str(meta.get("id") or result.artifact_id),
        "profile_name": profile_name,
        "message": result.message,
        "counts": dict(counts),
        "confidence": dict(confidence),
        "summary": {
            "counts": dict(counts),
            "confidence": dict(confidence),
            "top_gaps": gaps[:5],
        },
        "batch": {
            "done": int(batch.get("done") or counts.get("companies_requested") or 0),
            "total": int(batch.get("total") or counts.get("companies_requested") or 0),
        },
        "source_status": source_status,
        "failed_sources": [
            {"source": item.get("source"), "error": item.get("error")} for item in failed
        ],
        "gaps": gaps,
        "report_paths": {key: str(value) for key, value in report_paths.items()},
        "next_tool": "analyze_company_requirements",
        "next_step": (
            "调用 analyze_company_requirements（可传 evidence_run_id="
            f"{meta.get('id') or result.artifact_id}）进入阶段 8 企业需求分析。"
        ),
    }
    if boss_status is not None:
        summary["boss"] = {
            "jd_count": boss_jd_count,
            "returned": int(boss_status.get("count") or 0),
            "status": boss_status.get("status"),
            "error": str(boss_status.get("error") or ""),
        }
    return summary


__all__ = ["collect_company_evidence"]
