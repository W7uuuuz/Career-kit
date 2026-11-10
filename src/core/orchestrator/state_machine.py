"""阶段状态机——根据档案 core_state 与 artifact 事实推导下一步。

只读：不写档案、不落库。解析逻辑统一放在 ``core.progress``：
artifact 优先按 core_state 中的 id 解析，缺失时回退到该阶段的 latest；
下游 artifact 必须引用上游 artifact id，且 meta.profile_name 必须是当前档案。

12 阶段顺序：档案 → 目标 → 市场基线 → 差距 → 基线方案 → 企业池 →
证据 → 需求 → 执行方案 → 执行状态。阶段 11/12（投递、复盘）是可选阶段，
不阻塞执行；执行状态就绪后只作为 optional_next_tools 推荐。
"""

from __future__ import annotations

from typing import Any

from ...tools.profile import load_profile
from ..artifacts.store import ArtifactStore
from ..progress import (
    ARTIFACT_KEYS,
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
    downstream_exists,
    resolve_artifact,
    resolve_progress,
)

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


def next_action(profile_name: str) -> dict[str, Any]:
    """返回当前档案的下一步：阶段、建议工具、原因与已解析的 artifact ids。"""
    profile = load_profile(profile_name)
    store = ArtifactStore()
    progress = resolve_progress(profile, store, profile_name)
    return {
        "stage": progress["stage"],
        "next_tool": progress["next_tool"],
        "reason": progress["reason"],
        "artifact_ids": progress["artifact_ids"],
        "optional_next_tools": progress["optional_next_tools"],
    }


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
