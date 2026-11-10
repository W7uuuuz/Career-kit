"""共享进度解析——artifact 引用链（只读）。

状态机与用户引导都从这里取「当前阶段」，避免一个只看 ``core_state`` key、
另一个看 artifact 引用链，导致同一份档案出现两个位置。

纪律：
- 只读档案与 artifact，不写库、不改档案；
- 下游 artifact 必须引用上游 artifact id；
- artifact 的 ``meta.profile_name`` 必须与当前档案一致，跨档案引用一律拒绝；
- 阶段 11/12（投递、复盘）是可选阶段，不参与阶段推进，也不阻塞阶段 10。
"""

from __future__ import annotations

import hashlib
import json
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

# 各阶段（2-10）的必需上游引用矩阵：stage -> (上游 stage, 字段名, 字段位置)。
# 字段位置为 "body"（artifact 顶层字段）或 "inputs"（meta.inputs）。
_UPSTREAM_REFS: dict[str, tuple[tuple[str, str, str], ...]] = {
    STAGE_TARGET: ((STAGE_PROFILE, "profile_id", "inputs"),),
    STAGE_MARKET: ((STAGE_TARGET, "target_spec_id", "inputs"),),
    STAGE_GAP: (
        (STAGE_PROFILE, "profile_snapshot_id", "body"),
        (STAGE_MARKET, "market_baseline_id", "body"),
    ),
    STAGE_BASELINE_PLAN: ((STAGE_GAP, "gap_report_id", "body"),),
    STAGE_COMPANY_POOL: ((STAGE_BASELINE_PLAN, "baseline_plan_id", "inputs"),),
    STAGE_EVIDENCE: ((STAGE_COMPANY_POOL, "company_pool_id", "body"),),
    STAGE_REQUIREMENT: ((STAGE_EVIDENCE, "evidence_run_id", "body"),),
    STAGE_EXECUTION_PLAN: (
        (STAGE_REQUIREMENT, "requirement_profile_id", "body"),
        (STAGE_BASELINE_PLAN, "baseline_plan_id", "body"),
    ),
    STAGE_EXECUTION: ((STAGE_EXECUTION_PLAN, "execution_plan_id", "body"),),
}

_OPTIONAL_EXECUTION_TOOLS = [
    "build_application_list",
    "record_application",
    "check_plan_fit",
    "get_weekly_review",
]

# TargetSpec 指纹字段：只包含目标身份字段。expected_outcome（求职结果预期）、
# scan 元数据等补充信息不在其中，写它们不得让旧 TargetSpec 失效。
TARGET_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "direction",
    "role",
    "city",
    "target_tiers",
    "bridge_tiers",
    "graduation_year",
    "constraints",
)
TARGET_FINGERPRINT_KEY = "target_fingerprint"


def resolve_progress(
    profile: Any,
    store: ArtifactStore | None = None,
    profile_name: str = "",
) -> dict[str, Any]:
    """解析当前进度：阶段、下一步工具与 artifact ids。"""
    store = store if store is not None else ArtifactStore()
    core_state = _core_state(profile)
    if not profile_name:
        profile_name = _active_profile_name()

    resolved: dict[str, dict[str, Any] | None] = {}
    for stage in STAGE_ORDER:
        artifact_id = str(core_state.get(STAGE_KEYS[stage]) or "")
        resolved[stage] = resolve_artifact(store, profile_name, stage, artifact_id)

    artifact_ids: dict[str, str] = dict.fromkeys(ARTIFACT_KEYS, "")
    has_tasks = _has_tasks(profile)

    # 目标确认是 TargetSpec 的唯一门禁：未由用户确认，或 want 在 TargetSpec
    # 之后被改写时，旧 TargetSpec 不能再推进链路（回到目标阶段）。
    target_artifact = resolved[STAGE_TARGET]
    if target_artifact is not None and (
        not _goal_confirmed(profile) or _target_stale(profile, target_artifact)
    ):
        resolved[STAGE_TARGET] = None

    # 目标 JD 更新后旧差距分析过期：必须强制回到差距阶段，下游 tasks/plan 不得覆盖。
    if getattr(profile, "gap", None) and str(
        getattr(profile, "gap_stale_at", "") or ""
    ).strip():
        resolved_ids = {
            STAGE_KEYS[stage]: _artifact_id(resolved[stage]) for stage in STAGE_ORDER
        }
        return _result(
            STAGE_GAP,
            "analyze_gaps",
            "目标 JD 已更新，旧差距分析已过期，必须先重新分析",
            resolved_ids,
            has_tasks=has_tasks,
        )

    # 用户选择「先按基线执行」并已记录跳过事实时，基线任务不再被企业适配链路
    # （CompanyPool/Evidence/Requirement/ExecutionPlan）卡住；已应用的执行版仍走
    # 原有代际校验，避免绕过 6C 的 ExecutionState 匹配规则。
    baseline = _baseline_execution_result(profile, resolved, has_tasks=has_tasks)
    if baseline is not None:
        return baseline

    # import_plan 路径：无 GapReport 且尚未落 BaselinePlan 时，下一步是 save_roadmap。
    imported_baseline = resolved.get(STAGE_BASELINE_PLAN)
    if (
        _plan_imported(profile)
        and resolved.get(STAGE_GAP) is None
        and not _is_imported_baseline(imported_baseline)
    ):
        return _result(
            STAGE_BASELINE_PLAN,
            "generate_roadmap",
            "已导入计划文档，等待 save_roadmap 保存结构化路线图",
            artifact_ids,
            has_tasks=has_tasks,
        )

    imported_mode = (
        _plan_imported(profile)
        and _is_imported_baseline(imported_baseline)
        and _target_matches_artifact(imported_baseline, resolved)
    )
    if imported_mode:
        artifact_ids[STAGE_KEYS[STAGE_BASELINE_PLAN]] = _artifact_id(
            imported_baseline
        )
    else:
        # 阶段 1：档案快照。没有 ProfileSnapshot 时必须停在 finalize，即使
        # TargetSpec 已由 intake(want, user_confirmed=true) 同步存在。
        profile_artifact = resolved[STAGE_PROFILE]
        if profile_artifact is not None:
            artifact_ids[STAGE_KEYS[STAGE_PROFILE]] = _artifact_id(profile_artifact)
        else:
            early = _profile_stage_result(profile, artifact_ids, has_tasks=has_tasks)
            if early is not None:
                return early

        # 阶段 2-5：缺 artifact 不得因为下游 artifact 存在而跳过；
        # 已有 artifact 必须引用上游 id，空引用视为不满足。
        # 市场跳过时 MarketBaseline 缺失，但当前 TargetSpec 匹配的 market_skipped
        # GapReport 允许直接进入差距/规划阶段。
        market_skipped = False
        for stage in (STAGE_TARGET, STAGE_MARKET, STAGE_GAP, STAGE_BASELINE_PLAN):
            artifact = resolved[stage]
            if stage == STAGE_MARKET and _market_skipped_gap(
                resolved.get(STAGE_GAP),
                artifact_ids.get(STAGE_KEYS[STAGE_TARGET], ""),
            ):
                market_skipped = True
                continue
            if artifact is None:
                return _result(
                    stage,
                    _core_stage_tool(profile, stage),
                    _core_stage_reason(profile, stage),
                    artifact_ids,
                    has_tasks=has_tasks,
                )
            problems = _upstream_problems(stage, artifact, artifact_ids)
            if problems:
                return _result(
                    stage,
                    _core_stage_tool(profile, stage),
                    "；".join(problems),
                    artifact_ids,
                    has_tasks=has_tasks,
                )
            artifact_ids[STAGE_KEYS[stage]] = _artifact_id(artifact)
        if market_skipped:
            # 标记已跳过市场调研：不阻塞后续，但保持事实可见。
            artifact_ids.setdefault(STAGE_KEYS[STAGE_MARKET], "")

    pool = resolved[STAGE_COMPANY_POOL]
    if pool is None:
        return _result(
            STAGE_COMPANY_POOL,
            "select_target_companies",
            "尚未生成 CompanyPool",
            artifact_ids,
            has_tasks=has_tasks,
        )
    problems = _upstream_problems(STAGE_COMPANY_POOL, pool, artifact_ids)
    if problems:
        return _result(
            STAGE_COMPANY_POOL,
            "select_target_companies",
            "；".join(problems),
            artifact_ids,
            has_tasks=has_tasks,
        )
    artifact_ids[STAGE_KEYS[STAGE_COMPANY_POOL]] = _artifact_id(pool)
    if not _confirmed(pool):
        return _result(
            STAGE_COMPANY_POOL,
            "select_target_companies",
            "CompanyPool 尚未确认",
            artifact_ids,
            has_tasks=has_tasks,
        )

    evidence = resolved[STAGE_EVIDENCE]
    if evidence is None:
        return _result(
            STAGE_EVIDENCE,
            "collect_company_evidence",
            "缺少与当前 CompanyPool 匹配的 EvidenceRun",
            artifact_ids,
            has_tasks=has_tasks,
        )
    problems = _upstream_problems(STAGE_EVIDENCE, evidence, artifact_ids)
    if problems:
        return _result(
            STAGE_EVIDENCE,
            "collect_company_evidence",
            "；".join(problems),
            artifact_ids,
            has_tasks=has_tasks,
        )
    artifact_ids[STAGE_KEYS[STAGE_EVIDENCE]] = _artifact_id(evidence)

    requirement = resolved[STAGE_REQUIREMENT]
    if requirement is None:
        return _result(
            STAGE_REQUIREMENT,
            "analyze_company_requirements",
            "缺少与当前 EvidenceRun 匹配的 RequirementProfile",
            artifact_ids,
            has_tasks=has_tasks,
        )
    problems = _upstream_problems(STAGE_REQUIREMENT, requirement, artifact_ids)
    if problems:
        return _result(
            STAGE_REQUIREMENT,
            "analyze_company_requirements",
            "；".join(problems),
            artifact_ids,
            has_tasks=has_tasks,
        )
    artifact_ids[STAGE_KEYS[STAGE_REQUIREMENT]] = _artifact_id(requirement)

    # 阶段 8 门禁：analyze 只落草稿，必须 save_requirement_profile 或已有非空
    # interpretation 才允许进入阶段 9。手工/旧 artifact 不带 draft 标记时保持兼容。
    if not _requirement_ready(requirement):
        return _result(
            STAGE_REQUIREMENT,
            "save_requirement_profile",
            "需求画像仍是未解读草稿，先调用 save_requirement_profile 写入 interpretation",
            artifact_ids,
            has_tasks=has_tasks,
        )

    plan = resolved[STAGE_EXECUTION_PLAN]
    if plan is None:
        return _result(
            STAGE_EXECUTION_PLAN,
            "plan_execution_alignment",
            "缺少与当前 RequirementProfile 匹配的 ExecutionPlan",
            artifact_ids,
            has_tasks=has_tasks,
        )
    problems = _upstream_problems(
        STAGE_EXECUTION_PLAN,
        plan,
        artifact_ids,
        strict_baseline=_is_tracked_plan(plan),
    )
    if problems:
        return _result(
            STAGE_EXECUTION_PLAN,
            "plan_execution_alignment",
            "；".join(problems),
            artifact_ids,
            has_tasks=has_tasks,
        )
    artifact_ids[STAGE_KEYS[STAGE_EXECUTION_PLAN]] = _artifact_id(plan)

    if not bool(plan.get("applied")):
        return _result(
            STAGE_EXECUTION_PLAN,
            "save_execution_alignment",
            "ExecutionPlan 已生成但未应用",
            artifact_ids,
            has_tasks=has_tasks,
        )

    # 只有与当前 applied ExecutionPlan 匹配的 ExecutionState 才算执行态就绪；
    # 旧计划留下的任务不能直接把新计划推进到 executing/get_next_tasks。
    execution = resolved[STAGE_EXECUTION]
    if execution is not None:
        problems = _upstream_problems(STAGE_EXECUTION, execution, artifact_ids)
        if not problems:
            artifact_ids[STAGE_KEYS[STAGE_EXECUTION]] = _artifact_id(execution)
            return _result(
                STAGE_EXECUTING,
                "get_next_tasks",
                "执行状态已就绪，按当前阶段任务推进",
                artifact_ids,
                applied=True,
                has_execution_state=True,
                has_tasks=has_tasks,
            )

    reason = (
        "已有任务属于旧执行方案，需按当前 ExecutionPlan 重新生成任务"
        if has_tasks
        else "ExecutionPlan 已应用，尚未生成任务与执行状态"
    )
    return _result(
        STAGE_EXECUTION,
        "generate_tasks",
        reason,
        artifact_ids,
        applied=True,
        has_tasks=has_tasks,
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


def _profile_stage_result(
    profile: Any,
    artifact_ids: dict[str, str],
    *,
    has_tasks: bool,
) -> dict[str, Any] | None:
    """阶段 1 缺失 artifact 时的分流：采集卡 / 目标确认 / finalize。

    返回 None 表示可以继续向后解析。
    """
    # 空档案还没有任何可采集内容：先走采集卡，而不是让用户 finalize 空档案。
    if not _has_any_section(profile):
        return _result(
            STAGE_PROFILE,
            "intake(section='bundle')",
            "尚无档案内容，先采集基本信息",
            artifact_ids,
            has_tasks=has_tasks,
        )
    # 目标未由用户确认时停在目标阶段；已有目标字段则请用户确认，
    # 完全没有目标则先探索方向。
    if not _goal_confirmed(profile):
        if _has_want(profile) or bool(getattr(profile, "target_jd", None)):
            return _result(
                STAGE_TARGET,
                "intake(want)",
                "目标已存在但尚未由用户确认",
                artifact_ids,
                has_tasks=has_tasks,
            )
        return _result(
            STAGE_TARGET,
            "explore_goals",
            "尚未确定目标岗位",
            artifact_ids,
            has_tasks=has_tasks,
        )
    return _result(
        STAGE_PROFILE,
        "finalize_profile",
        "尚未建立 ProfileSnapshot",
        artifact_ids,
        has_tasks=has_tasks,
    )


def _artifact_field(artifact: dict[str, Any], field: str, where: str) -> str:
    if where == "inputs":
        meta = artifact.get("meta")
        inputs = meta.get("inputs") if isinstance(meta, dict) else None
        value = inputs.get(field) if isinstance(inputs, dict) else ""
    else:
        value = artifact.get(field)
    return str(value or "").strip()


def _artifact_validation(artifact: dict[str, Any] | None) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact, dict) else None
    validation = meta.get("validation") if isinstance(meta, dict) else None
    return validation if isinstance(validation, dict) else {}


def _artifact_inputs(artifact: dict[str, Any] | None) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact, dict) else None
    inputs = meta.get("inputs") if isinstance(meta, dict) else None
    return inputs if isinstance(inputs, dict) else {}


def _artifact_target_id(artifact: dict[str, Any] | None) -> str:
    return str(_artifact_inputs(artifact).get("target_spec_id") or "").strip()


def _is_imported_baseline(artifact: dict[str, Any] | None) -> bool:
    return _artifact_validation(artifact).get("imported") is True


def _target_matches_artifact(
    artifact: dict[str, Any] | None,
    resolved: dict[str, dict[str, Any] | None],
) -> bool:
    """imported BaselinePlan 的 target_spec_id 必须与当前 TargetSpec 一致。"""
    stored = _artifact_target_id(artifact)
    current = _artifact_id(resolved.get(STAGE_TARGET))
    if not stored:
        return not current
    return stored == current


def _plan_imported(profile: Any) -> bool:
    guidance = getattr(profile, "guidance", None)
    return bool(isinstance(guidance, dict) and guidance.get("plan_imported_at"))


def _market_skipped_gap(
    artifact: dict[str, Any] | None, target_id: str
) -> bool:
    """市场跳过 GapReport 必须带 validation 标记且指向当前 TargetSpec。"""
    if not isinstance(artifact, dict):
        return False
    if _artifact_validation(artifact).get("market_skipped") is not True:
        return False
    stored = _artifact_target_id(artifact)
    return bool(target_id) and stored == target_id


def _upstream_problems(
    stage: str,
    artifact: dict[str, Any],
    artifact_ids: dict[str, str],
    *,
    strict_baseline: bool = True,
) -> list[str]:
    """校验阶段 2-10 的上游引用；空上游 id 与不一致都视为不满足。

    ``strict_baseline=False`` 用于接口契约升级前生成、没有 validation 元信息的
    ExecutionPlan：允许它缺少 baseline_plan_id，其余上游仍强校验。
    """
    problems: list[str] = []
    validation = _artifact_validation(artifact)
    stored_target = _artifact_target_id(artifact)
    if stored_target:
        expected_target = artifact_ids.get(STAGE_KEYS[STAGE_TARGET], "")
        if stored_target != expected_target:
            problems.append(
                f"{stage} 的 target_spec_id（target）与当前 TargetSpec 不一致"
            )
    if stage == STAGE_BASELINE_PLAN and validation.get("imported") is True:
        return problems
    market_skipped = validation.get("market_skipped") is True
    for upstream_stage, field, where in _UPSTREAM_REFS.get(stage, ()):
        if upstream_stage == STAGE_MARKET and market_skipped:
            continue
        expected = artifact_ids.get(STAGE_KEYS[upstream_stage], "")
        actual = _artifact_field(artifact, field, where)
        if (
            upstream_stage == STAGE_BASELINE_PLAN
            and not strict_baseline
            and not actual
        ):
            continue
        upstream_label = f"{field}（{upstream_stage}）"
        if not expected:
            problems.append(f"缺少上游 {upstream_label}，不能推进")
        elif not actual:
            problems.append(f"{stage} 缺少 {upstream_label} 引用")
        elif actual != expected:
            problems.append(f"{stage} 的 {upstream_label} 与当前上游不一致")
    return problems


def _is_tracked_plan(plan: dict[str, Any]) -> bool:
    """是否由当前 save 路径生成（带 validation）；旧 artifact 无元信息时豁免新字段。"""
    meta = plan.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    return isinstance(validation, dict) and bool(validation)


def _has_interpretation(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for item in value.values():
        if isinstance(item, str) and item.strip():
            return True
        if isinstance(item, (list, tuple, dict)) and item:
            return True
    return False


def _requirement_ready(requirement: dict[str, Any]) -> bool:
    """D5：saved 或非空 interpretation 任一成立；两者都无则未就绪。

    saved = ``validation`` 是非空 dict 且 ``status != "draft"``；
    validation 缺失/空 dict 且 interpretation 为空 → 未就绪，与 contracts 一致。
    """
    if _has_interpretation(requirement.get("interpretation")):
        return True
    meta = requirement.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    if not isinstance(validation, dict) or not validation:
        return False
    return str(validation.get("status") or "") != "draft"


def _result(
    stage: str,
    next_tool: str,
    reason: str,
    artifact_ids: dict[str, str],
    *,
    applied: bool = False,
    has_execution_state: bool = False,
    has_tasks: bool = False,
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


def _has_any_section(profile: Any) -> bool:
    """是否已有任何可采集内容；空档案应先走采集卡。"""
    return bool(
        getattr(profile, "who", None)
        or getattr(profile, "have", None)
        or getattr(profile, "want", None)
        or getattr(profile, "target_jd", None)
    )


def _goal_confirmed(profile: Any) -> bool:
    """目标是否由用户确认。

    延迟到本地读取 guidance，避免 progress 反向 import guidance 造成循环依赖。
    """
    guidance = getattr(profile, "guidance", None)
    return bool(isinstance(guidance, dict) and guidance.get("goal_confirmed_at"))


def _has_want(profile: Any) -> bool:
    want = getattr(profile, "want", None) or {}
    return isinstance(want, dict) and bool(want)


def _baseline_execution_result(
    profile: Any,
    resolved: dict[str, dict[str, Any] | None],
    *,
    has_tasks: bool,
) -> dict[str, Any] | None:
    """「先按基线执行」记录存在时，优先返回执行阶段（不越过已应用的执行版）。"""
    guidance = getattr(profile, "guidance", None)
    if not isinstance(guidance, dict) or not guidance.get(
        "enterprise_alignment_skipped_at"
    ):
        return None
    plan = getattr(profile, "plan", None)
    if not (isinstance(plan, dict) and plan.get("roadmap")):
        return None
    # 已应用执行版必须继续走 6C 的代际/上游引用校验，不能被基线豁免覆盖。
    execution_plan = resolved.get(STAGE_EXECUTION_PLAN)
    if execution_plan is not None and bool(execution_plan.get("applied")):
        return None
    if resolved.get(STAGE_PROFILE) is None:
        return None

    artifact_ids = {
        STAGE_KEYS[stage]: _artifact_id(resolved.get(stage)) for stage in STAGE_ORDER
    }
    if has_tasks:
        return _result(
            STAGE_EXECUTING,
            "get_next_tasks",
            "已按基线执行，企业适配已记录跳过；可按当前阶段任务推进",
            artifact_ids,
            has_tasks=True,
        )
    return _result(
        STAGE_EXECUTION,
        "generate_tasks",
        "已按基线执行，企业适配已记录跳过；先生成当前阶段任务",
        artifact_ids,
        has_tasks=False,
    )


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return sorted(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def target_fingerprint(spec: Any) -> str:
    """TargetSpec 唯一指纹：只由目标身份字段决定，排除 expected_outcome 等补充信息。"""
    if isinstance(spec, dict):
        data = spec
    elif hasattr(spec, "model_dump"):
        data = spec.model_dump()
    else:
        data = {field: getattr(spec, field, None) for field in TARGET_FINGERPRINT_FIELDS}
    payload = {
        field: _fingerprint_value(data.get(field))
        for field in TARGET_FINGERPRINT_FIELDS
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def profile_target_fingerprint(profile: Any) -> str:
    """从档案 want/who 计算当前目标指纹（与 sync_target 写 artifact 时一致）。"""
    try:
        from .adapters.profile_mapping import target_spec

        return target_fingerprint(target_spec(profile))
    except Exception:  # noqa: BLE001 - 畸形档案按空指纹处理，不误判失效
        return ""


def stored_target_fingerprint(artifact: dict[str, Any] | None) -> str:
    """读取 TargetSpec artifact 保存的指纹；旧 artifact 无指纹时返回空串。"""
    meta = artifact.get("meta") if isinstance(artifact, dict) else None
    inputs = meta.get("inputs") if isinstance(meta, dict) else None
    if not isinstance(inputs, dict):
        return ""
    return str(inputs.get(TARGET_FINGERPRINT_KEY) or "").strip()


def _target_stale(profile: Any, artifact: dict[str, Any]) -> bool:
    """目标指纹变化时旧 TargetSpec 失效；没有保存指纹的旧 artifact 保持兼容。"""
    stored = stored_target_fingerprint(artifact)
    if not stored:
        return False
    current = profile_target_fingerprint(profile)
    return bool(current) and current != stored


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
    "TARGET_FINGERPRINT_FIELDS",
    "TARGET_FINGERPRINT_KEY",
    "downstream_exists",
    "profile_target_fingerprint",
    "resolve_artifact",
    "resolve_progress",
    "stored_target_fingerprint",
    "target_fingerprint",
]
