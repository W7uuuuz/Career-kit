"""阶段 7 MCP 工具：批量采集目标企业的岗位 JD 与面经证据。"""

from __future__ import annotations

import sys
from typing import Any

from ..core.artifacts.store import ArtifactStore
from ..core.stages import evidence
from ..core.stages.base import StageContext, StageResult
from ..guidance import login_action
from ..mcp_app import mcp
from ..scrapers.boss.auth import has_valid_cookies as boss_has_valid_cookies
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
    include_boss: bool = False,
    boss_confirmed: bool = False,
) -> str:
    """采集目标企业的岗位 JD 与面经，生成 EvidenceRun 与证据池报告（阶段 7）。

    何时调用：目标企业池已确认（select_target_companies）之后。
    本工具只采集事实：抓取、城市硬筛、详情补抓、去重、来源状态与置信度；
    LLM 不参与，不编造缺失内容。单源失败不影响整批，失败原因写入 source_status 与 gaps。

    BOSS 直聘纪律（include_boss=True 时）：
    - BOSS 是跨公司补充源，只补充薪资与广度，不能替代目标企业池；
    - 抓取前必须先问用户是否抓取 BOSS，用户同意后传 boss_confirmed=true；
    - 未确认返回 CONFIRMATION_REQUIRED；确认但未登录返回 LOGIN_REQUIRED，
      先问用户是否现在登录，绝不把登录失败直接当抓取失败；
    - 用户同意登录后，用 harness 的终端/Bash 直接运行 login_command（用户只需扫码），
      不要把命令丢给用户手动执行。

    Args:
        company_pool_id: 目标企业池 artifact id；空串取当前档案最新且已确认的企业池
        per_company_limit: 每家企业的 JD 抓取上限
        max_companies: 本次最多抓取的企业数（BOSS 不占该名额）
        max_jd: 最终保留的 JD 上限
        max_interviews: 最终保留的面经上限
        refresh: true 时不复用 profile.research 中 7 天内的历史样本
        include_boss: 是否把 BOSS 直聘作为补充证据源（默认关闭）
        boss_confirmed: 用户已确认抓取 BOSS 时为 true；未确认会返回 CONFIRMATION_REQUIRED

    Returns:
        JSON 字符串：artifact id、样本统计（含 BOSS 条数）、置信度、来源状态、
        数据缺口、报告完整路径与下一步 analyze_company_requirements。
    """
    if include_boss and not boss_confirmed:
        return error_response(
            "CONFIRMATION_REQUIRED",
            "采集范围包含 BOSS 直聘：该源需要扫码登录（登录态 2 小时有效），"
            "抓取前必须先问用户是否进行 BOSS 抓取。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "question": (
                    "是否抓取 BOSS 直聘？我可以直接帮你打开登录窗口，"
                    "你只需扫码（登录态 2 小时有效）。"
                ),
                "options": [
                    "同意：用 harness 运行登录脚本，扫码后带 include_boss=true、"
                    "boss_confirmed=true 重新调用 collect_company_evidence",
                    "不同意：不带 include_boss 重新调用，只采集目标企业池",
                ],
                "rule": "把 question 转问用户；同意后用 harness 直接运行 login_command，"
                        "不要把命令丢给用户手动执行；不得静默跳过 BOSS",
            },
        )

    if include_boss and boss_confirmed and not boss_has_valid_cookies():
        return error_response(
            "LOGIN_REQUIRED",
            "BOSS 直聘登录态不可用（未登录或超过 2 小时）：本次没有启动抓取，"
            "先问用户是否现在登录；也可以不带 include_boss 只采集目标企业池。",
            {
                **login_action(f'"{sys.executable}" -m src.scrapers.boss.login'),
                "question": (
                    "BOSS 直聘未登录，我可以直接帮你打开登录窗口扫码，要现在登录吗？"
                ),
                "after_login": (
                    "登录完成后带 include_boss=true、boss_confirmed=true "
                    "重新调用 collect_company_evidence"
                ),
                "alternative": "不想登录时不传 include_boss 重跑，只采集目标企业池",
                "rule": "先问用户是否现在登录；同意后用 harness 直接运行 login_command，"
                        "不要把命令丢给用户手动执行；不得把登录失败直接当抓取失败宣布",
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
    summary = {
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
    if boss_status is not None:
        summary["boss"] = {
            "jd_count": boss_jd_count,
            "returned": int(boss_status.get("count") or 0),
            "status": boss_status.get("status"),
            "error": str(boss_status.get("error") or ""),
        }
    return summary


__all__ = ["collect_company_evidence"]
