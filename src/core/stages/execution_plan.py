"""阶段 9：执行方案校准。

把基线路线图升级为执行版：代码负责提取已完成能力、校验结构、应用方案，
并维护 plan_history / adjustments；LLM 只设计 roadmap 与 changes。

确定性边界：
- completed_evidence 由代码从档案任务提取，不采信 LLM 输入；
- 每条 change 必须引用 evidence_ids，空证据的变更不允许落库；
- completed/skipped 任务是历史，应用时保留；旧 pending/in_progress 任务不迁移；
- `confirmed=False` 只保存预览 artifact，不修改档案；确认后才应用。
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from ...models import Adjustment, CareerProfile, TaskStatus
from ...tools.dashboard import render_roadmap_map, write_html
from ...tools.errors import InvalidJsonError
from ...tools.profile import get_active_profile_name, load_profile, profile_lock, save_profile
from ...tools.roadmap import parse_roadmap
from ...tools.tool_helpers import _parse_json_param
from ..artifacts.models import ArtifactMeta, ExecutionPlan, PlanChange
from ..artifacts.store import ArtifactStore
from ..orchestrator import state_machine
from .base import StageContext, StageResult

STAGE_ID = state_machine.STAGE_EXECUTION_PLAN
REQUIRES = ("requirement_profile", "baseline_plan", "profile")
PRODUCES = "execution_plan"

_FINISHED_STATUSES = (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
_PHASE_TYPES = ("learn", "project", "intern", "research")
_PRIORITIES = ("high", "medium", "low")

_ALIGNMENT_METHODOLOGY: dict[str, Any] = {
    "name": "执行方案校准",
    "version": "1.0",
    "goal": "把基线路线图升级为执行版：对齐企业真实需求，保留已完成历史，只重排未来任务。",
    "principles": [
        "每条变更必须引用 RequirementProfile 中的 evidence_ids；没有证据的变更不提。",
        "阶段数由需求与基线差距决定（通常 3-6 段），不为凑数强行 4 段。",
        "completed/skipped 任务是历史，不能删除、改写或重新排进未来阶段。",
        "旧 pending/in_progress 任务不迁移，执行版按新 roadmap 重新生成任务。",
        "只设计 roadmap 与 changes，不抓取、不统计、不直接写档案。",
        "产品不规划时间：任务名不带周期词，保持一次坐下可完成的粒度。",
        "拿不到真实 JD 时保持占位并如实说明：后续企业适配阶段会按目标企业与届别自动抓取，"
        "也可先用 import_jd 补充；绝不编造岗位要求。",
    ],
    "steps": [
        {
            "name": "对齐需求",
            "action": "从 requirement 中挑出高频率、公司特定要求与硬门槛，对照基线各阶段目标。",
        },
        {
            "name": "保留历史",
            "action": "列出 completed_evidence，确认新 roadmap 不重复已完成内容，也不删除历史任务。",
        },
        {
            "name": "设计执行版",
            "action": "按目标岗位证据缺口重排阶段与任务；每个改动写成一条带 evidence_ids 的 change。",
        },
        {
            "name": "写 diff_summary",
            "action": "用一段话说明改了什么、为什么改，供用户确认预览。",
        },
    ],
    "output_schema": {
        "requirement_profile_id": "requirement artifact id",
        "strategy_summary": "执行版整体策略",
        "roadmap": {
            "strategy_summary": "与顶层一致",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn|project|intern|research",
                    "name": "阶段名",
                    "goal": "阶段目标",
                    "kpi": {"metric": "", "target": "", "evidence": ""},
                    "milestones": [
                        {
                            "name": "里程碑",
                            "done_criteria": "",
                            "tasks": [{"name": "", "description": "", "priority": "high|medium|low"}],
                        }
                    ],
                }
            ],
        },
        "changes": [
            {
                "type": "add_task|modify_task|remove_task|reorder_tasks|"
                "modify_phase|add_phase|remove_phase|reorder_phases",
                "phase_id": "",
                "task_id": "",
                "details": {},
                "reason": "",
                "evidence_ids": ["JD001"],
            }
        ],
        "diff_summary": "本次校准的差异摘要",
    },
}


class ExecutionPlanError(Exception):
    """阶段 9 的可预期错误；工具层转成 error_response。"""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def plan_execution_alignment(requirement_profile_id: str = "") -> dict[str, Any]:
    """返回校准方法论、基线路线图、已完成证据与对齐提示（不写档案）。"""
    return _plan(get_active_profile_name(), requirement_profile_id)


def save_execution_alignment(
    alignment_json: str | dict[str, Any], confirmed: bool = False
) -> dict[str, Any]:
    """校验 LLM 对齐方案；`confirmed=False` 只预览，`True` 才应用到档案。"""
    return _save(get_active_profile_name(), alignment_json, confirmed)


def run(ctx: StageContext, inputs: dict[str, Any]) -> StageResult:
    """阶段协议入口：action=plan 生成提示，action=save 保存/应用方案。"""
    action = str(inputs.get("action") or "plan").strip().lower()
    try:
        if action == "save":
            alignment = inputs.get("alignment_json", inputs.get("alignment", {}))
            payload = _save(
                ctx.profile_name,
                alignment,
                bool(inputs.get("confirmed", ctx.user_confirmed)),
            )
            applied = bool(payload.get("applied"))
            return StageResult(
                status="ok" if applied else "needs_confirmation",
                artifact_id=str(payload.get("execution_plan_id") or ""),
                message=str(payload.get("message") or ""),
                next_stage=state_machine.STAGE_EXECUTING if applied else STAGE_ID,
                warnings=[str(item) for item in payload.get("warnings") or []],
            )
        payload = _plan(ctx.profile_name, str(inputs.get("requirement_profile_id") or ""))
        return StageResult(
            status="ok",
            message=str(payload.get("message") or ""),
            next_stage=STAGE_ID,
        )
    except ExecutionPlanError as exc:
        return StageResult(status="failed", message=f"{exc.code}: {exc.message}")


def validate(artifact: BaseModel) -> list[str]:
    """校验 ExecutionPlan artifact 的结构与证据引用；返回问题列表。"""
    if not isinstance(artifact, ExecutionPlan):
        return ["artifact 必须是 ExecutionPlan"]
    issues: list[str] = []
    if artifact.meta.stage != STAGE_ID:
        issues.append(f"meta.stage 必须是 {STAGE_ID}")
    if not artifact.requirement_profile_id:
        issues.append("requirement_profile_id 不能为空")
    issues.extend(_roadmap_issues(artifact.roadmap))
    for index, change in enumerate(artifact.changes):
        if not _clean_evidence_ids(change.evidence_ids):
            issues.append(f"changes[{index}] 缺少 evidence_ids")
    if not artifact.diff_summary.strip():
        issues.append("diff_summary 不能为空")
    return issues


def _plan(profile_name: str, requirement_profile_id: str) -> dict[str, Any]:
    profile = load_profile(profile_name)
    store = ArtifactStore()
    requirement = _resolve_requirement(store, profile_name, requirement_profile_id)
    baseline = _roadmap_of(profile.plan)
    if not _has_phases(baseline):
        raise ExecutionPlanError(
            "MISSING_BASELINE_PLAN",
            "档案里还没有基线路线图（profile.plan.phases 为空）——请先 save_roadmap 生成基线。",
            {"missing": "plan.roadmap.phases"},
        )

    summary = _summarize_requirement(requirement)
    completed = _extract_completed_evidence(profile)
    capability = _capability_evidence(profile)
    requirement_id = str(summary.get("requirement_profile_id") or "")
    return {
        "status": "ok",
        "profile_name": profile_name,
        "requirement": summary,
        "baseline_plan": baseline,
        "completed_evidence": completed,
        "capability_evidence": capability,
        "methodology": _ALIGNMENT_METHODOLOGY,
        "alignment_prompt": _alignment_prompt(requirement_id, summary),
        "message": (
            "已准备执行方案校准上下文。请基于 requirement 与 baseline_plan 设计执行版路线图，"
            "为每条 change 标注 evidence_ids，然后调用 save_execution_alignment 预览；"
            "用户确认后再传 confirmed=true 应用。"
        ),
        "next_steps": ["save_execution_alignment"],
    }


def _save(
    profile_name: str,
    alignment_json: str | dict[str, Any],
    confirmed: bool,
) -> dict[str, Any]:
    data = _parse_alignment(alignment_json)
    requirement_profile_id = str(data.get("requirement_profile_id") or "").strip()
    if not requirement_profile_id:
        raise ExecutionPlanError(
            "INVALID_PARAM",
            "requirement_profile_id 不能为空——请回传 plan_execution_alignment 提供的 RequirementProfile id。",
        )

    profile = load_profile(profile_name)
    store = ArtifactStore()
    requirement = _resolve_requirement(store, profile_name, requirement_profile_id)
    _check_requirement_chain(profile, requirement, requirement_profile_id)

    roadmap_raw = data.get("roadmap")
    if not isinstance(roadmap_raw, dict):
        raise ExecutionPlanError(
            "INVALID_ROADMAP",
            "roadmap 必须是 JSON 对象（包含 phases）。",
            {"received": type(roadmap_raw).__name__},
        )
    strategy_summary = str(
        data.get("strategy_summary") or roadmap_raw.get("strategy_summary") or ""
    ).strip()
    if not strategy_summary:
        raise ExecutionPlanError("INVALID_PARAM", "strategy_summary 不能为空。")
    roadmap = _normalize_roadmap(roadmap_raw, strategy_summary)

    changes = _parse_changes(data.get("changes"))
    _assert_known_evidence(changes, requirement)
    diff_summary = str(data.get("diff_summary") or "").strip()
    if not diff_summary:
        raise ExecutionPlanError("INVALID_PARAM", "diff_summary 不能为空——请说明本次校准改了什么。")

    roadmap_hash = _hash_value(roadmap)
    changes_hash = _hash_value([change.model_dump() for change in changes])
    if confirmed:
        existing = _find_applied_alignment(
            store,
            profile_name,
            requirement_profile_id,
            roadmap_hash,
            changes_hash,
        )
        if existing is not None:
            return _applied_alignment_payload(
                existing, profile, requirement_profile_id
            )

    baseline = _roadmap_of(profile.plan)
    if not _has_phases(baseline):
        raise ExecutionPlanError(
            "MISSING_BASELINE_PLAN",
            "应用前发现档案基线路线图缺失——请先恢复或重新生成基线路线图。",
            {"missing": "plan.roadmap.phases"},
        )

    completed = _extract_completed_evidence(profile)
    removed = _pending_tasks(profile)
    warnings = _evidence_warnings(changes, requirement)
    baseline_plan_id = _resolve_baseline_plan_id(store, profile_name, profile)

    meta = ArtifactMeta(
        id=store.new_id("ep"),
        stage=STAGE_ID,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
        inputs={
            "requirement_profile_id": requirement_profile_id,
            "baseline": "profile.plan",
            "baseline_plan_id": baseline_plan_id,
        },
        validation={
            "confirmed": confirmed,
            "applied": confirmed,
            "change_count": len(changes),
            "preserved_task_count": len(completed),
            "removed_task_count": len(removed),
            "warnings": warnings,
            "roadmap_hash": roadmap_hash,
            "changes_hash": changes_hash,
        },
    )
    artifact = ExecutionPlan(
        meta=meta,
        baseline_plan_id=baseline_plan_id,
        requirement_profile_id=requirement_profile_id,
        strategy_summary=strategy_summary,
        roadmap=roadmap,
        completed_evidence=completed,
        changes=changes,
        diff_summary=diff_summary,
        applied=confirmed,
    )

    preview = {
        "status": "needs_confirmation" if not confirmed else "ok",
        "applied": confirmed,
        "execution_plan_id": meta.id,
        "baseline": _roadmap_overview(baseline),
        "proposed": _roadmap_overview(roadmap),
        "changes": [change.model_dump() for change in changes],
        "change_counts": _change_counts(changes),
        "diff_summary": diff_summary,
        "preserved_tasks": _task_briefs(completed),
        "removed_tasks": _task_briefs(removed),
        "warnings": warnings,
    }

    if not confirmed:
        store.save(artifact)
        preview["message"] = (
            "预览已生成，档案未修改。确认无误后调用 "
            "save_execution_alignment(alignment_json=..., confirmed=true) 应用："
            f"将保留 {len(completed)} 个已完成/已跳过任务，移除 {len(removed)} 个旧 pending/in_progress 任务。"
        )
        preview["next_steps"] = ["save_execution_alignment"]
        return preview

    with profile_lock(profile_name):
        current = load_profile(profile_name)
        current_baseline = _roadmap_of(current.plan)
        if not _has_phases(current_baseline):
            raise ExecutionPlanError(
                "MISSING_BASELINE_PLAN",
                "应用时发现档案基线路线图缺失——请先恢复或重新生成基线路线图。",
                {"missing": "plan.roadmap.phases"},
            )
        current.save_plan_snapshot("company_alignment")
        preserved_tasks = [task for task in current.tasks if task.status in _FINISHED_STATUSES]
        removed_tasks = [task for task in current.tasks if task.status not in _FINISHED_STATUSES]
        current.tasks = preserved_tasks
        new_plan, dropped_plan_keys = _merge_plan_keys(current.plan, roadmap)
        current.plan = new_plan
        if dropped_plan_keys:
            meta.validation["dropped_plan_keys"] = dropped_plan_keys

        now = datetime.now().isoformat()
        current.plan_saved_at = now
        current.section_updated_at["plan"] = now
        adjustment = Adjustment(
            trigger="company_alignment",
            trigger_type="event",
            reason=diff_summary,
            changes=[change.model_dump() for change in changes],
        )
        current.add_adjustment(adjustment)

        core_state = dict(current.core_state) if isinstance(current.core_state, dict) else {}
        core_state.update({
            "stage": "executing",
            "requirement_profile_id": requirement_profile_id,
            "execution_plan_id": meta.id,
            "updated_at": now,
        })
        current.core_state = core_state
        save_profile(current, profile_name)

    map_path = ""
    map_error = ""
    try:
        map_path = write_html(render_roadmap_map(current), kind="roadmap")
    except Exception as exc:  # noqa: BLE001 - 地图刷新失败不阻断方案应用
        map_error = str(exc)

    meta.validation["map_path"] = map_path
    meta.validation["map_error"] = map_error
    store.save(artifact)

    preview.update({
        "status": "ok",
        "applied": True,
        "preserved_task_count": len(preserved_tasks),
        "removed_task_count": len(removed_tasks),
        "plan_history_versions": len(current.plan_history),
        "adjustment": adjustment.model_dump(),
        "core_state": dict(current.core_state),
        "map_path": map_path,
        "map_error": map_error,
        "message": (
            "执行方案已应用：profile.plan 已替换为执行版，plan_history 已保存快照；"
            f"保留 {len(preserved_tasks)} 个历史任务，移除 {len(removed_tasks)} 个旧任务。"
            + ("职业地图已刷新。" if map_path else f"职业地图刷新失败（不阻断）：{map_error}")
            + "接下来调用 generate_tasks 生成当前阶段任务。"
        ),
        "next_steps": ["get_next_tasks", "generate_tasks"],
    })
    return preview


def _resolve_requirement(
    store: ArtifactStore, profile_name: str, requirement_profile_id: str
) -> dict[str, Any]:
    if requirement_profile_id:
        data = store.load(requirement_profile_id)
        if not _is_stage(data, state_machine.STAGE_REQUIREMENT):
            raise ExecutionPlanError(
                "REQUIREMENT_NOT_FOUND",
                f"RequirementProfile「{requirement_profile_id}」不存在或类型不符。",
                {"requirement_profile_id": requirement_profile_id},
            )
    else:
        data = store.latest(profile_name, state_machine.STAGE_REQUIREMENT)
        if data is None:
            raise ExecutionPlanError(
                "MISSING_REQUIREMENT",
                "档案还没有 RequirementProfile——请先完成企业需求分析并保存。",
                {"missing": "requirement_profile"},
            )
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if str(meta.get("profile_name") or "") != profile_name:
        raise ExecutionPlanError(
            "REQUIREMENT_NOT_FOUND",
            "RequirementProfile 不属于当前档案，拒绝校准。",
            {"expected_profile": profile_name, "actual_profile": str(meta.get("profile_name") or "")},
        )
    return data


def _check_requirement_chain(
    profile: CareerProfile, requirement: dict[str, Any], requirement_profile_id: str
) -> None:
    core_state = profile.core_state if isinstance(profile.core_state, dict) else {}
    expected_requirement = str(core_state.get("requirement_profile_id") or "")
    if expected_requirement and expected_requirement != requirement_profile_id:
        raise ExecutionPlanError(
            "REQUIREMENT_MISMATCH",
            "提交的 RequirementProfile 与当前链路不一致，拒绝落库。",
            {"expected": expected_requirement, "received": requirement_profile_id},
        )
    expected_evidence = str(core_state.get("evidence_run_id") or "")
    actual_evidence = str(requirement.get("evidence_run_id") or "")
    if expected_evidence and actual_evidence and expected_evidence != actual_evidence:
        raise ExecutionPlanError(
            "REQUIREMENT_MISMATCH",
            "RequirementProfile 不属于当前 EvidenceRun，拒绝落库。",
            {"expected": expected_evidence, "received": actual_evidence},
        )


def _assert_known_evidence(
    changes: list[PlanChange], requirement: dict[str, Any]
) -> None:
    """拒绝引用 RequirementProfile 之外 evidence_ids 的变更。"""
    known = _known_evidence_ids(requirement)
    unknown = sorted(
        {
            evidence_id
            for change in changes
            for evidence_id in change.evidence_ids
            if evidence_id not in known
        }
    )
    if not unknown:
        return
    raise ExecutionPlanError(
        "UNKNOWN_EVIDENCE_ID",
        "变更引用了 RequirementProfile 中不存在的 evidence_ids，拒绝落库。",
        {"unknown_evidence_ids": unknown, "available_evidence_ids": sorted(known)},
    )


def _resolve_baseline_plan_id(
    store: ArtifactStore, profile_name: str, profile: CareerProfile
) -> str:
    """从 core_state 或 latest BaselinePlan 读取基线方案 id。"""
    core_state = profile.core_state if isinstance(profile.core_state, dict) else {}
    candidate = str(core_state.get("baseline_plan_id") or "").strip()
    if candidate:
        data = store.load(candidate)
        if _is_stage(data, state_machine.STAGE_BASELINE_PLAN):
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            if str(meta.get("profile_name") or "") == profile_name:
                return candidate
    latest = store.latest(profile_name, state_machine.STAGE_BASELINE_PLAN)
    if _is_stage(latest, state_machine.STAGE_BASELINE_PLAN):
        meta = latest.get("meta") if isinstance(latest.get("meta"), dict) else {}
        return str(meta.get("id") or "")
    return ""


def _merge_plan_keys(
    plan: Any, roadmap: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """保留 profile.plan 的非 roadmap 键；丢弃过期 current_detail 时返回标记。"""
    old_plan = plan if isinstance(plan, dict) else {}
    phase_ids = _phase_ids(roadmap)
    merged: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in old_plan.items():
        if key in ("roadmap", "phases"):
            continue
        if key == "current_detail":
            detail_phase = (
                str(value.get("phase_id") or "").strip()
                if isinstance(value, dict)
                else ""
            )
            if detail_phase and detail_phase not in phase_ids:
                dropped.append(key)
                continue
            merged[key] = copy.deepcopy(value)
            continue
        merged[key] = copy.deepcopy(value)
    merged["roadmap"] = roadmap
    return merged, dropped


def _phase_ids(roadmap: dict[str, Any]) -> set[str]:
    phases = roadmap.get("phases") if isinstance(roadmap.get("phases"), list) else []
    ids: set[str] = set()
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        ids.add(str(phase.get("id") or f"phase_{index + 1}"))
    return ids


def _hash_value(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = repr(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_applied_alignment(
    store: ArtifactStore,
    profile_name: str,
    requirement_profile_id: str,
    roadmap_hash: str,
    changes_hash: str,
) -> dict[str, Any] | None:
    """查找同一 requirement + roadmap + changes 的已应用执行方案（幂等）。"""
    for entry in store.list(profile_name, STAGE_ID):
        if not isinstance(entry, dict) or not entry.get("applied"):
            continue
        if str(entry.get("requirement_profile_id") or "") != requirement_profile_id:
            continue
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        validation = (
            meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
        )
        stored_roadmap_hash = str(validation.get("roadmap_hash") or "") or _hash_value(
            entry.get("roadmap") or {}
        )
        stored_changes_hash = str(validation.get("changes_hash") or "") or _hash_value(
            entry.get("changes") or []
        )
        if stored_roadmap_hash == roadmap_hash and stored_changes_hash == changes_hash:
            return entry
    return None


def _applied_alignment_payload(
    existing: dict[str, Any],
    profile: CareerProfile,
    requirement_profile_id: str,
) -> dict[str, Any]:
    """重复确认同一 alignment 时返回既有已应用方案，不重复写档案。"""
    meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    validation = (
        meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
    )
    roadmap = (
        existing.get("roadmap") if isinstance(existing.get("roadmap"), dict) else {}
    )
    changes = [item for item in existing.get("changes") or [] if isinstance(item, dict)]
    return {
        "status": "ok",
        "applied": True,
        "idempotent": True,
        "execution_plan_id": str(meta.get("id") or ""),
        "requirement_profile_id": requirement_profile_id,
        "baseline": {},
        "proposed": _roadmap_overview(roadmap),
        "changes": changes,
        "change_counts": _change_counts_raw(changes),
        "diff_summary": str(existing.get("diff_summary") or ""),
        "preserved_tasks": _task_briefs(_extract_completed_evidence(profile)),
        "removed_tasks": [],
        "warnings": [str(item) for item in validation.get("warnings") or []],
        "preserved_task_count": _as_int(validation.get("preserved_task_count")),
        "removed_task_count": _as_int(validation.get("removed_task_count")),
        "plan_history_versions": len(profile.plan_history),
        "adjustment": None,
        "core_state": (
            dict(profile.core_state) if isinstance(profile.core_state, dict) else {}
        ),
        "map_path": str(validation.get("map_path") or ""),
        "map_error": str(validation.get("map_error") or ""),
        "message": (
            "相同的执行方案（requirement_profile_id + roadmap + changes）已经应用过；"
            "本次不重复写入 plan_history / adjustments，也不重复删除任务。"
        ),
        "next_steps": ["get_next_tasks", "generate_tasks"],
    }


def _change_counts_raw(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for change in changes:
        key = str(change.get("type") or "")
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _parse_alignment(alignment_json: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(alignment_json, dict):
        return alignment_json
    if not isinstance(alignment_json, str):
        raise ExecutionPlanError(
            "INVALID_JSON",
            "执行方案必须是 JSON 对象或 JSON 字符串。",
            {"received": type(alignment_json).__name__},
        )
    try:
        return _parse_json_param(alignment_json, "执行方案")
    except InvalidJsonError as exc:
        raise ExecutionPlanError("INVALID_JSON", exc.message, exc.details) from exc


def _normalize_roadmap(raw: dict[str, Any], strategy_summary: str) -> dict[str, Any]:
    roadmap_in = copy.deepcopy(raw)
    roadmap_in["strategy_summary"] = strategy_summary
    issues = _roadmap_issues(roadmap_in)
    if issues:
        raise ExecutionPlanError(
            "INVALID_ROADMAP",
            "执行版路线图结构不合法。",
            {"issues": issues},
        )
    parsed = parse_roadmap(json.dumps({"roadmap": roadmap_in}, ensure_ascii=False))
    roadmap = parsed.get("roadmap")
    if not isinstance(roadmap, dict) or not _has_phases(roadmap):
        raise ExecutionPlanError(
            "INVALID_ROADMAP",
            "执行版路线图解析失败（phases 为空）。",
            {"issues": ["roadmap.phases 必须是非空数组"]},
        )
    roadmap["strategy_summary"] = strategy_summary
    return roadmap


def _parse_changes(raw: Any) -> list[PlanChange]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ExecutionPlanError(
            "INVALID_CHANGES",
            "changes 必须是数组。",
            {"received": type(raw).__name__},
        )
    changes: list[PlanChange] = []
    issues: list[str] = []
    for index, item in enumerate(raw):
        prefix = f"changes[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{prefix} 必须是对象")
            continue
        try:
            change = PlanChange.model_validate(item)
        except ValidationError as exc:
            issues.append(f"{prefix}.type 不合法：{exc.errors()[0].get('msg', '')}")
            continue
        evidence_ids = _clean_evidence_ids(change.evidence_ids)
        if not evidence_ids:
            issues.append(f"{prefix} 缺少 evidence_ids——没有证据的变更不允许落库")
            continue
        change.evidence_ids = evidence_ids
        issues.extend(_change_detail_issues(change, prefix))
        changes.append(change)
    if issues:
        raise ExecutionPlanError(
            "INVALID_CHANGES",
            "变更清单不合法。",
            {"issues": issues},
        )
    return changes


def _change_detail_issues(change: PlanChange, prefix: str) -> list[str]:
    details = change.details or {}
    issues: list[str] = []
    if change.type == "add_task" and not str(details.get("name") or "").strip():
        issues.append(f"{prefix}.details.name 必填（add_task）")
    if change.type in ("modify_task", "remove_task") and not change.task_id:
        issues.append(f"{prefix}.task_id 必填（{change.type}）")
    if change.type == "add_phase" and not str(details.get("name") or "").strip():
        issues.append(f"{prefix}.details.name 必填（add_phase）")
    if change.type in ("modify_phase", "remove_phase") and not change.phase_id:
        issues.append(f"{prefix}.phase_id 必填（{change.type}）")
    if change.type in ("reorder_tasks", "reorder_phases") and not details:
        issues.append(f"{prefix}.details 必填顺序说明（{change.type}）")
    return issues


def _roadmap_issues(roadmap: Any) -> list[str]:
    if not isinstance(roadmap, dict):
        return ["roadmap 必须是对象"]
    phases = roadmap.get("phases")
    if not isinstance(phases, list) or not phases:
        return ["roadmap.phases 必须是非空数组"]
    issues: list[str] = []
    for phase_index, phase in enumerate(phases):
        prefix = f"phases[{phase_index}]"
        if not isinstance(phase, dict):
            issues.append(f"{prefix} 必须是对象")
            continue
        if not str(phase.get("name") or "").strip():
            issues.append(f"{prefix}.name 不能为空")
        if not str(phase.get("goal") or "").strip():
            issues.append(f"{prefix}.goal 不能为空")
        phase_type = str(phase.get("type") or "learn")
        if phase_type not in _PHASE_TYPES:
            issues.append(f"{prefix}.type「{phase_type}」不合法（{'/'.join(_PHASE_TYPES)}）")
        milestones = phase.get("milestones", [])
        if milestones is None:
            milestones = []
        if not isinstance(milestones, list):
            issues.append(f"{prefix}.milestones 必须是数组")
            continue
        for ms_index, milestone in enumerate(milestones):
            ms_prefix = f"{prefix}.milestones[{ms_index}]"
            if not isinstance(milestone, dict):
                issues.append(f"{ms_prefix} 必须是对象")
                continue
            if not str(milestone.get("name") or "").strip():
                issues.append(f"{ms_prefix}.name 不能为空")
            tasks = milestone.get("tasks", [])
            if tasks is None:
                tasks = []
            if not isinstance(tasks, list):
                issues.append(f"{ms_prefix}.tasks 必须是数组")
                continue
            for task_index, task in enumerate(tasks):
                task_prefix = f"{ms_prefix}.tasks[{task_index}]"
                if not isinstance(task, dict):
                    issues.append(f"{task_prefix} 必须是对象")
                    continue
                if not str(task.get("name") or "").strip():
                    issues.append(f"{task_prefix}.name 不能为空")
                priority = str(task.get("priority") or "medium")
                if priority not in _PRIORITIES:
                    issues.append(f"{task_prefix}.priority「{priority}」不合法（high/medium/low）")
    return issues


def _extract_completed_evidence(profile: CareerProfile) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for task in profile.tasks:
        if task.status not in _FINISHED_STATUSES:
            continue
        entries.append({
            "task_id": task.id,
            "name": task.name,
            "phase_id": task.phase_id,
            "milestone_id": task.milestone_id,
            "status": task.status,
            "completed_at": task.completed_at or "",
            "how_to": list(task.how_to or []),
            "done_criteria": task.done_criteria or "",
        })
    return entries


def _pending_tasks(profile: CareerProfile) -> list[Any]:
    return [task for task in profile.tasks if task.status not in _FINISHED_STATUSES]


def _capability_evidence(profile: CareerProfile) -> list[dict[str, Any]]:
    raw = profile.have.get("capability_evidence") if isinstance(profile.have, dict) else None
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _summarize_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    meta = requirement.get("meta") if isinstance(requirement.get("meta"), dict) else {}
    hard = requirement.get("hard_requirements")
    gaps = requirement.get("gaps")
    interpretation = requirement.get("interpretation")
    return {
        "requirement_profile_id": str(meta.get("id") or ""),
        "evidence_run_id": str(requirement.get("evidence_run_id") or ""),
        "sample_size_jd": _as_int(requirement.get("sample_size_jd")),
        "sample_size_interview": _as_int(requirement.get("sample_size_interview")),
        "confidence_jd": str(requirement.get("confidence_jd") or ""),
        "confidence_interview": str(requirement.get("confidence_interview") or ""),
        "high_frequency": _compact_items(requirement.get("high_frequency")),
        "company_specific": _compact_items(requirement.get("company_specific")),
        "interview_topics": _compact_items(requirement.get("interview_topics")),
        "nice_to_have": _compact_items(requirement.get("nice_to_have")),
        "hard_requirements": [item for item in hard if isinstance(item, dict)]
        if isinstance(hard, list) else [],
        "gaps": [str(item) for item in gaps] if isinstance(gaps, list) else [],
        "interpretation": interpretation if isinstance(interpretation, dict) else {},
    }


_ITEM_FIELDS = (
    "term",
    "category",
    "jd_count",
    "jd_frequency",
    "company_count",
    "company_frequency",
    "evidence_ids",
)


def _compact_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for field in _ITEM_FIELDS:
            if field in item:
                row[field] = item[field]
        items.append(row)
    return items


def _known_evidence_ids(requirement: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("high_frequency", "company_specific", "interview_topics", "nice_to_have"):
        for item in requirement.get(key) or []:
            if not isinstance(item, dict):
                continue
            ids.update(_clean_evidence_ids(item.get("evidence_ids")))
    for item in requirement.get("hard_requirements") or []:
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip():
            ids.add(str(item["evidence_id"]).strip())
    return ids


def _evidence_warnings(changes: list[PlanChange], requirement: dict[str, Any]) -> list[str]:
    referenced = [evidence_id for change in changes for evidence_id in change.evidence_ids]
    if not referenced:
        return []
    known = _known_evidence_ids(requirement)
    if not known:
        return ["RequirementProfile 未包含 evidence_ids，无法核对变更引用来源"]
    unknown = sorted({evidence_id for evidence_id in referenced if evidence_id not in known})
    if not unknown:
        return []
    preview = "、".join(unknown[:5])
    suffix = " 等" if len(unknown) > 5 else ""
    return [f"变更引用了 RequirementProfile 中不存在的 evidence_ids：{preview}{suffix}（请核对来源）"]


def _alignment_prompt(requirement_profile_id: str, requirement_summary: dict[str, Any]) -> dict[str, Any]:
    known_ids: set[str] = set()
    for key in ("high_frequency", "company_specific", "interview_topics", "nice_to_have"):
        for item in requirement_summary.get(key) or []:
            if isinstance(item, dict):
                known_ids.update(_clean_evidence_ids(item.get("evidence_ids")))
    for item in requirement_summary.get("hard_requirements") or []:
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip():
            known_ids.add(str(item["evidence_id"]).strip())
    return {
        "task": (
            "以 baseline_plan 为骨架设计执行版路线图：按 RequirementProfile 的真实需求调整未来阶段；"
            "completed/skipped 任务是历史，不得删除或改写。"
        ),
        "requirement_profile_id": requirement_profile_id,
        "available_evidence_ids": sorted(known_ids),
        "rules": [
            "每条 change 必须引用 requirement 中出现过的 evidence_ids；没有证据的变更不要提。",
            "阶段数由需求与基线差距决定（通常 3-6 段），不为凑数强行 4 段。",
            "completed/skipped 任务不迁移为新任务，也不删除；新 roadmap 只面向未来。",
            "旧 pending/in_progress 任务会被代码移除，执行版由新 roadmap 重新生成任务。",
            "roadmap 与基线同构：strategy_summary + phases（phase 有 name/goal，milestones 带 tasks）。",
            "任务名不写时间周期（每周/每天等），保持一次坐下可完成的粒度。",
            "拿不到真实 JD 时保持占位并如实说明，后续自动抓取会按目标企业与届别补齐；也可用 import_jd 补充。",
            "只输出 JSON，不要直接修改档案；应用由代码在用户确认后执行。",
        ],
        "change_types": [
            "add_task",
            "modify_task",
            "remove_task",
            "reorder_tasks",
            "modify_phase",
            "add_phase",
            "remove_phase",
            "reorder_phases",
        ],
        "output_json": {
            "requirement_profile_id": requirement_profile_id,
            "strategy_summary": "",
            "roadmap": {
                "strategy_summary": "",
                "phases": [
                    {
                        "type": "project",
                        "name": "",
                        "goal": "",
                        "kpi": {"metric": "", "target": "", "evidence": ""},
                        "milestones": [
                            {
                                "name": "",
                                "done_criteria": "",
                                "tasks": [
                                    {"name": "", "description": "", "priority": "high"}
                                ],
                            }
                        ],
                    }
                ],
            },
            "changes": [
                {
                    "type": "add_task",
                    "phase_id": "phase_1",
                    "task_id": "",
                    "details": {"name": ""},
                    "reason": "",
                    "evidence_ids": [""],
                }
            ],
            "diff_summary": "",
        },
    }


def _roadmap_of(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    inner = plan.get("roadmap")
    if isinstance(inner, dict) and "phases" in inner:
        return inner
    if "phases" in plan:
        return plan
    return {}


def _has_phases(roadmap: Any) -> bool:
    return isinstance(roadmap, dict) and isinstance(roadmap.get("phases"), list) and bool(roadmap["phases"])


def _roadmap_overview(roadmap: dict[str, Any]) -> dict[str, Any]:
    phases = roadmap.get("phases") if isinstance(roadmap, dict) else []
    rows: list[dict[str, Any]] = []
    task_total = 0
    for index, phase in enumerate(phases if isinstance(phases, list) else []):
        if not isinstance(phase, dict):
            continue
        milestones = phase.get("milestones") if isinstance(phase.get("milestones"), list) else []
        task_count = 0
        for milestone in milestones:
            if not isinstance(milestone, dict):
                continue
            tasks = milestone.get("tasks")
            if isinstance(tasks, list):
                task_count += sum(1 for task in tasks if isinstance(task, dict))
        task_total += task_count
        rows.append({
            "id": str(phase.get("id") or f"phase_{index + 1}"),
            "name": str(phase.get("name") or ""),
            "goal": str(phase.get("goal") or ""),
            "milestone_count": len(milestones),
            "task_count": task_count,
        })
    return {"phase_count": len(rows), "task_count": task_total, "phases": rows}


def _change_counts(changes: list[PlanChange]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.type] = counts.get(change.type, 0) + 1
    return counts


def _task_briefs(tasks: list[Any]) -> list[dict[str, str]]:
    briefs: list[dict[str, str]] = []
    for task in tasks:
        if isinstance(task, dict):
            briefs.append({
                "task_id": str(task.get("task_id") or task.get("id") or ""),
                "name": str(task.get("name") or ""),
                "status": str(task.get("status") or ""),
            })
            continue
        briefs.append({
            "task_id": str(getattr(task, "id", "") or ""),
            "name": str(getattr(task, "name", "") or ""),
            "status": str(getattr(task, "status", "") or ""),
        })
    return briefs


def _clean_evidence_ids(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_stage(data: Any, stage: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    return isinstance(meta, dict) and meta.get("stage") == stage


__all__ = [
    "PRODUCES",
    "REQUIRES",
    "STAGE_ID",
    "ExecutionPlanError",
    "plan_execution_alignment",
    "run",
    "save_execution_alignment",
    "validate",
]
