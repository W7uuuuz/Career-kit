"""阶段状态机——根据档案 core_state 与 artifact 事实推导下一步。

只读：不写档案、不落库。artifact 优先按 core_state 中的 id 解析，
缺失时回退到该阶段的 latest；下游 artifact 必须引用上游 artifact id。

12 阶段顺序：档案 → 目标 → 市场基线 → 差距 → 基线方案 → 企业池 →
证据 → 需求 → 执行方案 → 执行状态。阶段 11/12（投递、复盘）是可选阶段，
不阻塞执行；执行状态就绪后只作为 optional_next_tools 推荐。
"""

from __future__ import annotations

from typing import Any

from ...tools.profile import load_profile
from ..artifacts.store import ArtifactStore

STAGE_PROFILE = "profile"
STAGE_TARGET = "target"
STAGE_MARKET = "market_baseline"
STAGE_GAP = "gap"
STAGE_BASELINE_PLAN = "baseline_plan"
STAGE_COMPANY_POOL = "company_pool"
STAGE_EVIDENCE = "evidence"
STAGE_REQUIREMENT = "requirement"
STAGE_EXECUTION_PLAN = "execution_plan"
STAGE_EXECUTION = "execution"
STAGE_APPLICATIONS = "applications"
STAGE_REVIEW = "review"

STAGE_EXECUTING = "executing"

_STAGE_ORDER: tuple[str, ...] = (
    STAGE_PROFILE,
    STAGE_TARGET,
    STAGE_MARKET,
    STAGE_GAP,
    STAGE_BASELINE_PLAN,
    STAGE_COMPANY_POOL,
    STAGE_EVIDENCE,
    STAGE_REQUIREMENT,
    STAGE_EXECUTION_PLAN,
    STAGE_EXECUTION,
    STAGE_APPLICATIONS,
    STAGE_REVIEW,
)

_STAGE_KEYS: dict[str, str] = {
    STAGE_PROFILE: "profile_id",
    STAGE_TARGET: "target_spec_id",
    STAGE_MARKET: "market_baseline_id",
    STAGE_GAP: "gap_report_id",
    STAGE_BASELINE_PLAN: "baseline_plan_id",
    STAGE_COMPANY_POOL: "company_pool_id",
    STAGE_EVIDENCE: "evidence_run_id",
    STAGE_REQUIREMENT: "requirement_profile_id",
    STAGE_EXECUTION_PLAN: "execution_plan_id",
    STAGE_EXECUTION: "execution_state_id",
    STAGE_APPLICATIONS: "application_state_id",
    STAGE_REVIEW: "review_report_id",
}

_ARTIFACT_KEYS = tuple(_STAGE_KEYS[stage] for stage in _STAGE_ORDER)

_OPTIONAL_EXECUTION_TOOLS = [
    "record_application",
    "check_plan_fit",
    "get_weekly_review",
]


def next_action(profile_name: str) -> dict[str, Any]:
    """返回当前档案的下一步：阶段、建议工具、原因与已解析的 artifact ids。"""
    profile = load_profile(profile_name)
    core_state = getattr(profile, "core_state", {})
    if not isinstance(core_state, dict):
        core_state = {}
    store = ArtifactStore()
    artifact_ids: dict[str, str] = dict.fromkeys(_ARTIFACT_KEYS, "")

    resolved: dict[str, dict[str, Any] | None] = {}
    for stage in _STAGE_ORDER:
        resolved[stage] = _resolve(
            store, profile_name, stage, str(core_state.get(_STAGE_KEYS[stage]) or "")
        )
    has_artifact = any(item is not None for item in resolved.values())

    for stage in (STAGE_PROFILE, STAGE_TARGET, STAGE_MARKET, STAGE_GAP, STAGE_BASELINE_PLAN):
        if resolved[stage] is not None:
            artifact_ids[_STAGE_KEYS[stage]] = _artifact_id(resolved[stage])
            continue
        if _downstream_exists(resolved, stage):
            continue
        if not has_artifact and _legacy_stage_done(profile, stage):
            continue
        return _stage_action(profile, stage, artifact_ids)

    pool = resolved[STAGE_COMPANY_POOL]
    if pool is None:
        return _action(STAGE_COMPANY_POOL, "select_target_companies", "尚未生成 CompanyPool", artifact_ids)
    artifact_ids["company_pool_id"] = _artifact_id(pool)
    if not _confirmed(pool):
        return _action(STAGE_COMPANY_POOL, "select_target_companies", "CompanyPool 尚未确认", artifact_ids)

    evidence = resolved[STAGE_EVIDENCE]
    if evidence is None or not _references(evidence, "company_pool_id", artifact_ids["company_pool_id"]):
        reason = "缺少与当前 CompanyPool 匹配的 EvidenceRun"
        return _action(STAGE_EVIDENCE, "collect_company_evidence", reason, artifact_ids)
    artifact_ids["evidence_run_id"] = _artifact_id(evidence)

    requirement = resolved[STAGE_REQUIREMENT]
    if requirement is None or not _references(
        requirement, "evidence_run_id", artifact_ids["evidence_run_id"]
    ):
        reason = "缺少与当前 EvidenceRun 匹配的 RequirementProfile"
        return _action(STAGE_REQUIREMENT, "analyze_company_requirements", reason, artifact_ids)
    artifact_ids["requirement_profile_id"] = _artifact_id(requirement)

    plan = resolved[STAGE_EXECUTION_PLAN]
    if plan is None or not _references(
        plan, "requirement_profile_id", artifact_ids["requirement_profile_id"]
    ):
        reason = "缺少与当前 RequirementProfile 匹配的 ExecutionPlan"
        return _action(STAGE_EXECUTION_PLAN, "plan_execution_alignment", reason, artifact_ids)
    artifact_ids["execution_plan_id"] = _artifact_id(plan)

    if not bool(plan.get("applied")):
        reason = "ExecutionPlan 已生成但未应用"
        return _action(STAGE_EXECUTION_PLAN, "save_execution_alignment", reason, artifact_ids)

    execution = resolved[STAGE_EXECUTION]
    if execution is not None and _references(
        execution, "execution_plan_id", artifact_ids["execution_plan_id"]
    ):
        artifact_ids["execution_state_id"] = _artifact_id(execution)
        return _action(
            STAGE_EXECUTING,
            "get_next_tasks",
            "执行状态已就绪，按当前阶段任务推进",
            artifact_ids,
            optional_next_tools=list(_OPTIONAL_EXECUTION_TOOLS),
        )

    if _has_tasks(profile):
        return _action(
            STAGE_EXECUTING,
            "get_next_tasks",
            "档案已有任务，按当前阶段任务推进",
            artifact_ids,
            optional_next_tools=list(_OPTIONAL_EXECUTION_TOOLS),
        )

    return _action(
        STAGE_EXECUTION,
        "generate_tasks",
        "ExecutionPlan 已应用，尚未生成任务与执行状态",
        artifact_ids,
    )


def _stage_action(
    profile: Any, stage: str, artifact_ids: dict[str, str]
) -> dict[str, Any]:
    if stage == STAGE_PROFILE:
        return _action(STAGE_PROFILE, "finalize_profile", "尚未建立 ProfileSnapshot", artifact_ids)
    if stage == STAGE_TARGET:
        tool = "intake(want)" if _has_want(profile) else "explore_goals"
        reason = "目标已存在但尚未写入 TargetSpec" if _has_want(profile) else "尚未确定目标岗位"
        return _action(STAGE_TARGET, tool, reason, artifact_ids)
    if stage == STAGE_MARKET:
        return _action(STAGE_MARKET, "gather_research_data", "尚未生成 MarketBaseline", artifact_ids)
    if stage == STAGE_GAP:
        return _action(STAGE_GAP, "analyze_gaps", "尚未生成 GapReport", artifact_ids)
    return _action(STAGE_BASELINE_PLAN, "generate_roadmap", "尚未生成 BaselinePlan", artifact_ids)


def _action(
    stage: str,
    next_tool: str,
    reason: str,
    artifact_ids: dict[str, str],
    optional_next_tools: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "next_tool": next_tool,
        "reason": reason,
        "artifact_ids": dict(artifact_ids),
        "optional_next_tools": list(optional_next_tools or []),
    }


def _downstream_exists(
    resolved: dict[str, dict[str, Any] | None], stage: str
) -> bool:
    index = _STAGE_ORDER.index(stage)
    return any(resolved[later] is not None for later in _STAGE_ORDER[index + 1 :])


def _legacy_stage_done(profile: Any, stage: str) -> bool:
    """旧档案没有 artifact 时，用已有 section 推断阶段完成；不下游写档案。"""
    plan = getattr(profile, "plan", None) or {}
    research = getattr(profile, "research", None) or {}
    tasks = getattr(profile, "tasks", None) or []
    has_plan = isinstance(plan, dict) and bool(plan.get("roadmap"))
    has_gap = bool(getattr(profile, "gap", None))
    has_research = isinstance(research, dict) and bool(
        research.get("report_md") or research.get("jd_samples") or research.get("cases")
    )
    has_tasks = bool(tasks)
    has_want = _has_want(profile)
    has_profile = bool(
        getattr(profile, "summary", "")
        or getattr(profile, "who", None)
        or getattr(profile, "have", None)
    )
    if stage == STAGE_PROFILE:
        return has_profile or has_want or has_research or has_gap or has_plan or has_tasks
    if stage == STAGE_TARGET:
        return has_want or has_research or has_gap or has_plan or has_tasks
    if stage == STAGE_MARKET:
        return has_research or has_gap or has_plan or has_tasks
    if stage == STAGE_GAP:
        return has_gap or has_plan or has_tasks
    if stage == STAGE_BASELINE_PLAN:
        return has_plan or has_tasks
    return False


def _has_want(profile: Any) -> bool:
    want = getattr(profile, "want", None) or {}
    return isinstance(want, dict) and bool(want)


def _has_tasks(profile: Any) -> bool:
    return bool(getattr(profile, "tasks", None) or [])


def _resolve(
    store: ArtifactStore, profile_name: str, stage: str, artifact_id: str
) -> dict[str, Any] | None:
    if artifact_id:
        data = store.load(artifact_id)
        if _matches_stage(data, stage):
            return data
    data = store.latest(profile_name, stage)
    return data if _matches_stage(data, stage) else None


def _matches_stage(data: dict[str, Any] | None, stage: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    return isinstance(meta, dict) and meta.get("stage") == stage


def _artifact_id(artifact: dict[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    meta = artifact.get("meta")
    return str(meta.get("id") or "") if isinstance(meta, dict) else ""


def _confirmed(pool: dict[str, Any]) -> bool:
    meta = pool.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    if isinstance(validation, dict) and validation.get("confirmed") is True:
        return True
    companies = pool.get("companies")
    if not isinstance(companies, list):
        return False
    return any(isinstance(item, dict) and item.get("status") == "confirmed" for item in companies)


def _references(artifact: dict[str, Any], field: str, expected_id: str) -> bool:
    if not expected_id:
        return True
    actual = str(artifact.get(field) or "")
    return not actual or actual == expected_id


__all__ = [
    "STAGE_APPLICATIONS",
    "STAGE_BASELINE_PLAN",
    "STAGE_COMPANY_POOL",
    "STAGE_EVIDENCE",
    "STAGE_EXECUTING",
    "STAGE_EXECUTION",
    "STAGE_EXECUTION_PLAN",
    "STAGE_GAP",
    "STAGE_MARKET",
    "STAGE_PROFILE",
    "STAGE_REQUIREMENT",
    "STAGE_REVIEW",
    "STAGE_TARGET",
    "next_action",
]
