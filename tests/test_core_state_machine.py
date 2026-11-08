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


def _save_target(store: ArtifactStore) -> str:
    return store.save(
        TargetArtifact(
            meta=_meta(store, state_machine.STAGE_TARGET),
            role="AI Agent 开发",
            city="北京",
        )
    )


def _save_market(store: ArtifactStore) -> str:
    return store.save(
        MarketBaseline(
            meta=_meta(store, state_machine.STAGE_MARKET),
            target_spec=TargetSpec(role="AI Agent 开发"),
        )
    )


def _save_gap(store: ArtifactStore) -> str:
    return store.save(
        GapReport(meta=_meta(store, state_machine.STAGE_GAP), match_score=60)
    )


def _save_baseline(store: ArtifactStore) -> str:
    return store.save(
        BaselinePlan(
            meta=_meta(store, state_machine.STAGE_BASELINE_PLAN),
            roadmap={"phases": []},
        )
    )


def _save_pool(
    store: ArtifactStore, confirmed: bool = True, profile_name: str = PROFILE_NAME
) -> str:
    return store.save(
        CompanyPool(
            meta=_meta(store, state_machine.STAGE_COMPANY_POOL, profile_name),
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
    assert action["next_tool"] == "finalize_profile"
    assert all(value == "" for value in action["artifact_ids"].values())
    assert action["optional_next_tools"] == []


def test_stages_follow_artifact_order(
    store: ArtifactStore, profile_state: dict[str, Any]
) -> None:
    assert state_machine.next_action(PROFILE_NAME)["next_tool"] == "finalize_profile"
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
