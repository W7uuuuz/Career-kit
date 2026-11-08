"""旧档案 → Core v2 artifact 同步层（全 12 阶段迁移）。

把旧 `CareerProfile` 中已有的数据写成新 artifact，并在档案 `core_state`
里写入对应指针。纪律：

- 只从档案复制事实，除 `core_state` 外不修改任何字段；
- 缺失前置数据时返回空字符串，不写半成品 artifact；
- 任何失败都不抛给调用方，返回空字符串由主工具决定是否记录 warning。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..models import CareerProfile
from ..tools.application_tracker import funnel_stats
from ..tools.profile import load_profile, profile_lock, save_profile
from ..tools.task_manager import resolve_current_phase
from .adapters.legacy_profile import profile_snapshot, target_spec
from .artifacts.models import (
    ApplicationState,
    ArtifactMeta,
    BaselinePlan,
    ExecutionState,
    GapReport,
    MarketBaseline,
    ProfileSnapshot,
    ReviewReport,
    TargetSpec,
)
from .artifacts.store import ArtifactStore

STAGE_PROFILE = "profile"
STAGE_TARGET = "target"
STAGE_MARKET_BASELINE = "market_baseline"
STAGE_GAP = "gap"
STAGE_BASELINE_PLAN = "baseline_plan"
STAGE_EXECUTION_PLAN = "execution_plan"
STAGE_EXECUTION = "execution"
STAGE_APPLICATIONS = "applications"
STAGE_REVIEW = "review"

KEY_PROFILE = "profile_id"
KEY_TARGET = "target_spec_id"
KEY_MARKET_BASELINE = "market_baseline_id"
KEY_GAP = "gap_report_id"
KEY_BASELINE_PLAN = "baseline_plan_id"
KEY_EXECUTION = "execution_state_id"
KEY_APPLICATIONS = "application_state_id"
KEY_REVIEW = "review_report_id"


class _ProfileArtifact(ProfileSnapshot):
    """给 ProfileSnapshot 附加 meta，使其可被 ArtifactStore 持久化。"""

    meta: ArtifactMeta


class _TargetArtifact(TargetSpec):
    """给 TargetSpec 附加 meta，使其可被 ArtifactStore 持久化。"""

    meta: ArtifactMeta


def sync_profile(profile_name: str) -> str:
    """档案快照 → ProfileSnapshot artifact（`pf_`）。"""
    try:
        profile = load_profile(profile_name)
        snapshot = profile_snapshot(profile)
        if not (snapshot.who or snapshot.have or snapshot.want or snapshot.summary):
            return ""
        store = ArtifactStore()
        artifact = _ProfileArtifact(
            meta=_meta(store, "pf", STAGE_PROFILE, profile_name, {}),
            **snapshot.model_dump(),
        )
        return _persist(profile, profile_name, artifact, KEY_PROFILE, STAGE_PROFILE)
    except Exception:
        return ""


def sync_target(profile_name: str) -> str:
    """目标岗位定位 → TargetSpec artifact（`ts_`）。"""
    try:
        profile = load_profile(profile_name)
        if not profile.want:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        spec = target_spec(profile)
        artifact = _TargetArtifact(
            meta=_meta(store, "ts", STAGE_TARGET, profile_name, {"profile_id": state.get(KEY_PROFILE, "")}),
            **spec.model_dump(),
        )
        return _persist(profile, profile_name, artifact, KEY_TARGET, STAGE_TARGET)
    except Exception:
        return ""


def sync_market_baseline(profile_name: str) -> str:
    """市场调研 → MarketBaseline artifact（`mb_`）。"""
    try:
        profile = load_profile(profile_name)
        research = profile.research if isinstance(profile.research, dict) else {}
        if not (research.get("report_md") or research.get("jd_samples") or research.get("cases")):
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        artifact = MarketBaseline(
            meta=_meta(
                store,
                "mb",
                STAGE_MARKET_BASELINE,
                profile_name,
                {"profile_id": state.get(KEY_PROFILE, ""), "target_spec_id": state.get(KEY_TARGET, "")},
            ),
            target_spec=_resolve_target_spec(store, profile, state),
            jd_samples=_dict_list(research.get("jd_samples")),
            case_samples=_dict_list(research.get("cases")),
            digest=_as_dict(research.get("digest")),
            source_status=_dict_list(research.get("source_status")),
            counts=_int_dict(research.get("counts")),
            gaps=_str_list(research.get("gaps")),
            report_paths=_report_paths(research),
        )
        return _persist(profile, profile_name, artifact, KEY_MARKET_BASELINE, STAGE_MARKET_BASELINE)
    except Exception:
        return ""


def sync_gap(profile_name: str) -> str:
    """差距分析 → GapReport artifact（`gr_`）。

    必须能解析出 profile 快照并落成 ProfileSnapshot，否则返回空字符串，
    不写 ``profile_snapshot_id`` 为空的半成品 GapReport。
    """
    try:
        profile = load_profile(profile_name)
        gap = profile.gap if isinstance(profile.gap, dict) else {}
        if not gap:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        profile_id = _resolve_profile_id(store, profile, profile_name, state)
        if not profile_id:
            return ""
        artifact = GapReport(
            meta=_meta(
                store,
                "gr",
                STAGE_GAP,
                profile_name,
                {
                    "profile_id": profile_id,
                    "market_baseline_id": state.get(KEY_MARKET_BASELINE, ""),
                },
            ),
            profile_snapshot_id=profile_id,
            market_baseline_id=str(state.get(KEY_MARKET_BASELINE, "")),
            match_score=_as_int(gap.get("match_score")),
            match_level=str(gap.get("match_level") or ""),
            start_level=str(gap.get("start_level") or ""),
            strengths=_dict_list(gap.get("strengths")),
            resume_red_flags=_dict_list(gap.get("resume_red_flags")),
            resume_optimization=_as_dict(gap.get("resume_optimization")),
            interview_preparation=_as_dict(gap.get("interview_preparation")),
            skill_gaps=_dict_list(gap.get("skill_gaps")),
            priority_actions=_dict_list(gap.get("priority_actions")),
            market_context=str(gap.get("market_context") or ""),
        )
        return _persist(profile, profile_name, artifact, KEY_GAP, STAGE_GAP)
    except Exception:
        return ""


def sync_baseline_plan(profile_name: str) -> str:
    """基线路线图 → BaselinePlan artifact（`bp_`）。

    ``plan.roadmap`` 必须是带非空 phases 的 dict；list/空值视为畸形数据，
    返回空字符串，不写半成品。
    """
    try:
        profile = load_profile(profile_name)
        plan = profile.plan if isinstance(profile.plan, dict) else {}
        roadmap = plan.get("roadmap")
        if not isinstance(roadmap, dict):
            return ""
        phases = roadmap.get("phases")
        if not isinstance(phases, list) or not phases:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        strategy = str(plan.get("strategy_summary") or "")
        if not strategy:
            strategy = str(roadmap.get("strategy_summary") or "")
        artifact = BaselinePlan(
            meta=_meta(
                store,
                "bp",
                STAGE_BASELINE_PLAN,
                profile_name,
                {"profile_id": state.get(KEY_PROFILE, ""), "gap_report_id": state.get(KEY_GAP, "")},
            ),
            gap_report_id=str(state.get(KEY_GAP, "")),
            strategy_summary=strategy,
            roadmap=roadmap,
        )
        return _persist(profile, profile_name, artifact, KEY_BASELINE_PLAN, STAGE_BASELINE_PLAN)
    except Exception:
        return ""


def sync_execution_state(profile_name: str) -> str:
    """任务与打卡 → ExecutionState artifact（`es_`）。

    必须已有已应用的 ExecutionPlan，或可解析的 baseline plan；否则返回空字符串，
    不写 ``execution_plan_id`` 为空的半成品 ExecutionState。
    """
    try:
        profile = load_profile(profile_name)
        if not profile.tasks:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        plan_id = str(state.get("execution_plan_id") or "")
        plan = store.load(plan_id) if plan_id else None
        has_applied_plan = _matches_stage(
            plan, STAGE_EXECUTION_PLAN, profile_name
        ) and bool(plan.get("applied"))
        if has_applied_plan:
            baseline_id = str(state.get(KEY_BASELINE_PLAN) or "")
        else:
            baseline_id = _resolve_baseline_plan_id(store, profile_name, state)
            if not baseline_id:
                return ""
        task_counts = {"pending": 0, "in_progress": 0, "completed": 0, "skipped": 0}
        for task in profile.tasks:
            task_counts[task.status] = task_counts.get(task.status, 0) + 1
        checkin_counts: dict[str, int] = {}
        for checkin in profile.checkins:
            checkin_counts[checkin.status] = checkin_counts.get(checkin.status, 0) + 1
        current = resolve_current_phase(profile)
        have = profile.have if isinstance(profile.have, dict) else {}
        artifact = ExecutionState(
            meta=_meta(
                store,
                "es",
                STAGE_EXECUTION,
                profile_name,
                {
                    "profile_id": state.get(KEY_PROFILE, ""),
                    "baseline_plan_id": baseline_id,
                    "execution_plan_id": plan_id if has_applied_plan else "",
                },
            ),
            execution_plan_id=plan_id if has_applied_plan else "",
            current_phase_id=str(current["phase_id"]) if current else "",
            task_counts=task_counts,
            checkin_counts=checkin_counts,
            capability_evidence=_dict_list(have.get("capability_evidence")),
        )
        return _persist(profile, profile_name, artifact, KEY_EXECUTION, STAGE_EXECUTION)
    except Exception:
        return ""


def sync_application_state(profile_name: str) -> str:
    """投递记录 → ApplicationState artifact（`as_`，可选阶段，不推进 stage）。"""
    try:
        profile = load_profile(profile_name)
        state = _core_state(profile)
        if not profile.applications:
            # 投递被删空时清掉旧指针，避免 core_state 指向已失效的 artifact。
            if state.get(KEY_APPLICATIONS):
                merge_core_state(profile_name, {KEY_APPLICATIONS: None})
            return ""
        store = ArtifactStore()
        artifact = ApplicationState(
            meta=_meta(
                store,
                "as",
                STAGE_APPLICATIONS,
                profile_name,
                {
                    "profile_id": state.get(KEY_PROFILE, ""),
                    "evidence_run_id": state.get("evidence_run_id", ""),
                },
            ),
            evidence_run_id=str(state.get("evidence_run_id") or ""),
            applications=[app.model_dump() for app in profile.applications],
            funnel=funnel_stats(profile),
        )
        return _persist(
            profile,
            profile_name,
            artifact,
            KEY_APPLICATIONS,
            STAGE_APPLICATIONS,
            advance_stage=False,
        )
    except Exception:
        return ""


def sync_review(
    profile_name: str,
    plan_fit: dict | None = None,
    weekly_facts: dict | None = None,
) -> str:
    """周期复盘 → ReviewReport artifact（`rr_`，可选阶段，不推进 stage）。

    前置链路不完整（无 applied ExecutionPlan / 无 ExecutionState）时返回空字符串，
    不写孤儿 ReviewReport。
    """
    try:
        if not plan_fit and not weekly_facts:
            return ""
        profile = load_profile(profile_name)
        state = _core_state(profile)
        store = ArtifactStore()

        plan_id = str(state.get("execution_plan_id") or "")
        plan = store.load(plan_id) if plan_id else None
        if not _matches_stage(plan, STAGE_EXECUTION_PLAN, profile_name):
            return ""
        if not bool(plan.get("applied")):
            return ""

        execution_id = str(state.get(KEY_EXECUTION) or "")
        execution = store.load(execution_id) if execution_id else None
        if not _matches_stage(execution, STAGE_EXECUTION, profile_name):
            return ""

        fit = _jsonable(plan_fit) if isinstance(plan_fit, dict) else {}
        facts = _jsonable(weekly_facts) if isinstance(weekly_facts, dict) else {}
        artifact = ReviewReport(
            meta=_meta(
                store,
                "rr",
                STAGE_REVIEW,
                profile_name,
                {
                    "profile_id": state.get(KEY_PROFILE, ""),
                    "execution_state_id": execution_id,
                },
            ),
            execution_state_id=execution_id,
            plan_fit=fit if isinstance(fit, dict) else {},
            weekly_facts=facts if isinstance(facts, dict) else {},
            recommendations=_recommendations(fit, facts),
        )
        return _persist(
            profile,
            profile_name,
            artifact,
            KEY_REVIEW,
            STAGE_REVIEW,
            advance_stage=False,
        )
    except Exception:
        return ""


def _meta(
    store: ArtifactStore,
    prefix: str,
    stage: str,
    profile_name: str,
    inputs: dict[str, Any],
) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
        inputs={str(key): str(value) for key, value in inputs.items() if value},
    )


def merge_core_state(
    profile_name: str,
    updates: dict[str, Any],
    advance_stage: bool = False,
) -> dict[str, Any]:
    """原子更新 core_state：load → 合并 → save 全程持档案锁，避免并发丢 key。

    - ``updates`` 中值为 None 表示删除该 key；
    - ``advance_stage=False`` 时不接受 ``stage`` 变更（可选阶段不推进）；
    - 始终刷新 ``updated_at``。
    """
    with profile_lock(profile_name):
        profile = load_profile(profile_name)
        state = _core_state(profile)
        for key, value in updates.items():
            if key == "stage" and not advance_stage:
                continue
            if value is None:
                state.pop(key, None)
            else:
                state[key] = value
        state["updated_at"] = datetime.now().isoformat()
        profile.core_state = state
        save_profile(profile, profile_name)
        return dict(state)


def _persist(
    profile: CareerProfile,
    profile_name: str,
    artifact: BaseModel,
    key: str,
    stage: str,
    *,
    advance_stage: bool = True,
) -> str:
    store = ArtifactStore()
    artifact_id = store.save(artifact, dedupe=True)
    updates: dict[str, Any] = {key: artifact_id}
    if advance_stage:
        updates["stage"] = stage
    merge_core_state(profile_name, updates, advance_stage=advance_stage)
    return artifact_id


def _matches_stage(
    data: dict[str, Any] | None, stage: str, profile_name: str
) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    if not isinstance(meta, dict) or meta.get("stage") != stage:
        return False
    return str(meta.get("profile_name") or "") == profile_name


def _core_state(profile: CareerProfile) -> dict[str, Any]:
    state = getattr(profile, "core_state", None)
    return dict(state) if isinstance(state, dict) else {}


def _resolve_target_spec(
    store: ArtifactStore, profile: CareerProfile, state: dict[str, Any]
) -> TargetSpec:
    target_id = str(state.get(KEY_TARGET) or "")
    if target_id:
        data = store.load(target_id)
        if isinstance(data, dict):
            fields = {name: data[name] for name in TargetSpec.model_fields if name in data}
            try:
                return TargetSpec.model_validate(fields)
            except Exception:
                pass
    return target_spec(profile)


def _resolve_profile_id(
    store: ArtifactStore,
    profile: CareerProfile,
    profile_name: str,
    state: dict[str, Any],
) -> str:
    """解析 GapReport 依赖的 ProfileSnapshot id。

    优先 core_state 指针，其次该档案最新的 ProfileSnapshot；都没有时尝试从
    当前档案生成可解析的快照并落库。无法生成时返回空字符串。
    """
    profile_id = str(state.get(KEY_PROFILE) or "")
    if profile_id and _matches_stage(
        store.load(profile_id), STAGE_PROFILE, profile_name
    ):
        return profile_id
    latest = store.latest(profile_name, STAGE_PROFILE)
    if _matches_stage(latest, STAGE_PROFILE, profile_name):
        return _artifact_id(latest)
    try:
        snapshot = profile_snapshot(profile)
    except Exception:
        return ""
    if not (
        snapshot.who
        or snapshot.have
        or snapshot.want
        or snapshot.gap
        or snapshot.plan
        or snapshot.summary
    ):
        return ""
    artifact = _ProfileArtifact(
        meta=_meta(store, "pf", STAGE_PROFILE, profile_name, {}),
        **snapshot.model_dump(),
    )
    new_id = store.save(artifact, dedupe=True)
    merge_core_state(profile_name, {KEY_PROFILE: new_id}, advance_stage=False)
    return new_id


def _resolve_baseline_plan_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """解析 ExecutionState 依赖的 BaselinePlan id；缺失时尝试从档案同步一次。"""
    baseline_id = str(state.get(KEY_BASELINE_PLAN) or "")
    if baseline_id and _matches_stage(
        store.load(baseline_id), STAGE_BASELINE_PLAN, profile_name
    ):
        return baseline_id
    return sync_baseline_plan(profile_name)


def _artifact_id(artifact: dict[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    meta = artifact.get("meta")
    return str(meta.get("id") or "") if isinstance(meta, dict) else ""


def _report_paths(research: dict[str, Any]) -> dict[str, str]:
    paths = {
        "md": str(research.get("report_md") or ""),
        "html": str(research.get("report_html") or ""),
        "json": str(research.get("report_json") or ""),
    }
    return {key: value for key, value in paths.items() if value}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _int_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, item in value.items():
        try:
            counts[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return counts


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _recommendations(plan_fit: dict[str, Any], weekly_facts: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    signals = plan_fit.get("signals")
    if isinstance(signals, list):
        for signal in signals:
            if isinstance(signal, dict):
                message = str(signal.get("message") or "").strip()
                if message:
                    recommendations.append(message)
    suggestions = weekly_facts.get("suggestions")
    if isinstance(suggestions, list):
        for suggestion in suggestions:
            text = str(suggestion).strip()
            if text:
                recommendations.append(text)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in recommendations:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


__all__ = [
    "KEY_APPLICATIONS",
    "KEY_BASELINE_PLAN",
    "KEY_EXECUTION",
    "KEY_GAP",
    "KEY_MARKET_BASELINE",
    "KEY_PROFILE",
    "KEY_REVIEW",
    "KEY_TARGET",
    "STAGE_APPLICATIONS",
    "STAGE_BASELINE_PLAN",
    "STAGE_EXECUTION",
    "STAGE_EXECUTION_PLAN",
    "STAGE_GAP",
    "STAGE_MARKET_BASELINE",
    "STAGE_PROFILE",
    "STAGE_REVIEW",
    "STAGE_TARGET",
    "merge_core_state",
    "sync_application_state",
    "sync_baseline_plan",
    "sync_execution_state",
    "sync_gap",
    "sync_market_baseline",
    "sync_profile",
    "sync_review",
    "sync_target",
]
