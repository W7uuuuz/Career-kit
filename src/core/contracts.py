"""阶段契约矩阵（Phase 1 影子模式）。

``STAGE_CONTRACTS`` 把每个阶段的必需上游、产物、就绪判定与下一步工具收口成
一张表；``requires`` 与 ``core.progress._UPSTREAM_REFS`` 保持一致，避免进度
解析与契约表各自维护一套上游关系。

``ready`` 只读 artifact 映射（stage -> artifact dict），不读 profile 的临时
字段。

这些 ``ready`` 谓词是阶段就绪的唯一判定：``core.state`` 与 ``core.progress``
都直接复用。``STAGE_PROFILE`` 的 next_tool 是 ``finalize_profile``；EMPTY 是
尚未解析出 profile artifact 的 pre-stage 状态，由 ``core.state`` 在 profile
contract 之前判定，不属于 profile contract。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .progress import (
    _UPSTREAM_REFS,
    STAGE_BASELINE_PLAN,
    STAGE_COMPANY_POOL,
    STAGE_EVIDENCE,
    STAGE_EXECUTION,
    STAGE_EXECUTION_PLAN,
    STAGE_GAP,
    STAGE_KEYS,
    STAGE_MARKET,
    STAGE_PROFILE,
    STAGE_REQUIREMENT,
    STAGE_TARGET,
)


@dataclass(frozen=True)
class StageContract:
    """单个阶段的契约：上游、产物、就绪判定与下一步工具。

    ``ready`` 只读 artifact；EMPTY 不是阶段契约，而是 pre-stage 状态。
    """

    stage: str
    stage_index: int
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    ready: Callable[[Mapping[str, Any]], bool]
    next_tool: str
    skippable: bool = False


def _requires(stage: str) -> tuple[str, ...]:
    return tuple(field for _stage, field, _where in _UPSTREAM_REFS.get(stage, ()))


def _produces(stage: str) -> tuple[str, ...]:
    return (STAGE_KEYS[stage],)


def _artifact(
    artifacts: Mapping[str, Any], stage: str
) -> dict[str, Any] | None:
    value = artifacts.get(stage)
    return value if isinstance(value, dict) else None


def _artifact_id(artifact: dict[str, Any] | None) -> str:
    if not isinstance(artifact, dict):
        return ""
    meta = artifact.get("meta")
    return str(meta.get("id") or "") if isinstance(meta, dict) else ""


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


def _current_target_id(artifacts: Mapping[str, Any]) -> str:
    return _artifact_id(_artifact(artifacts, STAGE_TARGET))


def _target_matches(artifact: dict[str, Any], artifacts: Mapping[str, Any]) -> bool:
    """artifact 记录的 target_spec_id 必须指向当前 TargetSpec。

    旧 artifact 没有 target_spec_id 时保持兼容；一旦写入就必须匹配，
    目标变化后旧 gap/baseline 不再 ready。
    """
    stored = _artifact_field(artifact, "target_spec_id", "inputs")
    if not stored:
        return True
    return stored == _current_target_id(artifacts)


def _upstream_ready(stage: str, artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, stage)
    if data is None:
        return False
    for upstream_stage, field, where in _UPSTREAM_REFS.get(stage, ()):
        expected = _artifact_id(_artifact(artifacts, upstream_stage))
        actual = _artifact_field(data, field, where)
        if not expected or actual != expected:
            return False
    return True


def _ready_profile(artifacts: Mapping[str, Any]) -> bool:
    return _artifact(artifacts, STAGE_PROFILE) is not None


def _ready_target(artifacts: Mapping[str, Any]) -> bool:
    return _upstream_ready(STAGE_TARGET, artifacts)


def _ready_market_baseline(artifacts: Mapping[str, Any]) -> bool:
    return _upstream_ready(STAGE_MARKET, artifacts)


def _ready_gap(artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, STAGE_GAP)
    if data is None or not _target_matches(data, artifacts):
        return False
    validation = _artifact_validation(data)
    if validation.get("market_skipped") is True:
        # 市场跳过：不要求 MarketBaseline，但必须指向当前 TargetSpec，
        # 且 ProfileSnapshot 必须指向当前快照。
        target_id = _artifact_field(data, "target_spec_id", "inputs")
        if not target_id or target_id != _current_target_id(artifacts):
            return False
        profile_id = _artifact_id(_artifact(artifacts, STAGE_PROFILE))
        actual = _artifact_field(data, "profile_snapshot_id", "body")
        return bool(profile_id) and actual == profile_id
    return _upstream_ready(STAGE_GAP, artifacts)


def _ready_baseline_plan(artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, STAGE_BASELINE_PLAN)
    if data is None or not _target_matches(data, artifacts):
        return False
    validation = _artifact_validation(data)
    if validation.get("imported") is True:
        # import_plan 路径：没有 GapReport，保留 validation 标记作为契约；
        # 当前已有 TargetSpec 时，记录过的 target_spec_id 必须一致。
        target_id = _artifact_field(data, "target_spec_id", "inputs")
        current_target = _current_target_id(artifacts)
        return not (current_target and target_id != current_target)
    if validation.get("market_skipped") is True:
        target_id = _artifact_field(data, "target_spec_id", "inputs")
        if not target_id or target_id != _current_target_id(artifacts):
            return False
        gap_id = _artifact_id(_artifact(artifacts, STAGE_GAP))
        actual = _artifact_field(data, "gap_report_id", "body")
        return bool(gap_id) and actual == gap_id and _ready_gap(artifacts)
    return _upstream_ready(STAGE_BASELINE_PLAN, artifacts)


def _ready_company_pool(artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, STAGE_COMPANY_POOL)
    if data is None or not _upstream_ready(STAGE_COMPANY_POOL, artifacts):
        return False
    meta = data.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    if isinstance(validation, dict) and validation.get("confirmed") is True:
        return True
    companies = data.get("companies")
    if not isinstance(companies, list):
        return False
    return any(
        isinstance(item, dict) and item.get("status") == "confirmed"
        for item in companies
    )


def _ready_evidence(artifacts: Mapping[str, Any]) -> bool:
    return _upstream_ready(STAGE_EVIDENCE, artifacts)


def _has_interpretation(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for item in value.values():
        if isinstance(item, str) and item.strip():
            return True
        if isinstance(item, (list, tuple, dict)) and item:
            return True
    return False


def _ready_requirement(artifacts: Mapping[str, Any]) -> bool:
    """D5：saved 或 interpretation 非空即可进入阶段 9。

    saved = ``validation`` 是非空 dict 且 ``status != "draft"``；
    validation 缺失/空 dict 且 interpretation 为空 → 未就绪。
    """
    data = _artifact(artifacts, STAGE_REQUIREMENT)
    if data is None or not _upstream_ready(STAGE_REQUIREMENT, artifacts):
        return False
    if _has_interpretation(data.get("interpretation")):
        return True
    meta = data.get("meta")
    validation = meta.get("validation") if isinstance(meta, dict) else None
    if not isinstance(validation, dict) or not validation:
        return False
    return str(validation.get("status") or "") != "draft"


def _ready_execution_plan(artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, STAGE_EXECUTION_PLAN)
    return (
        data is not None
        and _upstream_ready(STAGE_EXECUTION_PLAN, artifacts)
        and bool(data.get("applied"))
    )


def _ready_execution(artifacts: Mapping[str, Any]) -> bool:
    data = _artifact(artifacts, STAGE_EXECUTION)
    if data is None or not _upstream_ready(STAGE_EXECUTION, artifacts):
        return False
    plan = _artifact(artifacts, STAGE_EXECUTION_PLAN)
    return (
        _artifact_id(plan) != ""
        and str(data.get("execution_plan_id") or "") == _artifact_id(plan)
    )


STAGE_CONTRACTS: dict[str, StageContract] = {
    STAGE_PROFILE: StageContract(
        stage=STAGE_PROFILE,
        stage_index=1,
        requires=(),
        produces=_produces(STAGE_PROFILE),
        ready=_ready_profile,
        next_tool="finalize_profile",
    ),
    STAGE_TARGET: StageContract(
        stage=STAGE_TARGET,
        stage_index=2,
        requires=_requires(STAGE_TARGET),
        produces=_produces(STAGE_TARGET),
        ready=_ready_target,
        next_tool="intake(want)",
    ),
    STAGE_MARKET: StageContract(
        stage=STAGE_MARKET,
        stage_index=3,
        requires=_requires(STAGE_MARKET),
        produces=_produces(STAGE_MARKET),
        ready=_ready_market_baseline,
        next_tool="gather_research_data",
        skippable=True,
    ),
    STAGE_GAP: StageContract(
        stage=STAGE_GAP,
        stage_index=4,
        requires=_requires(STAGE_GAP),
        produces=_produces(STAGE_GAP),
        ready=_ready_gap,
        next_tool="analyze_gaps",
    ),
    STAGE_BASELINE_PLAN: StageContract(
        stage=STAGE_BASELINE_PLAN,
        stage_index=5,
        requires=_requires(STAGE_BASELINE_PLAN),
        produces=_produces(STAGE_BASELINE_PLAN),
        ready=_ready_baseline_plan,
        next_tool="generate_roadmap",
    ),
    STAGE_COMPANY_POOL: StageContract(
        stage=STAGE_COMPANY_POOL,
        stage_index=6,
        requires=_requires(STAGE_COMPANY_POOL),
        produces=_produces(STAGE_COMPANY_POOL),
        ready=_ready_company_pool,
        next_tool="select_target_companies",
        skippable=True,
    ),
    STAGE_EVIDENCE: StageContract(
        stage=STAGE_EVIDENCE,
        stage_index=7,
        requires=_requires(STAGE_EVIDENCE),
        produces=_produces(STAGE_EVIDENCE),
        ready=_ready_evidence,
        next_tool="collect_company_evidence",
        skippable=True,
    ),
    STAGE_REQUIREMENT: StageContract(
        stage=STAGE_REQUIREMENT,
        stage_index=8,
        requires=_requires(STAGE_REQUIREMENT),
        produces=_produces(STAGE_REQUIREMENT),
        ready=_ready_requirement,
        next_tool="save_requirement_profile",
    ),
    STAGE_EXECUTION_PLAN: StageContract(
        stage=STAGE_EXECUTION_PLAN,
        stage_index=9,
        requires=_requires(STAGE_EXECUTION_PLAN),
        produces=_produces(STAGE_EXECUTION_PLAN),
        ready=_ready_execution_plan,
        next_tool="save_execution_alignment",
    ),
    STAGE_EXECUTION: StageContract(
        stage=STAGE_EXECUTION,
        stage_index=10,
        requires=_requires(STAGE_EXECUTION),
        produces=_produces(STAGE_EXECUTION),
        ready=_ready_execution,
        next_tool="detail_current_phase",
    ),
}


__all__ = ["STAGE_CONTRACTS", "StageContract"]
