"""阶段状态机——根据档案 core_state 与 artifact 事实推导下一步。

只读：不写档案、不落库。artifact 优先按 core_state 中的 id 解析，
缺失时回退到该阶段的 latest；下游 artifact 必须引用上游 artifact id。
"""

from __future__ import annotations

from typing import Any

from ...tools.profile import load_profile
from ..artifacts.store import ArtifactStore

STAGE_COMPANY_POOL = "company_pool"
STAGE_EVIDENCE = "evidence"
STAGE_REQUIREMENT = "requirement"
STAGE_EXECUTION_PLAN = "execution_plan"
STAGE_EXECUTING = "executing"

_ARTIFACT_KEYS = (
    "company_pool_id",
    "evidence_run_id",
    "requirement_profile_id",
    "execution_plan_id",
)


def next_action(profile_name: str) -> dict[str, Any]:
    """返回当前档案的下一步：阶段、建议工具、原因与已解析的 artifact ids。"""
    profile = load_profile(profile_name)
    core_state = getattr(profile, "core_state", {})
    if not isinstance(core_state, dict):
        core_state = {}
    store = ArtifactStore()
    artifact_ids: dict[str, str] = dict.fromkeys(_ARTIFACT_KEYS, "")

    pool = _resolve(
        store, profile_name, STAGE_COMPANY_POOL, str(core_state.get("company_pool_id") or "")
    )
    if pool is None:
        return _action(STAGE_COMPANY_POOL, "select_target_companies", "尚未生成 CompanyPool", artifact_ids)
    artifact_ids["company_pool_id"] = _artifact_id(pool)
    if not _confirmed(pool):
        return _action(STAGE_COMPANY_POOL, "select_target_companies", "CompanyPool 尚未确认", artifact_ids)

    evidence = _resolve(store, profile_name, STAGE_EVIDENCE, str(core_state.get("evidence_run_id") or ""))
    if evidence is None or not _references(evidence, "company_pool_id", artifact_ids["company_pool_id"]):
        reason = "缺少与当前 CompanyPool 匹配的 EvidenceRun"
        return _action(STAGE_EVIDENCE, "collect_company_evidence", reason, artifact_ids)
    artifact_ids["evidence_run_id"] = _artifact_id(evidence)

    requirement = _resolve(
        store, profile_name, STAGE_REQUIREMENT, str(core_state.get("requirement_profile_id") or "")
    )
    if requirement is None or not _references(
        requirement, "evidence_run_id", artifact_ids["evidence_run_id"]
    ):
        reason = "缺少与当前 EvidenceRun 匹配的 RequirementProfile"
        return _action(STAGE_REQUIREMENT, "analyze_company_requirements", reason, artifact_ids)
    artifact_ids["requirement_profile_id"] = _artifact_id(requirement)

    plan = _resolve(
        store, profile_name, STAGE_EXECUTION_PLAN, str(core_state.get("execution_plan_id") or "")
    )
    if plan is None or not _references(
        plan, "requirement_profile_id", artifact_ids["requirement_profile_id"]
    ):
        reason = "缺少与当前 RequirementProfile 匹配的 ExecutionPlan"
        return _action(STAGE_EXECUTION_PLAN, "plan_execution_alignment", reason, artifact_ids)
    artifact_ids["execution_plan_id"] = _artifact_id(plan)

    if not bool(plan.get("applied")):
        reason = "ExecutionPlan 已生成但未应用"
        return _action(STAGE_EXECUTION_PLAN, "save_execution_alignment", reason, artifact_ids)
    return _action(STAGE_EXECUTING, "", "ExecutionPlan 已应用，进入执行期", artifact_ids)


def _action(stage: str, next_tool: str, reason: str, artifact_ids: dict[str, str]) -> dict[str, Any]:
    return {
        "stage": stage,
        "next_tool": next_tool,
        "reason": reason,
        "artifact_ids": dict(artifact_ids),
    }


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


def _artifact_id(artifact: dict[str, Any]) -> str:
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
    "STAGE_COMPANY_POOL",
    "STAGE_EVIDENCE",
    "STAGE_EXECUTING",
    "STAGE_EXECUTION_PLAN",
    "STAGE_REQUIREMENT",
    "next_action",
]
