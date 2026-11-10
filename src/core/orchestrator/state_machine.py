"""阶段状态机——根据档案 core_state 与 artifact 事实推导下一步。

只读：不写档案、不落库。状态判定唯一来源是 ``core.state.resolve_state``：
``next_action`` 只把 ``StateSnapshot`` 映射成历史字段，供 web 与旧调用方消费；
artifact 解析复用 ``core.progress`` 的纯查询函数，不再调用旧的进度解析入口。

12 阶段顺序：档案 → 目标 → 市场基线 → 差距 → 基线方案 → 企业池 →
证据 → 需求 → 执行方案 → 执行状态。阶段 11/12（投递、复盘）是可选阶段，
不阻塞执行；执行状态就绪后只作为 optional_next_tools 推荐。
"""

from __future__ import annotations

from typing import Any

from ...tools.profile import load_profile
from ..artifacts.store import ArtifactStore
from ..progress import (
    _OPTIONAL_EXECUTION_TOOLS,
    ARTIFACT_KEYS,
    REQUIRED_STAGES,
    STAGE_APPLICATIONS,
    STAGE_BASELINE_PLAN,
    STAGE_COMPANY_POOL,
    STAGE_EVIDENCE,
    STAGE_EXECUTING,
    STAGE_EXECUTION,
    STAGE_EXECUTION_PLAN,
    STAGE_GAP,
    STAGE_KEYS,
    STAGE_MARKET,
    STAGE_ORDER,
    STAGE_PROFILE,
    STAGE_REQUIREMENT,
    STAGE_REVIEW,
    STAGE_TARGET,
    _upstream_problems,
    downstream_exists,
    resolve_artifact,
)
from ..state import State, StateSnapshot, resolve_state

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

# State → 历史阶段 key：只服务旧接口字段，不参与状态判定。
_STATE_STAGE: dict[State, str] = {
    State.EMPTY: STAGE_PROFILE,
    State.PROFILE_COLLECTING: STAGE_TARGET,
    State.PROFILE_READY: STAGE_PROFILE,
    State.MARKET_PENDING: STAGE_MARKET,
    State.GAP_PENDING: STAGE_GAP,
    State.BASELINE_PLAN_PENDING: STAGE_BASELINE_PLAN,
    State.COMPANY_PENDING: STAGE_COMPANY_POOL,
    State.EVIDENCE_PENDING: STAGE_EVIDENCE,
    State.REQUIREMENT_DRAFT: STAGE_REQUIREMENT,
    State.REQUIREMENT_READY: STAGE_EXECUTION_PLAN,
    State.EXECUTION_PLAN_DRAFT: STAGE_EXECUTION_PLAN,
    State.EXECUTION_READY: STAGE_EXECUTION,
    State.EXECUTING: STAGE_EXECUTING,
    State.MAINTENANCE: STAGE_EXECUTING,
}

# 历史 next_tool 与快照不同的两处；其余直接复用 StateSnapshot。
_LEGACY_NEXT_TOOL: dict[State, str] = {
    State.EMPTY: "intake(section='bundle')",
    State.EXECUTION_READY: "generate_tasks",
    State.EXECUTING: "get_next_tasks",
    State.MAINTENANCE: "get_next_tasks",
}


class _NamedProfile:
    """给状态解析补上档案名，并兼容只有 artifact、没有 who 的旧 fixture。

    ``core.state._profile_name`` 优先读 ``profile.name``；测试与旧调用方通过
    ``next_action(profile_name)`` 显式传入档案名，这里用只读代理把名字带进去，
    不修改原对象。
    """

    def __init__(self, profile: Any, profile_name: str, *, has_profile_artifact: bool):
        self._profile = profile
        self._has_profile_artifact = has_profile_artifact
        self.name = profile_name

    def __getattr__(self, item: str) -> Any:
        value = getattr(self._profile, item, None)
        if item == "who" and not value and self._has_profile_artifact:
            return {"_resumed": True}
        return value


def next_action(profile_name: str) -> dict[str, Any]:
    """返回当前档案的下一步：阶段、建议工具、原因与已解析的 artifact ids。"""
    profile = load_profile(profile_name)
    store = ArtifactStore()
    resolved = _resolve_artifacts(store, profile_name)
    view = _NamedProfile(
        profile,
        profile_name,
        has_profile_artifact=resolved.get(STAGE_PROFILE) is not None,
    )
    snapshot = resolve_state(view, store)
    artifact_ids = _legacy_artifact_ids(resolved, snapshot)
    effective = _legacy_state(snapshot, resolved, artifact_ids)
    return {
        "stage": _STATE_STAGE[effective],
        "next_tool": _LEGACY_NEXT_TOOL.get(effective, snapshot.next_tool),
        "reason": _legacy_reason(snapshot, resolved, artifact_ids),
        "artifact_ids": artifact_ids,
        "optional_next_tools": (
            list(_OPTIONAL_EXECUTION_TOOLS)
            if effective in (State.EXECUTING, State.MAINTENANCE)
            else []
        ),
        "applied": bool(
            isinstance(resolved.get(STAGE_EXECUTION_PLAN), dict)
            and resolved[STAGE_EXECUTION_PLAN].get("applied")
        ),
        "has_execution_state": bool(
            artifact_ids.get(STAGE_KEYS[STAGE_EXECUTION])
        ),
        "has_tasks": bool(getattr(profile, "tasks", None) or []),
    }


def _resolve_artifacts(
    store: ArtifactStore, profile_name: str
) -> dict[str, dict[str, Any] | None]:
    profile = load_profile(profile_name)
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


def _legacy_artifact_ids(
    resolved: dict[str, dict[str, Any] | None], snapshot: StateSnapshot
) -> dict[str, str]:
    """按当前快照重算历史 artifact_ids：只保留链路内有效且已落库的上游。"""
    ids: dict[str, str] = dict.fromkeys(ARTIFACT_KEYS, "")
    codes = {blocker.code for blocker in snapshot.blockers}
    if "target_unconfirmed" in codes or "target_stale" in codes:
        resolved[STAGE_TARGET] = None

    for stage in REQUIRED_STAGES:
        artifact = resolved.get(stage)
        if artifact is None:
            if (
                stage == STAGE_MARKET
                and "market_skipped" in codes
            ):
                continue
            break
        problems = _upstream_problems(
            stage,
            artifact,
            ids,
            strict_baseline=_strict_baseline_for(stage, artifact),
        )
        if problems:
            break
        ids[STAGE_KEYS[stage]] = _artifact_id(artifact)
    return ids


def _plan_is_tracked(plan: dict[str, Any]) -> bool:
    """save 路径生成、带 validation 的 ExecutionPlan；旧 artifact 无元信息时放宽。"""
    meta = plan.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    return isinstance(validation, dict) and bool(validation)


def _strict_baseline_for(stage: str, artifact: dict[str, Any]) -> bool:
    """只有旧的无 validation ExecutionPlan 放宽 baseline_plan_id 校验。"""
    if stage != STAGE_EXECUTION_PLAN:
        return True
    return _plan_is_tracked(artifact)


def _legacy_state(
    snapshot: StateSnapshot,
    resolved: dict[str, dict[str, Any] | None],
    artifact_ids: dict[str, str],
) -> State:
    """旧 artifact 兼容：无 validation 的 applied ExecutionPlan 仍推进执行态。"""
    if snapshot.state is not State.REQUIREMENT_READY:
        return snapshot.state
    plan = resolved.get(STAGE_EXECUTION_PLAN)
    if not isinstance(plan, dict) or not plan.get("applied") or _plan_is_tracked(plan):
        return snapshot.state
    plan_id = _artifact_id(plan)
    if not plan_id:
        return snapshot.state
    execution = resolved.get(STAGE_EXECUTION)
    if isinstance(execution, dict):
        ids = dict(artifact_ids)
        ids[STAGE_KEYS[STAGE_EXECUTION_PLAN]] = plan_id
        if not _upstream_problems(STAGE_EXECUTION, execution, ids):
            return State.EXECUTING
    return State.EXECUTION_READY


def _legacy_reason(
    snapshot: StateSnapshot,
    resolved: dict[str, dict[str, Any] | None],
    artifact_ids: dict[str, str],
) -> str:
    parts = [blocker.detail for blocker in snapshot.blockers if blocker.detail]
    pending = _STATE_STAGE[snapshot.state]
    artifact = resolved.get(pending)
    if artifact is not None and pending in REQUIRED_STAGES:
        parts.extend(
            _upstream_problems(
                pending,
                artifact,
                artifact_ids,
                strict_baseline=_strict_baseline_for(pending, artifact),
            )
        )
    if "execution_plan_invalid" in {b.code for b in snapshot.blockers}:
        plan = resolved.get(STAGE_EXECUTION_PLAN) or {}
        baseline_id = str(plan.get("baseline_plan_id") or "")
        parts.append(f"检查 baseline_plan_id（当前 {baseline_id or '空'}）引用")
    return "；".join(dict.fromkeys(parts))


# ---------------------------------------------------------------------------
# 兼容包装：保留原有内部函数名，实际逻辑委托给共享 progress 模块。
# ---------------------------------------------------------------------------


def _downstream_exists(
    resolved: dict[str, dict[str, Any] | None], stage: str
) -> bool:
    return downstream_exists(resolved, stage)


def _resolve(
    store: ArtifactStore, profile_name: str, stage: str, artifact_id: str
) -> dict[str, Any] | None:
    return resolve_artifact(store, profile_name, stage, artifact_id)


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


def _has_want(profile: Any) -> bool:
    want = getattr(profile, "want", None) or {}
    return isinstance(want, dict) and bool(want)


def _has_tasks(profile: Any) -> bool:
    return bool(getattr(profile, "tasks", None) or [])


# 兼容旧引用：常量集合仍从 state_machine 暴露。
_STAGE_ORDER = STAGE_ORDER
_STAGE_KEYS = STAGE_KEYS
_ARTIFACT_KEYS = ARTIFACT_KEYS
