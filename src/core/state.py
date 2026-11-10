"""唯一状态解析器（Phase 1 影子模式）。

``resolve_state(profile, store)`` 直接从 profile 字段与 ArtifactStore 解析出的
artifact 推导 14 个状态，不再调用 ``resolve_progress`` 决定状态。阶段就绪判定
统一复用 ``core.contracts.STAGE_CONTRACTS[*].ready``，本模块只负责状态顺序与
四条覆盖规则：

1. gap_stale 强制 GAP_PENDING；
2. TargetSpec 只在 ``goal_confirmed_at`` 存在时有效；
3. enterprise skip 只在没有任何企业 artifact 时允许 BASELINE → EXECUTION_READY；
4. ExecutionState 必须匹配当前 applied ExecutionPlan，旧任务不进入 EXECUTING。

本模块只读档案与 artifact，不写库、不改档案；Phase 1 不改任何现有入口。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import contracts
from .artifacts.store import ArtifactStore
from .progress import (
    STAGE_BASELINE_PLAN,
    STAGE_COMPANY_POOL,
    STAGE_EVIDENCE,
    STAGE_EXECUTION,
    STAGE_EXECUTION_PLAN,
    STAGE_GAP,
    STAGE_KEYS,
    STAGE_MARKET,
    STAGE_ORDER,
    STAGE_PROFILE,
    STAGE_REQUIREMENT,
    STAGE_TARGET,
    profile_target_fingerprint,
    resolve_artifact,
    stored_target_fingerprint,
)


class State(StrEnum):
    """14 个唯一状态；名称与 state-model.md 第 3 节一致。"""

    EMPTY = "EMPTY"
    PROFILE_COLLECTING = "PROFILE_COLLECTING"
    PROFILE_READY = "PROFILE_READY"
    MARKET_PENDING = "MARKET_PENDING"
    GAP_PENDING = "GAP_PENDING"
    BASELINE_PLAN_PENDING = "BASELINE_PLAN_PENDING"
    COMPANY_PENDING = "COMPANY_PENDING"
    EVIDENCE_PENDING = "EVIDENCE_PENDING"
    REQUIREMENT_DRAFT = "REQUIREMENT_DRAFT"
    REQUIREMENT_READY = "REQUIREMENT_READY"
    EXECUTION_PLAN_DRAFT = "EXECUTION_PLAN_DRAFT"
    EXECUTION_READY = "EXECUTION_READY"
    EXECUTING = "EXECUTING"
    MAINTENANCE = "MAINTENANCE"


@dataclass(frozen=True)
class Blocker:
    """状态阻塞事实；只陈述缺什么/过期什么，不写用户话术。"""

    code: str
    detail: str = ""
    artifact_id: str = ""


@dataclass(frozen=True)
class StateSnapshot:
    """状态快照；所有入口的唯一输入。"""

    state: State
    stage_index: int
    stage_name: str
    next_tool: str
    user_decision: str
    allowed_tools: frozenset[str]
    blockers: tuple[Blocker, ...]
    artifact_ids: dict[str, str]
    completion: dict[str, bool]
    skip_flags: dict[str, bool]


STAGE_NAMES: tuple[str, ...] = (
    "职业档案构建",
    "目标岗位定位",
    "市场基线调研",
    "能力差距诊断",
    "培养方案规划",
    "目标企业筛选",
    "岗位与面经采集",
    "企业需求分析",
    "执行方案校准",
    "任务执行与打卡",
    "求职投递管理",
    "周期复盘与计划调整",
)

_STATE_STAGE_INDEX: dict[State, int] = {
    State.EMPTY: 1,
    State.PROFILE_COLLECTING: 2,
    State.PROFILE_READY: 1,
    State.MARKET_PENDING: 3,
    State.GAP_PENDING: 4,
    State.BASELINE_PLAN_PENDING: 5,
    State.COMPANY_PENDING: 6,
    State.EVIDENCE_PENDING: 7,
    State.REQUIREMENT_DRAFT: 8,
    State.REQUIREMENT_READY: 9,
    State.EXECUTION_PLAN_DRAFT: 9,
    State.EXECUTION_READY: 10,
    State.EXECUTING: 10,
    State.MAINTENANCE: 10,
}

_STATE_USER_DECISION: dict[State, str] = {
    State.EMPTY: "给简历或一次回 4 项",
    State.PROFILE_COLLECTING: "确认方向/城市/届别",
    State.PROFILE_READY: "确认建档",
    State.MARKET_PENDING: "是否先做市场调研",
    State.GAP_PENDING: "开始差距分析",
    State.BASELINE_PLAN_PENDING: "开始规划",
    State.COMPANY_PENDING: "企业适配或先按基线执行",
    State.EVIDENCE_PENDING: "开始采集",
    State.REQUIREMENT_DRAFT: "保存企业需求解读",
    State.REQUIREMENT_READY: "开始校准",
    State.EXECUTION_PLAN_DRAFT: "确认应用执行版",
    State.EXECUTION_READY: "细化或直接生成任务",
    State.EXECUTING: "推进任务",
    State.MAINTENANCE: "投递或复盘",
}

# 只读诊断工具在所有状态都允许；其余按状态门禁。工具→状态允许关系的唯一来源。
READ_ONLY_TOOLS = frozenset(
    {
        "get_workflow_status",
        "get_progress",
        "list_profiles",
        "get_weekly_review",
        "check_plan_fit",
        "export_dashboard",
        "list_data_sources",
        "get_scraper_guide",
        "search_knowledge",
        "read_research_details",
    }
)

_ALLOWED_TOOLS: dict[State, frozenset[str]] = {
    State.EMPTY: frozenset(
        {"parse_resume", "import_jd", "import_jd_file", "intake", "start_session"}
    ),
    State.PROFILE_COLLECTING: frozenset(
        {"parse_resume", "intake", "explore_goals"}
    ),
    State.PROFILE_READY: frozenset({"finalize_profile", "intake"}),
    State.MARKET_PENDING: frozenset(
        {
            "research_market",
            "gather_research_data",
            "fetch_company_jobs",
            "search_cases",
            "fetch_jd_detail",
            "boss_login",
            "analyze_gaps",
            "save_gap_analysis",
            "import_jd",
            "import_jd_file",
        }
    ),
    State.GAP_PENDING: frozenset(
        {
            "analyze_gaps",
            "save_gap_analysis",
            "generate_roadmap",
            "save_roadmap",
            "fetch_company_jobs",
            "search_cases",
            "fetch_jd_detail",
            "read_research_details",
        }
    ),
    State.BASELINE_PLAN_PENDING: frozenset({"generate_roadmap", "save_roadmap"}),
    State.COMPANY_PENDING: frozenset(
        {
            "select_target_companies",
            "detail_current_phase",
            "generate_tasks",
            "get_next_tasks",
            "save_roadmap",
        }
    ),
    State.EVIDENCE_PENDING: frozenset(
        {"collect_company_evidence", "boss_login", "select_target_companies"}
    ),
    State.REQUIREMENT_DRAFT: frozenset(
        {"analyze_company_requirements", "save_requirement_profile"}
    ),
    State.REQUIREMENT_READY: frozenset(
        {"plan_execution_alignment", "read_research_details", "fetch_jd_detail"}
    ),
    State.EXECUTION_PLAN_DRAFT: frozenset({"save_execution_alignment"}),
    State.EXECUTION_READY: frozenset(
        {
            "detail_current_phase",
            "save_current_detail",
            "generate_tasks",
            "get_next_tasks",
            "export_dashboard",
        }
    ),
    State.EXECUTING: frozenset(
        {
            "get_next_tasks",
            "checkin_task",
            "detail_current_phase",
            "save_current_detail",
            "generate_tasks",
            "trigger_insight",
            "apply_insight",
            "build_application_list",
            "record_application",
            "check_plan_fit",
            "get_weekly_review",
            "export_dashboard",
        }
    ),
    State.MAINTENANCE: frozenset(
        {
            "build_application_list",
            "record_application",
            "check_plan_fit",
            "get_weekly_review",
            "get_next_tasks",
            "export_dashboard",
        }
    ),
}

_ENTERPRISE_STAGES: tuple[str, ...] = (
    STAGE_COMPANY_POOL,
    STAGE_EVIDENCE,
    STAGE_REQUIREMENT,
    STAGE_EXECUTION_PLAN,
)

_FINISHED_STATUSES = ("completed", "skipped")


def _allowed_for_state(state: State) -> frozenset[str]:
    return _ALLOWED_TOOLS.get(state, frozenset()) | READ_ONLY_TOOLS


def allowed_tools(snapshot: StateSnapshot) -> frozenset[str]:
    """状态决定的可调用工具集合；工具门禁只查它。"""
    return _allowed_for_state(snapshot.state)


def _guidance(profile: Any) -> dict[str, Any]:
    value = getattr(profile, "guidance", None)
    return value if isinstance(value, dict) else {}


def _skip_flag(profile: Any) -> bool:
    return bool(_guidance(profile).get("enterprise_alignment_skipped_at"))


def _profile_name(profile: Any) -> str:
    for attr in ("name", "profile_name"):
        value = getattr(profile, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    try:
        from ..tools.profile import get_active_profile_name

        return get_active_profile_name()
    except Exception:  # noqa: BLE001 - 无档案层时按空名处理
        return ""


def _has_any_section(profile: Any) -> bool:
    return bool(
        getattr(profile, "who", None)
        or getattr(profile, "have", None)
        or getattr(profile, "want", None)
        or getattr(profile, "target_jd", None)
    )


def _task_status(task: Any) -> str:
    if isinstance(task, dict):
        return str(task.get("status") or "")
    return str(getattr(task, "status", "") or "")


def _all_tasks_finished(profile: Any) -> bool:
    tasks = getattr(profile, "tasks", None) or []
    return bool(tasks) and all(
        _task_status(task) in _FINISHED_STATUSES for task in tasks
    )


def _artifact_id(artifact: dict[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    meta = artifact.get("meta")
    return str(meta.get("id") or "") if isinstance(meta, dict) else ""


def _stage_ready(stage: str, artifacts: dict[str, Any]) -> bool:
    contract = contracts.STAGE_CONTRACTS.get(stage)
    return bool(contract and contract.ready(artifacts))


def _target_stale(profile: Any, artifact: dict[str, Any]) -> bool:
    """目标指纹变化时旧 TargetSpec 失效；无指纹的旧 artifact 保持兼容。"""
    stored = stored_target_fingerprint(artifact)
    if not stored:
        return False
    current = profile_target_fingerprint(profile)
    return bool(current) and current != stored


def _has_tasks(profile: Any) -> bool:
    return bool(getattr(profile, "tasks", None) or [])


def _resolve_artifacts(
    profile: Any, store: ArtifactStore, profile_name: str
) -> dict[str, dict[str, Any] | None]:
    core_state = getattr(profile, "core_state", None)
    core_state = core_state if isinstance(core_state, dict) else {}
    return {
        stage: resolve_artifact(
            store,
            profile_name,
            stage,
            str(core_state.get(STAGE_KEYS[stage]) or ""),
        )
        for stage in STAGE_ORDER
    }


def _artifact_ids(
    artifacts: dict[str, dict[str, Any] | None],
) -> dict[str, str]:
    return {
        STAGE_KEYS[stage]: _artifact_id(artifacts.get(stage))
        for stage in STAGE_ORDER
    }


def _evidence_blockers(
    evidence: dict[str, Any] | None,
) -> list[Blocker]:
    if not isinstance(evidence, dict):
        return []
    blockers: list[Blocker] = []
    counts = evidence.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    list_only = int(counts.get("list_only_kept") or counts.get("list_only") or 0)
    if list_only:
        blockers.append(
            Blocker(
                "boss_list_only",
                f"{list_only} 条 BOSS 列表数据未补详情",
                _artifact_id(evidence),
            )
        )
    dropped = int(counts.get("dropped_city") or counts.get("unknown_city") or 0)
    if dropped:
        blockers.append(
            Blocker(
                "city_filter_dropped",
                f"{dropped} 条岗位因城市硬筛剔除或地点未知",
                _artifact_id(evidence),
            )
        )
    return blockers


def _next_tool_for(
    state: State,
    profile: Any,
    artifacts: dict[str, dict[str, Any] | None],
) -> str:
    if state == State.EMPTY:
        return "parse_resume"
    if state == State.PROFILE_COLLECTING:
        has_goal = bool(
            getattr(profile, "want", None) or getattr(profile, "target_jd", None)
        )
        return "intake(want)" if has_goal else "explore_goals"
    if state == State.PROFILE_READY:
        return "finalize_profile"
    if state == State.MARKET_PENDING:
        return "gather_research_data"
    if state == State.GAP_PENDING:
        return "analyze_gaps"
    if state == State.BASELINE_PLAN_PENDING:
        return "generate_roadmap"
    if state == State.COMPANY_PENDING:
        return "select_target_companies"
    if state == State.EVIDENCE_PENDING:
        return "collect_company_evidence"
    if state == State.REQUIREMENT_DRAFT:
        if artifacts.get(STAGE_REQUIREMENT) is None:
            return "analyze_company_requirements"
        return "save_requirement_profile"
    if state == State.REQUIREMENT_READY:
        return "plan_execution_alignment"
    if state == State.EXECUTION_PLAN_DRAFT:
        return "save_execution_alignment"
    if state == State.EXECUTION_READY:
        plan = getattr(profile, "plan", None)
        plan = plan if isinstance(plan, dict) else {}
        if plan.get("current_detail") or _has_tasks(profile):
            return "generate_tasks"
        return "detail_current_phase"
    if state == State.EXECUTING:
        return "get_next_tasks"
    return "build_application_list"


def _snapshot(
    state: State,
    profile: Any,
    artifacts: dict[str, dict[str, Any] | None],
    blockers: list[Blocker],
) -> StateSnapshot:
    stage_index = _STATE_STAGE_INDEX[state]
    artifact_ids = _artifact_ids(artifacts)
    return StateSnapshot(
        state=state,
        stage_index=stage_index,
        stage_name=STAGE_NAMES[stage_index - 1],
        next_tool=_next_tool_for(state, profile, artifacts),
        user_decision=_STATE_USER_DECISION[state],
        allowed_tools=_allowed_for_state(state),
        blockers=tuple(blockers),
        artifact_ids=artifact_ids,
        completion={
            stage: bool(artifact_ids.get(STAGE_KEYS[stage]))
            for stage in STAGE_ORDER
        },
        skip_flags={"enterprise_alignment": _skip_flag(profile)},
    )


def resolve_state(
    profile: Any, store: ArtifactStore | None = None
) -> StateSnapshot:
    """从 profile 字段与 artifact 直接推导唯一状态快照（只读）。"""
    active_store = store if store is not None else ArtifactStore()
    profile_name = _profile_name(profile)
    artifacts = _resolve_artifacts(profile, active_store, profile_name)
    blockers: list[Blocker] = _evidence_blockers(artifacts.get(STAGE_EVIDENCE))

    if not _has_any_section(profile):
        return _snapshot(State.EMPTY, profile, artifacts, blockers)

    guidance = _guidance(profile)
    goal_confirmed = bool(guidance.get("goal_confirmed_at"))

    # 覆盖规则 2：TargetSpec 只在目标已确认时有效。
    target = artifacts.get(STAGE_TARGET)
    if target is not None:
        if not goal_confirmed:
            artifacts[STAGE_TARGET] = None
            blockers.append(
                Blocker("target_unconfirmed", "目标尚未由用户确认")
            )
        elif _target_stale(profile, target):
            artifacts[STAGE_TARGET] = None
            blockers.append(
                Blocker("target_stale", "目标字段已变化，旧 TargetSpec 失效")
            )

    # 覆盖规则 1：gap_stale 强制回到差距分析，下游 plan/tasks 不得覆盖。
    if getattr(profile, "gap", None) and str(
        getattr(profile, "gap_stale_at", "") or ""
    ).strip():
        blockers.append(Blocker("gap_stale", "目标 JD 已更新，旧差距分析已过期"))
        return _snapshot(State.GAP_PENDING, profile, artifacts, blockers)

    if not goal_confirmed:
        blockers.append(Blocker("target_unconfirmed", "目标尚未由用户确认"))
        return _snapshot(State.PROFILE_COLLECTING, profile, artifacts, blockers)

    if not _stage_ready(STAGE_PROFILE, artifacts):
        return _snapshot(State.PROFILE_READY, profile, artifacts, blockers)

    if not _stage_ready(STAGE_TARGET, artifacts):
        blockers.append(Blocker("target_unconfirmed", "目标尚未写入 TargetSpec"))
        return _snapshot(State.PROFILE_COLLECTING, profile, artifacts, blockers)

    market_skipped = False
    if not _stage_ready(STAGE_MARKET, artifacts):
        # 覆盖规则：市场调研可跳过。档案已有差距/路线图/任务事实时，不再要求
        # MarketBaseline，标记跳过并继续按后续 artifact 事实判定。
        plan = getattr(profile, "plan", None)
        roadmap_exists = isinstance(plan, dict) and bool(plan.get("roadmap"))
        if getattr(profile, "gap", None) or roadmap_exists or _has_tasks(profile):
            market_skipped = True
            blockers.append(Blocker("market_skipped", "用户选择跳过市场调研"))
        else:
            blockers.append(Blocker("artifact_missing", "尚未生成 MarketBaseline"))
            return _snapshot(State.MARKET_PENDING, profile, artifacts, blockers)

    # 市场跳过时 Gap/Baseline artifact 可能缺 MarketBaseline 上游引用；用户已有
    # roadmap 即视为规划完成，允许继续执行（对应 GAP_PENDING 放行规划工具）。
    plan = getattr(profile, "plan", None)
    roadmap_exists = isinstance(plan, dict) and bool(plan.get("roadmap"))
    gap_ready = _stage_ready(STAGE_GAP, artifacts)
    if not gap_ready and market_skipped and roadmap_exists:
        gap_ready = True
    if not gap_ready:
        blockers.append(Blocker("artifact_missing", "尚未生成 GapReport"))
        return _snapshot(State.GAP_PENDING, profile, artifacts, blockers)

    baseline_ready = _stage_ready(STAGE_BASELINE_PLAN, artifacts)
    if not baseline_ready and market_skipped and roadmap_exists:
        baseline_ready = True
    if not baseline_ready:
        blockers.append(Blocker("artifact_missing", "尚未生成 BaselinePlan"))
        return _snapshot(State.BASELINE_PLAN_PENDING, profile, artifacts, blockers)

    # 覆盖规则 3：企业链未补齐且用户已记录跳过时，允许直接进入执行准备；
    # 一旦出现 CompanyPool/Evidence/Requirement/ExecutionPlan，恢复企业链路。
    enterprise_present = any(
        artifacts.get(stage) for stage in _ENTERPRISE_STAGES
    )
    if _skip_flag(profile) and not enterprise_present:
        blockers.append(
            Blocker("enterprise_alignment_skipped", "企业适配已记录跳过")
        )
        # 基线执行路径没有 applied ExecutionPlan：有任务即进入执行态，
        # 否则停留在执行准备，允许 detail_current_phase → save_current_detail。
        if _has_tasks(profile):
            return _snapshot(State.EXECUTING, profile, artifacts, blockers)
        return _snapshot(State.EXECUTION_READY, profile, artifacts, blockers)

    if not _stage_ready(STAGE_COMPANY_POOL, artifacts):
        pool = artifacts.get(STAGE_COMPANY_POOL)
        if isinstance(pool, dict):
            blockers.append(
                Blocker(
                    "company_pool_unconfirmed",
                    "CompanyPool 尚未确认",
                    _artifact_id(pool),
                )
            )
        else:
            blockers.append(Blocker("artifact_missing", "尚未生成 CompanyPool"))
        return _snapshot(State.COMPANY_PENDING, profile, artifacts, blockers)

    if not _stage_ready(STAGE_EVIDENCE, artifacts):
        blockers.append(
            Blocker("artifact_missing", "缺少与当前 CompanyPool 匹配的 EvidenceRun")
        )
        return _snapshot(State.EVIDENCE_PENDING, profile, artifacts, blockers)

    if not _stage_ready(STAGE_REQUIREMENT, artifacts):
        requirement = artifacts.get(STAGE_REQUIREMENT)
        blockers.append(
            Blocker(
                "requirement_draft",
                "需求画像未生成或仍是未解读草稿",
                _artifact_id(requirement),
            )
        )
        return _snapshot(State.REQUIREMENT_DRAFT, profile, artifacts, blockers)

    plan = artifacts.get(STAGE_EXECUTION_PLAN)
    if plan is None:
        blockers.append(Blocker("artifact_missing", "尚未生成 ExecutionPlan"))
        return _snapshot(State.REQUIREMENT_READY, profile, artifacts, blockers)
    if not bool(plan.get("applied")):
        blockers.append(
            Blocker("execution_plan_not_applied", "ExecutionPlan 已生成但未应用")
        )
        return _snapshot(State.EXECUTION_PLAN_DRAFT, profile, artifacts, blockers)
    if not _stage_ready(STAGE_EXECUTION_PLAN, artifacts):
        blockers.append(
            Blocker("execution_plan_invalid", "ExecutionPlan 上游引用不一致，需要重新校准")
        )
        return _snapshot(State.REQUIREMENT_READY, profile, artifacts, blockers)

    # 覆盖规则 4：ExecutionState 必须匹配当前 applied ExecutionPlan。
    if not _stage_ready(STAGE_EXECUTION, artifacts):
        execution = artifacts.get(STAGE_EXECUTION)
        if isinstance(execution, dict):
            blockers.append(
                Blocker(
                    "execution_state_stale",
                    "ExecutionState 不属于当前 applied ExecutionPlan",
                    _artifact_id(execution),
                )
            )
        else:
            blockers.append(Blocker("execution_state_missing", "尚未生成执行状态"))
        return _snapshot(State.EXECUTION_READY, profile, artifacts, blockers)

    if _all_tasks_finished(profile):
        return _snapshot(State.MAINTENANCE, profile, artifacts, blockers)
    return _snapshot(State.EXECUTING, profile, artifacts, blockers)


__all__ = [
    "Blocker",
    "READ_ONLY_TOOLS",
    "STAGE_NAMES",
    "State",
    "StateSnapshot",
    "allowed_tools",
    "resolve_state",
]
