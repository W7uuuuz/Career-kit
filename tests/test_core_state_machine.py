"""12 阶段状态机回归——按 artifact 顺序推进、可选阶段不阻塞、旧档案兜底。

所有用例使用 tmp_path 隔离数据目录，不读写真实 ~/.career-kit。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths  # noqa: E402
from src.core.artifacts.models import (  # noqa: E402
    ApplicationState,
    ArtifactMeta,
    BaselinePlan,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    ExecutionPlan,
    ExecutionState,
    GapReport,
    MarketBaseline,
    ProfileSnapshot,
    RequirementProfile,
    ReviewReport,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.core.orchestrator import state_machine  # noqa: E402

PROFILE_NAME = "alice"

PREFIXES = {
    state_machine.STAGE_PROFILE: "pf",
    state_machine.STAGE_TARGET: "ts",
    state_machine.STAGE_MARKET: "mb",
    state_machine.STAGE_GAP: "gr",
    state_machine.STAGE_BASELINE_PLAN: "bp",
    state_machine.STAGE_COMPANY_POOL: "cp",
    state_machine.STAGE_EVIDENCE: "ev",
    state_machine.STAGE_REQUIREMENT: "rp",
    state_machine.STAGE_EXECUTION_PLAN: "ep",
    state_machine.STAGE_EXECUTION: "es",
}


class ProfileArtifact(ProfileSnapshot):
    meta: ArtifactMeta


class TargetArtifact(TargetSpec):
    meta: ArtifactMeta


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    return root


@pytest.fixture()
def store(data_dir: Path) -> ArtifactStore:
    return ArtifactStore()


@pytest.fixture()
def profile_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    data: dict[str, Any] = {
        "core_state": {},
        "want": {},
        "who": {},
        "have": {},
        "summary": "",
        "research": {},
        "gap": {},
        "plan": {},
        "tasks": [],
    }
    monkeypatch.setattr(
        state_machine,
        "load_profile",
        lambda name: SimpleNamespace(**data),
    )
    return data


def _meta(store: ArtifactStore, stage: str, profile_name: str = PROFILE_NAME) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(PREFIXES[stage]),
        stage=stage,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
    )


def _save_profile(store: ArtifactStore) -> str:
    return store.save(
        ProfileArtifact(
            meta=_meta(store, state_machine.STAGE_PROFILE),
            name="张三",
            who={"name": "张三"},
            summary="应届生",
        )
    )


def _latest_id(
    store: ArtifactStore, stage: str, profile_name: str = PROFILE_NAME
) -> str:
    data = store.latest(profile_name, stage)
    if not isinstance(data, dict):
        return ""
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return str(meta.get("id") or "")


def _save_target(store: ArtifactStore, profile_name: str = PROFILE_NAME) -> str:
    return store.save(
        TargetArtifact(
            meta=_meta(
                store,
                state_machine.STAGE_TARGET,
                profile_name,
            ).model_copy(
                update={"inputs": {"profile_id": _latest_id(store, state_machine.STAGE_PROFILE, profile_name)}}
            ),
            role="AI Agent 开发",
            city="北京",
        )
    )


def _save_market(store: ArtifactStore, profile_name: str = PROFILE_NAME) -> str:
    return store.save(
        MarketBaseline(
            meta=_meta(
                store, state_machine.STAGE_MARKET, profile_name
            ).model_copy(
                update={"inputs": {"target_spec_id": _latest_id(store, state_machine.STAGE_TARGET, profile_name)}}
            ),
            target_spec=TargetSpec(role="AI Agent 开发"),
        )
    )


def _save_gap(store: ArtifactStore, profile_name: str = PROFILE_NAME) -> str:
    return store.save(
        GapReport(
            meta=_meta(store, state_machine.STAGE_GAP, profile_name),
            profile_snapshot_id=_latest_id(store, state_machine.STAGE_PROFILE, profile_name),
            market_baseline_id=_latest_id(store, state_machine.STAGE_MARKET, profile_name),
            match_score=60,
        )
    )


def _save_baseline(store: ArtifactStore, profile_name: str = PROFILE_NAME) -> str:
    return store.save(
        BaselinePlan(
            meta=_meta(store, state_machine.STAGE_BASELINE_PLAN, profile_name),
            gap_report_id=_latest_id(store, state_machine.STAGE_GAP, profile_name),
            roadmap={"phases": []},
        )
    )


def _save_pool(
    store: ArtifactStore, confirmed: bool = True, profile_name: str = PROFILE_NAME
) -> str:
    return store.save(
        CompanyPool(
            meta=_meta(
                store, state_machine.STAGE_COMPANY_POOL, profile_name
            ).model_copy(
                update={"inputs": {"baseline_plan_id": _latest_id(store, state_machine.STAGE_BASELINE_PLAN, profile_name)}}
            ),
            target_spec=TargetSpec(role="AI Agent 开发"),
            companies=[
                CompanyEntry(
                    id="bytedance",
                    name="字节跳动",
                    tier="大厂",
                    industry="互联网",
                    scrapable=True,
                    status="confirmed" if confirmed else "recommended",
                )
            ],
        )
    )


def _save_evidence(store: ArtifactStore, company_pool_id: str) -> str:
    return store.save(
        EvidenceRun(
            meta=_meta(store, state_machine.STAGE_EVIDENCE),
            target_spec=TargetSpec(role="AI Agent 开发"),
            company_pool_id=company_pool_id,
        )
    )


def _save_requirement(store: ArtifactStore, evidence_run_id: str) -> str:
    return store.save(
        RequirementProfile(
            meta=_meta(store, state_machine.STAGE_REQUIREMENT),
            evidence_run_id=evidence_run_id,
        )
    )


def _save_plan(
    store: ArtifactStore, requirement_profile_id: str, applied: bool
) -> str:
    return store.save(
        ExecutionPlan(
            meta=_meta(store, state_machine.STAGE_EXECUTION_PLAN),
            requirement_profile_id=requirement_profile_id,
            applied=applied,
        )
    )


def _save_execution(store: ArtifactStore, execution_plan_id: str) -> str:
    return store.save(
        ExecutionState(
            meta=_meta(store, state_machine.STAGE_EXECUTION),
            execution_plan_id=execution_plan_id,
        )
    )


def _save_application(store: ArtifactStore) -> str:
    return store.save(
        ApplicationState(
            meta=ArtifactMeta(
                id=store.new_id("as"),
                stage=state_machine.STAGE_APPLICATIONS,
                profile_name=PROFILE_NAME,
                created_at=datetime.now().isoformat(),
            )
        )
    )


def _save_review(store: ArtifactStore) -> str:
    return store.save(
        ReviewReport(
            meta=ArtifactMeta(
                id=store.new_id("rr"),
                stage=state_machine.STAGE_REVIEW,
                profile_name=PROFILE_NAME,
                created_at=datetime.now().isoformat(),
            )
        )
    )


def test_empty_profile_starts_at_stage_one(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_PROFILE
    assert action["next_tool"] == "intake(section='bundle')"
    assert all(value == "" for value in action["artifact_ids"].values())
    assert action["optional_next_tools"] == []


def test_stages_follow_artifact_order(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    assert state_machine.next_action(PROFILE_NAME)["next_tool"] == "intake(section='bundle')"
    _save_profile(store)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_TARGET
    assert action["next_tool"] == "explore_goals"

    profile_state["want"] = {"target_role": "AI Agent 开发"}
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_TARGET
    assert action["next_tool"] == "intake(want)"
    _save_target(store)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_MARKET
    assert action["next_tool"] == "gather_research_data"
    _save_market(store)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_GAP
    assert action["next_tool"] == "analyze_gaps"
    _save_gap(store)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_BASELINE_PLAN
    assert action["next_tool"] == "generate_roadmap"
    _save_baseline(store)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert action["next_tool"] == "select_target_companies"

    _save_pool(store, confirmed=False)
    assert state_machine.next_action(PROFILE_NAME)["next_tool"] == "select_target_companies"

    pool_id = _save_pool(store, confirmed=True)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EVIDENCE
    assert action["next_tool"] == "collect_company_evidence"
    assert action["artifact_ids"]["company_pool_id"] == pool_id

    evidence_id = _save_evidence(store, pool_id)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_REQUIREMENT
    assert action["next_tool"] == "analyze_company_requirements"
    assert action["artifact_ids"]["evidence_run_id"] == evidence_id

    requirement_id = _save_requirement(store, evidence_id)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "plan_execution_alignment"
    assert action["artifact_ids"]["requirement_profile_id"] == requirement_id

    _save_plan(store, requirement_id, applied=False)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "save_execution_alignment"

    plan_id = _save_plan(store, requirement_id, applied=True)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTION
    assert action["next_tool"] == "generate_tasks"
    assert action["artifact_ids"]["execution_plan_id"] == plan_id
    assert action["artifact_ids"]["execution_state_id"] == ""

    execution_id = _save_execution(store, plan_id)
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTING
    assert action["next_tool"] == "get_next_tasks"
    assert action["artifact_ids"]["execution_state_id"] == execution_id
    assert action["optional_next_tools"] == [
        "build_application_list",
        "record_application",
        "check_plan_fit",
        "get_weekly_review",
    ]


def test_optional_stages_do_not_block_execution(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    _save_profile(store)
    _save_target(store)
    _save_market(store)
    _save_gap(store)
    _save_baseline(store)
    pool_id = _save_pool(store)
    evidence_id = _save_evidence(store, pool_id)
    requirement_id = _save_requirement(store, evidence_id)
    plan_id = _save_plan(store, requirement_id, applied=True)
    _save_execution(store, plan_id)

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTING
    assert action["next_tool"] == "get_next_tasks"
    assert action["artifact_ids"]["application_state_id"] == ""
    assert action["artifact_ids"]["review_report_id"] == ""
    assert "record_application" in action["optional_next_tools"]
    assert "get_weekly_review" in action["optional_next_tools"]


def test_legacy_plan_counts_as_baseline_done(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    profile_state["who"] = {"name": "旧用户"}
    profile_state["summary"] = "旧档案"
    profile_state["want"] = {"target_role": "AI Agent 开发"}
    profile_state["gap"] = {"match_score": 58}
    profile_state["plan"] = {"roadmap": {"phases": []}}

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert action["next_tool"] == "select_target_companies"
    assert all(value == "" for value in action["artifact_ids"].values())


def test_legacy_plan_without_research_is_not_forced_to_redo(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    profile_state["gap"] = {"match_score": 58}
    profile_state["plan"] = {"roadmap": {"phases": []}}

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert action["next_tool"] == "select_target_companies"


def test_core_state_artifact_ids_take_precedence(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    _save_profile(store)
    _save_target(store)
    _save_market(store)
    _save_gap(store)
    _save_baseline(store)
    old_pool_id = _save_pool(store)
    _save_pool(store)
    old_evidence_id = _save_evidence(store, old_pool_id)

    profile_state["core_state"] = {
        "company_pool_id": old_pool_id,
        "evidence_run_id": old_evidence_id,
    }

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_REQUIREMENT
    assert action["artifact_ids"]["company_pool_id"] == old_pool_id
    assert action["artifact_ids"]["evidence_run_id"] == old_evidence_id

def test_optional_artifacts_do_not_skip_core_stages(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    profile_state["who"] = {"name": "张三"}
    profile_state["have"] = {"skills": ["Python"]}
    profile_state["want"] = {"target_role": "AI Agent 开发"}
    _save_application(store)
    _save_review(store)

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_MARKET
    assert action["next_tool"] == "gather_research_data"
    assert action["artifact_ids"]["application_state_id"] == ""
    assert action["artifact_ids"]["review_report_id"] == ""


def test_cross_profile_artifact_is_rejected(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    foreign_pool_id = _save_pool(store, profile_name="bob")
    profile_state["core_state"] = {"company_pool_id": foreign_pool_id}

    action = state_machine.next_action(PROFILE_NAME)

    assert action["artifact_ids"]["company_pool_id"] == ""
    assert action["stage"] == state_machine.STAGE_PROFILE


def test_empty_reference_does_not_satisfy_chain(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    _save_profile(store)
    _save_target(store)
    _save_market(store)
    _save_gap(store)
    _save_baseline(store)
    pool_id = _save_pool(store)
    store.save(
        EvidenceRun(
            meta=_meta(store, state_machine.STAGE_EVIDENCE),
            target_spec=TargetSpec(role="AI Agent 开发"),
            company_pool_id="",
        )
    )
    profile_state["core_state"] = {"company_pool_id": pool_id}

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EVIDENCE
    assert action["next_tool"] == "collect_company_evidence"
    assert action["artifact_ids"]["evidence_run_id"] == ""


def _save_requirement_custom(
    store: ArtifactStore,
    evidence_run_id: str,
    *,
    validation: dict[str, Any],
    interpretation: dict[str, Any] | None = None,
) -> str:
    meta = _meta(store, state_machine.STAGE_REQUIREMENT).model_copy(
        update={"validation": validation}
    )
    return store.save(
        RequirementProfile(
            meta=meta,
            evidence_run_id=evidence_run_id,
            interpretation=interpretation or {},
        )
    )


def _seed_through_evidence(store: ArtifactStore) -> str:
    _save_profile(store)
    _save_target(store)
    _save_market(store)
    _save_gap(store)
    _save_baseline(store)
    pool_id = _save_pool(store)
    return _save_evidence(store, pool_id)


def test_draft_requirement_requires_save_before_stage_nine(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    draft_id = _save_requirement_custom(
        store, evidence_id, validation={"status": "draft"}
    )

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_REQUIREMENT
    assert action["next_tool"] == "save_requirement_profile"
    assert action["artifact_ids"]["requirement_profile_id"] == draft_id


def test_draft_requirement_with_interpretation_reaches_stage_nine(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    _save_requirement_custom(
        store,
        evidence_id,
        validation={"status": "draft"},
        interpretation={"summary": "RAG 是核心要求"},
    )

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "plan_execution_alignment"


def test_saved_requirement_without_interpretation_reaches_stage_nine(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    _save_requirement_custom(store, evidence_id, validation={"status": "saved"})

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "plan_execution_alignment"


def test_execution_plan_baseline_mismatch_blocks_advancement(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    requirement_id = _save_requirement_custom(
        store, evidence_id, validation={"status": "saved"}
    )
    store.save(
        ExecutionPlan(
            meta=_meta(store, state_machine.STAGE_EXECUTION_PLAN).model_copy(
                update={"validation": {"applied": True}}
            ),
            requirement_profile_id=requirement_id,
            baseline_plan_id="bp_other",
            applied=True,
        )
    )

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "plan_execution_alignment"
    assert "baseline_plan_id" in action["reason"]


def test_empty_upstream_ids_are_reported_not_skipped() -> None:
    from src.core import progress as progress_module

    # 上游 id 与下游引用都为空：必须报「缺少上游」，不能静默放行。
    problems = progress_module._upstream_problems(
        state_machine.STAGE_COMPANY_POOL,
        {"meta": {"inputs": {}}},
        {},
    )
    assert any("缺少上游" in problem and "baseline_plan_id" in problem for problem in problems)

    # 专用例外只允许 strict_baseline=False 的 ExecutionPlan 缺 baseline_plan_id。
    plan = {
        "requirement_profile_id": "rp_1",
        "baseline_plan_id": "",
        "meta": {"validation": {}},
    }
    ids = {"requirement_profile_id": "rp_1"}
    assert (
        progress_module._upstream_problems(
            state_machine.STAGE_EXECUTION_PLAN, plan, ids, strict_baseline=False
        )
        == []
    )
    strict = progress_module._upstream_problems(
        state_machine.STAGE_EXECUTION_PLAN, plan, ids, strict_baseline=True
    )
    assert any("baseline_plan_id" in problem for problem in strict)


def test_skip_flag_cannot_bypass_applied_plan_upstream_checks(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    requirement_id = _save_requirement_custom(
        store, evidence_id, validation={"status": "saved"}
    )
    store.save(
        ExecutionPlan(
            meta=_meta(store, state_machine.STAGE_EXECUTION_PLAN).model_copy(
                update={"validation": {"applied": True}}
            ),
            requirement_profile_id=requirement_id,
            baseline_plan_id="bp_other",
            applied=True,
        )
    )
    profile_state["plan"] = {"roadmap": {"phases": [{"name": "基线", "milestones": []}]}}
    profile_state["tasks"] = [object()]
    profile_state["guidance"] = {
        "goal_confirmed_at": "2026-11-09T00:00:00",
        "enterprise_alignment_skipped_at": "2026-11-09T00:00:00",
    }

    action = state_machine.next_action(PROFILE_NAME)

    # 已应用执行版必须继续走 6C 上游校验，不能被「先按基线执行」豁免覆盖。
    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "plan_execution_alignment"
    assert action["next_tool"] not in {"generate_tasks", "get_next_tasks"}
    assert "baseline_plan_id" in action["reason"]


def test_skip_flag_cannot_bypass_stale_execution_state_generation(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    evidence_id = _seed_through_evidence(store)
    requirement_id = _save_requirement_custom(
        store, evidence_id, validation={"status": "saved"}
    )
    baseline_id = _latest_id(store, state_machine.STAGE_BASELINE_PLAN)
    plan_id = store.save(
        ExecutionPlan(
            meta=_meta(store, state_machine.STAGE_EXECUTION_PLAN).model_copy(
                update={"validation": {"applied": True}}
            ),
            requirement_profile_id=requirement_id,
            baseline_plan_id=baseline_id,
            applied=True,
        )
    )
    store.save(
        ExecutionState(
            meta=_meta(store, state_machine.STAGE_EXECUTION),
            execution_plan_id="ep_old_generation",
        )
    )
    profile_state["plan"] = {"roadmap": {"phases": [{"name": "基线", "milestones": []}]}}
    profile_state["tasks"] = [object()]
    profile_state["guidance"] = {
        "goal_confirmed_at": "2026-11-09T00:00:00",
        "enterprise_alignment_skipped_at": "2026-11-09T00:00:00",
    }

    action = state_machine.next_action(PROFILE_NAME)

    # 旧代际 ExecutionState 不能借跳过标记直接 get_next_tasks。
    assert plan_id
    assert action["stage"] == state_machine.STAGE_EXECUTION
    assert action["next_tool"] == "generate_tasks"
    assert action["artifact_ids"]["execution_state_id"] == ""

