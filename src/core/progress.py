"""共享进度解析——artifact 引用链 + 旧档案兜底（只读）。

状态机与用户引导都从这里取「当前阶段」，避免一个只看 ``core_state`` key、
另一个看 artifact 引用链，导致同一份档案出现两个位置。

纪律：
- 只读档案与 artifact，不写库、不改档案；
- 下游 artifact 必须引用上游 artifact id；
- artifact 的 ``meta.profile_name`` 必须与当前档案一致，跨档案引用一律拒绝；
- 阶段 11/12（投递、复盘）是可选阶段，不参与阶段推进，也不阻塞阶段 10。
"""

from __future__ import annotations

from typing import Any

from .artifacts.store import ArtifactStore

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

STAGE_ORDER: tuple[str, ...] = (
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

STAGE_KEYS: dict[str, str] = {
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

ARTIFACT_KEYS: tuple[str, ...] = tuple(STAGE_KEYS[stage] for stage in STAGE_ORDER)

# 必选阶段：决定用户下一步；投递/复盘是可选项，不推进 stage。
REQUIRED_STAGES: tuple[str, ...] = STAGE_ORDER[:10]
OPTIONAL_STAGES: tuple[str, ...] = (STAGE_APPLICATIONS, STAGE_REVIEW)

# 阶段 1-5 允许旧档案兜底（没有 artifact 时按已有 section 判断）。
_CORE_PREFIX_STAGES: tuple[str, ...] = (
    STAGE_PROFILE,
    STAGE_TARGET,
    STAGE_MARKET,
    STAGE_GAP,
    STAGE_BASELINE_PLAN,
)

_OPTIONAL_EXECUTION_TOOLS = [
    "build_application_list",
    "record_application",
    "check_plan_fit",
    "get_weekly_review",
]


def resolve_progress(
    profile: Any,
    store: ArtifactStore | None = None,
    profile_name: str = "",
) -> dict[str, Any]:
    """解析当前进度：阶段、下一步工具、artifact ids 与旧档案兜底标记。"""
    store = store if store is not None else ArtifactStore()
    core_state = _core_state(profile)
    if not profile_name:
        profile_name = _active_profile_name()

    resolved: dict[str, dict[str, Any] | None] = {}
    for stage in STAGE_ORDER:
        artifact_id = str(core_state.get(STAGE_KEYS[stage]) or "")
        resolved[stage] = resolve_artifact(store, profile_name, stage, artifact_id)

    artifact_ids: dict[str, str] = dict.fromkeys(ARTIFACT_KEYS, "")
    has_required_artifact = any(
        resolved[stage] is not None for stage in REQUIRED_STAGES
    )
    legacy = legacy_flags(profile)

    for stage in _CORE_PREFIX_STAGES:
        artifact = resolved[stage]
        if artifact is not None:
            artifact_ids[STAGE_KEYS[stage]] = _artifact_id(artifact)
            continue
        if downstream_exists(resolved, stage):
            continue
        if not has_required_artifact and legacy_stage_done(profile, stage):
            continue
        return _result(
            stage,
            _core_stage_tool(profile, stage),
            _core_stage_reason(profile, stage),
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )

    pool = resolved[STAGE_COMPANY_POOL]
    if pool is None:
        return _result(
            STAGE_COMPANY_POOL,
            "select_target_companies",
            "尚未生成 CompanyPool",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )
    artifact_ids[STAGE_KEYS[STAGE_COMPANY_POOL]] = _artifact_id(pool)
    if not _confirmed(pool):
        return _result(
            STAGE_COMPANY_POOL,
            "select_target_companies",
            "CompanyPool 尚未确认",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )

    evidence = resolved[STAGE_EVIDENCE]
    if evidence is None or not _references(
        evidence, "company_pool_id", artifact_ids[STAGE_KEYS[STAGE_COMPANY_POOL]]
    ):
        return _result(
            STAGE_EVIDENCE,
            "collect_company_evidence",
            "缺少与当前 CompanyPool 匹配的 EvidenceRun",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )
    artifact_ids[STAGE_KEYS[STAGE_EVIDENCE]] = _artifact_id(evidence)

    requirement = resolved[STAGE_REQUIREMENT]
    if requirement is None or not _references(
        requirement, "evidence_run_id", artifact_ids[STAGE_KEYS[STAGE_EVIDENCE]]
    ):
        return _result(
            STAGE_REQUIREMENT,
            "analyze_company_requirements",
            "缺少与当前 EvidenceRun 匹配的 RequirementProfile",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )
    artifact_ids[STAGE_KEYS[STAGE_REQUIREMENT]] = _artifact_id(requirement)

    plan = resolved[STAGE_EXECUTION_PLAN]
    if plan is None or not _references(
        plan, "requirement_profile_id", artifact_ids[STAGE_KEYS[STAGE_REQUIREMENT]]
    ):
        return _result(
            STAGE_EXECUTION_PLAN,
            "plan_execution_alignment",
            "缺少与当前 RequirementProfile 匹配的 ExecutionPlan",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )
    artifact_ids[STAGE_KEYS[STAGE_EXECUTION_PLAN]] = _artifact_id(plan)

    if not bool(plan.get("applied")):
        return _result(
            STAGE_EXECUTION_PLAN,
            "save_execution_alignment",
            "ExecutionPlan 已生成但未应用",
            artifact_ids,
            legacy=legacy,
            has_tasks=_has_tasks(profile),
        )

    execution = resolved[STAGE_EXECUTION]
    if execution is not None and _references(
        execution, "execution_plan_id", artifact_ids[STAGE_KEYS[STAGE_EXECUTION_PLAN]]
    ):
        artifact_ids[STAGE_KEYS[STAGE_EXECUTION]] = _artifact_id(execution)
        return _result(
            STAGE_EXECUTING,
            "get_next_tasks",
            "执行状态已就绪，按当前阶段任务推进",
            artifact_ids,
            applied=True,
            has_execution_state=True,
            has_tasks=_has_tasks(profile),
            legacy=legacy,
        )

    if _has_tasks(profile):
        return _result(
            STAGE_EXECUTING,
            "get_next_tasks",
            "档案已有任务，按当前阶段任务推进",
            artifact_ids,
            applied=True,
            has_tasks=True,
            legacy=legacy,
        )

    return _result(
        STAGE_EXECUTION,
        "generate_tasks",
        "ExecutionPlan 已应用，尚未生成任务与执行状态",
        artifact_ids,
        applied=True,
        has_tasks=_has_tasks(profile),
        legacy=legacy,
    )


def resolve_artifact(
    store: ArtifactStore,
    profile_name: str,
    stage: str,
    artifact_id: str = "",
) -> dict[str, Any] | None:
    """优先按 core_state 的 id 解析，缺失时回退该档案该阶段 latest。"""
    if artifact_id:
        data = store.load(artifact_id)
        if _matches_stage(data, stage, profile_name):
            return data
    if not profile_name:
        return None
    data = store.latest(profile_name, stage)
    return data if _matches_stage(data, stage, profile_name) else None


def legacy_flags(profile: Any) -> dict[str, bool]:
    """旧档案兜底标记：只读已有 section，不要求 artifact。"""
    plan = getattr(profile, "plan", None) or {}
    research = getattr(profile, "research", None) or {}
    want = getattr(profile, "want", None) or {}
    tasks = getattr(profile, "tasks", None) or []
    applications = getattr(profile, "applications", None) or []
    has_plan = isinstance(plan, dict) and bool(plan.get("roadmap"))
    has_gap = bool(getattr(profile, "gap", None))
    has_research = isinstance(research, dict) and bool(
        research.get("report_md") or research.get("jd_samples") or research.get("cases")
    )
    return {
        "profile": bool(
            getattr(profile, "summary", "")
            or getattr(profile, "who", None)
            or getattr(profile, "have", None)
        ),
        "target": isinstance(want, dict) and bool(want),
        "research": has_research,
        "gap": has_gap,
        "plan": has_plan,
        "tasks": bool(tasks),
        "applications": bool(applications),
    }


def legacy_stage_done(profile: Any, stage: str) -> bool:
    """旧档案没有 artifact 时，用已有 section 推断阶段完成。"""
    flags = legacy_flags(profile)
    downstream = (
        flags["research"] or flags["gap"] or flags["plan"] or flags["tasks"]
    )
    done = {
        STAGE_PROFILE: flags["profile"] or downstream,
        STAGE_TARGET: flags["target"] or downstream,
        STAGE_MARKET: downstream,
        STAGE_GAP: flags["gap"] or flags["plan"] or flags["tasks"],
        STAGE_BASELINE_PLAN: flags["plan"] or flags["tasks"],
        STAGE_EXECUTION: flags["tasks"],
    }
    return bool(done.get(stage, False))


def downstream_exists(
    resolved: dict[str, dict[str, Any] | None], stage: str
) -> bool:
    """只检查必选下游；可选阶段（投递/复盘）不跳过前面的阶段。"""
    index = STAGE_ORDER.index(stage)
    return any(
        resolved[later] is not None
        for later in STAGE_ORDER[index + 1 :]
        if later in REQUIRED_STAGES
    )


def _core_stage_tool(profile: Any, stage: str) -> str:
    if stage == STAGE_PROFILE:
        return "finalize_profile"
    if stage == STAGE_TARGET:
        return "intake(want)" if _has_want(profile) else "explore_goals"
    if stage == STAGE_MARKET:
        return "gather_research_data"
    if stage == STAGE_GAP:
        return "analyze_gaps"
    return "generate_roadmap"


def _core_stage_reason(profile: Any, stage: str) -> str:
    if stage == STAGE_PROFILE:
        return "尚未建立 ProfileSnapshot"
    if stage == STAGE_TARGET:
        if _has_want(profile):
            return "目标已存在但尚未写入 TargetSpec"
        return "尚未确定目标岗位"
    if stage == STAGE_MARKET:
        return "尚未生成 MarketBaseline"
    if stage == STAGE_GAP:
        return "尚未生成 GapReport"
    return "尚未生成 BaselinePlan"


def _result(
    stage: str,
    next_tool: str,
    reason: str,
    artifact_ids: dict[str, str],
    *,
    applied: bool = False,
    has_execution_state: bool = False,
    has_tasks: bool = False,
    legacy: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "next_tool": next_tool,
        "reason": reason,
        "artifact_ids": dict(artifact_ids),
        "optional_next_tools": (
            list(_OPTIONAL_EXECUTION_TOOLS) if stage == STAGE_EXECUTING else []
        ),
        "applied": applied,
        "has_execution_state": has_execution_state,
        "has_tasks": has_tasks,
        "legacy": dict(legacy or {}),
    }


def _matches_stage(
    data: dict[str, Any] | None, stage: str, profile_name: str
) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("stage") != stage:
        return False
    return str(meta.get("profile_name") or "") == profile_name


def _references(artifact: dict[str, Any], field: str, expected_id: str) -> bool:
    """下游必须引用上游；expected 非空而 actual 为空视为不通过。"""
    if not expected_id:
        return True
    actual = str(artifact.get(field) or "")
    return bool(actual) and actual == expected_id


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
    return any(
        isinstance(item, dict) and item.get("status") == "confirmed"
        for item in companies
    )


def _core_state(profile: Any) -> dict[str, Any]:
    value = getattr(profile, "core_state", None)
    return value if isinstance(value, dict) else {}


def _has_want(profile: Any) -> bool:
    want = getattr(profile, "want", None) or {}
    return isinstance(want, dict) and bool(want)


def _has_tasks(profile: Any) -> bool:
    return bool(getattr(profile, "tasks", None) or [])


def _active_profile_name() -> str:
    """延迟导入，避免 guidance 在模块加载期依赖 tool 层。"""
    try:
        from ..tools.profile import get_active_profile_name

        return get_active_profile_name()
    except Exception:  # noqa: BLE001 - 无档案层时按空名处理
        return ""


__all__ = [
    "ARTIFACT_KEYS",
    "OPTIONAL_STAGES",
    "REQUIRED_STAGES",
    "STAGE_APPLICATIONS",
    "STAGE_BASELINE_PLAN",
    "STAGE_COMPANY_POOL",
    "STAGE_EVIDENCE",
    "STAGE_EXECUTING",
    "STAGE_EXECUTION",
    "STAGE_EXECUTION_PLAN",
    "STAGE_GAP",
    "STAGE_KEYS",
    "STAGE_MARKET",
    "STAGE_ORDER",
    "STAGE_PROFILE",
    "STAGE_REQUIREMENT",
    "STAGE_REVIEW",
    "STAGE_TARGET",
    "downstream_exists",
    "legacy_flags",
    "legacy_stage_done",
    "resolve_artifact",
    "resolve_progress",
]
