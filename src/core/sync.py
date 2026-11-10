"""`CareerProfile` → Core v2 artifact 同步层（全 12 阶段）。

把 `CareerProfile` 中已有的数据写成新 artifact，并在档案 `core_state`
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
from .adapters.profile_mapping import profile_snapshot, target_spec
from .artifacts.models import (
    ApplicationCandidate,
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
from .progress import TARGET_FINGERPRINT_KEY, target_fingerprint

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
    """目标岗位定位 → TargetSpec artifact（`ts_`）。

    TargetSpec 必须引用 ProfileSnapshot；缺上游时先尝试生成快照，仍缺失则返回空，
    不写半成品。
    """
    try:
        profile = load_profile(profile_name)
        if not profile.want:
            return ""
        guidance = profile.guidance if isinstance(profile.guidance, dict) else {}
        # 目标未由用户确认时不得写 TargetSpec。
        if not guidance.get("goal_confirmed_at"):
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        # TargetSpec 不能反向创建 ProfileSnapshot：新流程必须等 finalize_profile，
        # 否则 intake(want) 后 GUIDE 会跳过建档直接进入市场调研。
        profile_id = _existing_profile_id(store, profile_name, state)
        if not profile_id:
            return ""
        spec = target_spec(profile)
        artifact = _TargetArtifact(
            meta=_meta(
                store,
                "ts",
                STAGE_TARGET,
                profile_name,
                {
                    "profile_id": profile_id,
                    TARGET_FINGERPRINT_KEY: target_fingerprint(spec),
                },
            ),
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
        # meta.inputs.profile_id 必须指向本次解析到的快照，不能用解析前的旧 state。
        profile_id = _resolve_profile_id(store, profile_name, state)
        if not profile_id:
            return ""
        target_id = _resolve_target_spec_id(store, profile_name, state)
        if not target_id:
            return ""
        artifact = MarketBaseline(
            meta=_meta(
                store,
                "mb",
                STAGE_MARKET_BASELINE,
                profile_name,
                {"profile_id": profile_id, "target_spec_id": target_id},
            ),
            target_spec=_resolve_target_spec(store, profile, target_id),
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

    必须能解析出 ProfileSnapshot 与当前 TargetSpec，否则返回空字符串，
    不写 ``profile_snapshot_id`` 为空的半成品 GapReport。市场调研被跳过时
    MarketBaseline 缺失，仍写 GapReport，但标记 ``validation.market_skipped``
    并把 ``meta.inputs.target_spec_id`` 指向当前 TargetSpec。
    """
    try:
        profile = load_profile(profile_name)
        gap = profile.gap if isinstance(profile.gap, dict) else {}
        if not gap:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        profile_id = _resolve_profile_id(store, profile_name, state)
        if not profile_id:
            return ""
        target_id = _resolve_target_spec_id(store, profile_name, state)
        if not target_id:
            return ""
        market_id = _resolve_market_baseline_id(store, profile_name, state)
        validation = {"market_skipped": True} if not market_id else {}
        inputs: dict[str, Any] = {
            "profile_id": profile_id,
            "target_spec_id": target_id,
        }
        if market_id:
            inputs["market_baseline_id"] = market_id
        artifact = GapReport(
            meta=_meta(
                store,
                "gr",
                STAGE_GAP,
                profile_name,
                inputs,
                validation=validation,
            ),
            profile_snapshot_id=profile_id,
            market_baseline_id=market_id,
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
    返回空字符串，不写半成品。上游 GapReport 缺失时只有 import_plan 路径
    （``guidance.plan_imported_at``）允许写 ``validation.imported`` 的
    BaselinePlan；市场跳过由 GapReport 的 ``validation.market_skipped`` 继承。
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
        if _plan_imported(profile):
            gap_id = _existing_gap_report_id(store, profile_name, state)
        else:
            gap_id = _resolve_gap_report_id(store, profile_name, state)
        validation: dict[str, Any] = {}
        target_id = ""
        if gap_id:
            gap = store.load(gap_id)
            gap_meta = gap.get("meta") if isinstance(gap, dict) else None
            gap_validation = (
                gap_meta.get("validation") if isinstance(gap_meta, dict) else None
            )
            if isinstance(gap_validation, dict) and gap_validation.get(
                "market_skipped"
            ):
                validation["market_skipped"] = True
            gap_inputs = (
                gap_meta.get("inputs") if isinstance(gap_meta, dict) else None
            )
            if isinstance(gap_inputs, dict):
                target_id = str(gap_inputs.get("target_spec_id") or "")
        elif _plan_imported(profile):
            validation["imported"] = True
        else:
            return ""
        if not target_id:
            target_id = _resolve_target_spec_id(store, profile_name, state)
        strategy = str(plan.get("strategy_summary") or "")
        if not strategy:
            strategy = str(roadmap.get("strategy_summary") or "")
        inputs: dict[str, Any] = {
            "profile_id": state.get(KEY_PROFILE, ""),
            "target_spec_id": target_id,
        }
        if gap_id:
            inputs["gap_report_id"] = gap_id
        artifact = BaselinePlan(
            meta=_meta(
                store,
                "bp",
                STAGE_BASELINE_PLAN,
                profile_name,
                inputs,
                validation=validation,
            ),
            gap_report_id=gap_id,
            strategy_summary=strategy,
            roadmap=roadmap,
        )
        return _persist(profile, profile_name, artifact, KEY_BASELINE_PLAN, STAGE_BASELINE_PLAN)
    except Exception:
        return ""


def sync_execution_state(profile_name: str) -> str:
    """任务与打卡 → ExecutionState artifact（`es_`）。

    必须已有 applied ExecutionPlan 且 ``execution_plan_id`` 非空；否则返回空字符串，
    绝不写 ``execution_plan_id`` 为空的半成品 ExecutionState。
    """
    try:
        profile = load_profile(profile_name)
        if not profile.tasks:
            return ""
        state = _core_state(profile)
        store = ArtifactStore()
        plan_id = str(state.get("execution_plan_id") or "").strip()
        if not plan_id:
            return ""
        plan = store.load(plan_id)
        if not (
            _matches_stage(plan, STAGE_EXECUTION_PLAN, profile_name)
            and bool(plan.get("applied"))
        ):
            return ""
        # ExecutionState 只属于当前 applied plan 的代际：plan 里保留的
        # completed/skipped 历史任务不是新方案生成的任务，不能凭它们落库。
        if not _has_current_generation_tasks(plan, profile):
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
                    "execution_plan_id": plan_id,
                },
            ),
            execution_plan_id=plan_id,
            current_phase_id=str(current["phase_id"]) if current else "",
            task_counts=task_counts,
            checkin_counts=checkin_counts,
            capability_evidence=_dict_list(have.get("capability_evidence")),
        )
        return _persist(profile, profile_name, artifact, KEY_EXECUTION, STAGE_EXECUTION)
    except Exception:
        return ""


def sync_application_state(profile_name: str) -> str:
    """投递记录 → ApplicationState artifact（`as_`，可选阶段，不推进 stage）。

    重建时保留最近一次 ApplicationState 的 ``candidates``：投递清单是用户资产，
    记录/删除投递不应把已生成的候选清空。只有投递记录与候选都为空时才清指针。
    """
    try:
        profile = load_profile(profile_name)
        state = _core_state(profile)
        store = ArtifactStore()
        candidates = _existing_candidates(store, profile_name, state)
        if not profile.applications and not candidates:
            # 投递被删空且没有候选时清掉旧指针，避免 core_state 指向已失效的 artifact。
            if state.get(KEY_APPLICATIONS):
                merge_core_state(profile_name, {KEY_APPLICATIONS: None})
            return ""
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
            candidates=candidates,
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


def _existing_candidates(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> list[ApplicationCandidate]:
    """读取最近一次 ApplicationState 的候选；缺失或损坏时返回空列表。"""
    artifact_id = str(state.get(KEY_APPLICATIONS) or "")
    data = store.load(artifact_id) if artifact_id else None
    if _matches_stage(data, STAGE_APPLICATIONS, profile_name):
        candidates = _parse_candidates(data)
        if candidates:
            return candidates
    latest = store.latest(profile_name, STAGE_APPLICATIONS)
    if _matches_stage(latest, STAGE_APPLICATIONS, profile_name):
        return _parse_candidates(latest)
    return []


def _parse_candidates(data: dict[str, Any] | None) -> list[ApplicationCandidate]:
    if not isinstance(data, dict):
        return []
    raw = data.get("candidates")
    if not isinstance(raw, list):
        return []
    candidates: list[ApplicationCandidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            candidates.append(ApplicationCandidate.model_validate(item))
        except Exception:
            continue
    return candidates


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
        # ReviewReport 引用的 ExecutionState 必须属于当前 applied plan。
        if str(execution.get("execution_plan_id") or "") != plan_id:
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
    validation: dict[str, Any] | None = None,
) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
        inputs={str(key): str(value) for key, value in inputs.items() if value},
        validation=dict(validation or {}),
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


def _has_current_generation_tasks(
    plan: dict[str, Any], profile: CareerProfile
) -> bool:
    """任务是否属于当前 applied plan 这一代。

    apply 时保留的 completed/skipped 历史任务记在 ExecutionPlan.completed_evidence；
    如果档案里的任务全部是这些历史任务，说明新方案还没执行 generate_tasks，
    不能据此写入 ExecutionState。旧 artifact 没有 completed_evidence 时保持兼容。
    """
    current_ids = {task.id for task in profile.tasks if task.id}
    if not current_ids:
        return False
    preserved_ids = {
        str(item.get("task_id") or "").strip()
        for item in plan.get("completed_evidence") or []
        if isinstance(item, dict) and str(item.get("task_id") or "").strip()
    }
    if not (preserved_ids and current_ids <= preserved_ids):
        return True
    # 新方案的任务名与历史任务完全同名时会被复用 ID：只要当前 plan 的预期任务
    # 已被现有任务覆盖，就视为已生成（避免误把已完成的复用任务挡在门禁外）。
    return _tasks_cover_plan(plan, profile)


def _tasks_cover_plan(plan: dict[str, Any], profile: CareerProfile) -> bool:
    roadmap = plan.get("roadmap") if isinstance(plan.get("roadmap"), dict) else {}
    phases = roadmap.get("phases") if isinstance(roadmap.get("phases"), list) else []
    expected: set[tuple[str, str]] = set()
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        phase_id = str(phase.get("id") or f"phase_{index + 1}")
        milestones = phase.get("milestones") if isinstance(phase.get("milestones"), list) else []
        for milestone in milestones:
            if not isinstance(milestone, dict):
                continue
            tasks = milestone.get("tasks") if isinstance(milestone.get("tasks"), list) else []
            for task in tasks:
                if isinstance(task, dict) and str(task.get("name") or "").strip():
                    expected.add((phase_id, str(task["name"]).strip()))
    if not expected:
        return False
    current = {(task.phase_id, task.name) for task in profile.tasks}
    return expected <= current


def _core_state(profile: CareerProfile) -> dict[str, Any]:
    state = getattr(profile, "core_state", None)
    return dict(state) if isinstance(state, dict) else {}


def _resolve_target_spec_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """解析 MarketBaseline 依赖的 TargetSpec id；缺失时尝试从档案同步一次。"""
    target_id = str(state.get(KEY_TARGET) or "").strip()
    if target_id:
        # core_state 已有指针但不合法时不再重建，避免覆盖用户已有 key。
        data = store.load(target_id)
        return target_id if _matches_stage(data, STAGE_TARGET, profile_name) else ""
    return sync_target(profile_name)


def _resolve_target_spec(
    store: ArtifactStore, profile: CareerProfile, target_id: str
) -> TargetSpec:
    if target_id:
        data = store.load(target_id)
        if isinstance(data, dict):
            fields = {name: data[name] for name in TargetSpec.model_fields if name in data}
            try:
                return TargetSpec.model_validate(fields)
            except Exception:
                pass
    return target_spec(profile)


def _existing_profile_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """只解析已存在的 ProfileSnapshot；缺失时不创建，返回空字符串。"""
    profile_id = str(state.get(KEY_PROFILE) or "")
    if profile_id and _matches_stage(
        store.load(profile_id), STAGE_PROFILE, profile_name
    ):
        return profile_id
    latest = store.latest(profile_name, STAGE_PROFILE)
    if _matches_stage(latest, STAGE_PROFILE, profile_name):
        return _artifact_id(latest)
    return ""


def _resolve_profile_id(
    store: ArtifactStore,
    profile_name: str,
    state: dict[str, Any],
) -> str:
    """解析 GapReport 依赖的 ProfileSnapshot id。

    优先 core_state 指针，其次该档案最新的 ProfileSnapshot；都没有时返回空字符串。
    """
    profile_id = str(state.get(KEY_PROFILE) or "")
    if profile_id and _matches_stage(
        store.load(profile_id), STAGE_PROFILE, profile_name
    ):
        return profile_id
    latest = store.latest(profile_name, STAGE_PROFILE)
    if _matches_stage(latest, STAGE_PROFILE, profile_name):
        return _artifact_id(latest)
    return ""


def _resolve_market_baseline_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """解析 GapReport 依赖的 MarketBaseline id；缺失时尝试从档案同步一次。"""
    market_id = str(state.get(KEY_MARKET_BASELINE) or "").strip()
    if market_id:
        data = store.load(market_id)
        return (
            market_id
            if _matches_stage(data, STAGE_MARKET_BASELINE, profile_name)
            else ""
        )
    return sync_market_baseline(profile_name)


def _resolve_gap_report_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """解析 BaselinePlan 依赖的 GapReport id；缺失时尝试从档案同步一次。"""
    gap_id = str(state.get(KEY_GAP) or "").strip()
    if gap_id:
        return gap_id if _matches_stage(store.load(gap_id), STAGE_GAP, profile_name) else ""
    return sync_gap(profile_name)


def _existing_gap_report_id(
    store: ArtifactStore, profile_name: str, state: dict[str, Any]
) -> str:
    """只解析已存在的 GapReport；import_plan 路径不得反向创建差距分析。"""
    gap_id = str(state.get(KEY_GAP) or "").strip()
    if gap_id and _matches_stage(store.load(gap_id), STAGE_GAP, profile_name):
        return gap_id
    latest = store.latest(profile_name, STAGE_GAP)
    return _artifact_id(latest) if _matches_stage(latest, STAGE_GAP, profile_name) else ""


def _plan_imported(profile: CareerProfile) -> bool:
    guidance = getattr(profile, "guidance", None)
    return bool(isinstance(guidance, dict) and guidance.get("plan_imported_at"))


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
