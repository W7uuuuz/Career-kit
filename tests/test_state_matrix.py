"""状态矩阵 fixture——13 个持久化状态与 contracts 就绪判定的一致性。

覆盖 docs/internal/state-model.md 第 7 节场景；断言只用状态、next_tool、
user_decision、allowed_tools、blockers 等事实，不启动网络、不写真实档案。

BOSS 运行期登录失效是工具返回态（LOGIN_REQUIRED），不是持久化状态，
属于 Phase 3 工具门禁测试，不在本矩阵内。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from src import paths
from src.core import contracts, progress
from src.core.artifacts.models import (
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
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.state import State, allowed_tools, resolve_state

PROFILE_NAME = "alice"

PREFIXES = {
    progress.STAGE_PROFILE: "pf",
    progress.STAGE_TARGET: "ts",
    progress.STAGE_MARKET: "mb",
    progress.STAGE_GAP: "gr",
    progress.STAGE_BASELINE_PLAN: "bp",
    progress.STAGE_COMPANY_POOL: "cp",
    progress.STAGE_EVIDENCE: "ev",
    progress.STAGE_REQUIREMENT: "rp",
    progress.STAGE_EXECUTION_PLAN: "ep",
    progress.STAGE_EXECUTION: "es",
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


def _profile(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "name": PROFILE_NAME,
        "who": {},
        "have": {},
        "want": {},
        "target_jd": {},
        "research": {},
        "gap": {},
        "plan": {},
        "tasks": [],
        "applications": [],
        "core_state": {},
        "guidance": {},
        "gap_stale_at": "",
        "section_updated_at": {},
        "summary": "",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _confirmed_profile(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "want": {"target_role": "AI Agent 开发"},
        "guidance": {"goal_confirmed_at": "2026-11-09T00:00:00"},
    }
    defaults.update(overrides)
    return _profile(**defaults)


def _meta(
    store: ArtifactStore,
    stage: str,
    *,
    inputs: dict[str, str] | None = None,
    validation: dict[str, Any] | None = None,
) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(PREFIXES[stage]),
        stage=stage,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
        inputs=inputs or {},
        validation=validation or {},
    )


def _save_profile(store: ArtifactStore) -> str:
    return store.save(
        ProfileArtifact(
            meta=_meta(store, progress.STAGE_PROFILE),
            name="张三",
            who={"name": "张三"},
            have={"skills": ["Python"]},
            summary="应届生",
        )
    )


def _save_target(store: ArtifactStore, profile_id: str) -> str:
    return store.save(
        TargetArtifact(
            meta=_meta(
                store, progress.STAGE_TARGET, inputs={"profile_id": profile_id}
            ),
            role="AI Agent 开发",
            city="北京",
        )
    )


def _save_market(store: ArtifactStore, target_id: str) -> str:
    return store.save(
        MarketBaseline(
            meta=_meta(
                store,
                progress.STAGE_MARKET,
                inputs={"target_spec_id": target_id},
            ),
            target_spec=TargetSpec(role="AI Agent 开发"),
        )
    )


def _save_gap(store: ArtifactStore, profile_id: str, market_id: str) -> str:
    return store.save(
        GapReport(
            meta=_meta(store, progress.STAGE_GAP),
            profile_snapshot_id=profile_id,
            market_baseline_id=market_id,
            match_score=60,
        )
    )


def _save_baseline(store: ArtifactStore, gap_id: str) -> str:
    return store.save(
        BaselinePlan(
            meta=_meta(store, progress.STAGE_BASELINE_PLAN),
            gap_report_id=gap_id,
            roadmap={"phases": [{"id": "phase_1", "name": "基础"}]},
        )
    )


def _save_pool(
    store: ArtifactStore, baseline_id: str, *, confirmed: bool = True
) -> str:
    return store.save(
        CompanyPool(
            meta=_meta(
                store,
                progress.STAGE_COMPANY_POOL,
                inputs={"baseline_plan_id": baseline_id},
                validation={"confirmed": confirmed},
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


def _save_evidence(
    store: ArtifactStore,
    pool_id: str,
    *,
    counts: dict[str, int] | None = None,
) -> str:
    return store.save(
        EvidenceRun(
            meta=_meta(store, progress.STAGE_EVIDENCE),
            target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
            company_pool_id=pool_id,
            jd_items=[
                {
                    "id": f"JD{index:03d}",
                    "company_id": "bytedance",
                    "company": "字节跳动",
                    "tier": "大厂",
                    "title": "AI Agent 开发",
                    "location": "北京",
                    "detail_status": "list_only",
                }
                for index in range(1, 4)
            ],
            counts=counts or {},
        )
    )


def _save_requirement(
    store: ArtifactStore,
    evidence_id: str,
    *,
    validation: dict[str, Any] | None = None,
    interpretation: dict[str, Any] | None = None,
) -> str:
    return store.save(
        RequirementProfile(
            meta=_meta(
                store,
                progress.STAGE_REQUIREMENT,
                validation=validation or {},
            ),
            evidence_run_id=evidence_id,
            interpretation=interpretation or {},
        )
    )


def _save_plan(
    store: ArtifactStore,
    requirement_id: str,
    baseline_id: str,
    *,
    applied: bool = True,
) -> str:
    return store.save(
        ExecutionPlan(
            meta=_meta(
                store,
                progress.STAGE_EXECUTION_PLAN,
                validation={"applied": applied},
            ),
            requirement_profile_id=requirement_id,
            baseline_plan_id=baseline_id,
            applied=applied,
        )
    )


def _save_execution(store: ArtifactStore, plan_id: str) -> str:
    return store.save(
        ExecutionState(
            meta=_meta(store, progress.STAGE_EXECUTION),
            execution_plan_id=plan_id,
        )
    )


def _seed_to_gap(store: ArtifactStore) -> tuple[str, str, str, str]:
    profile_id = _save_profile(store)
    target_id = _save_target(store, profile_id)
    market_id = _save_market(store, target_id)
    gap_id = _save_gap(store, profile_id, market_id)
    return profile_id, target_id, market_id, gap_id


def _seed_to_baseline(store: ArtifactStore) -> str:
    _profile_id, _target_id, _market_id, gap_id = _seed_to_gap(store)
    return _save_baseline(store, gap_id)


def _seed_to_pool(store: ArtifactStore) -> str:
    baseline_id = _seed_to_baseline(store)
    return _save_pool(store, baseline_id)


def _seed_to_evidence(
    store: ArtifactStore, *, counts: dict[str, int] | None = None
) -> str:
    pool_id = _seed_to_pool(store)
    return _save_evidence(store, pool_id, counts=counts)


def _seed_to_requirement(store: ArtifactStore) -> tuple[str, str]:
    evidence_id = _seed_to_evidence(store)
    baseline = store.latest(PROFILE_NAME, progress.STAGE_BASELINE_PLAN)
    assert isinstance(baseline, dict)
    baseline_id = str((baseline.get("meta") or {}).get("id") or "")
    requirement_id = _save_requirement(
        store,
        evidence_id,
        validation={"status": "saved"},
        interpretation={"summary": "RAG 是核心要求"},
    )
    return requirement_id, baseline_id


def _case_01(store: ArtifactStore) -> SimpleNamespace:
    return _profile()


def _case_02(store: ArtifactStore) -> SimpleNamespace:
    return _profile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        guidance={"brief_shown_at": "2026-11-09T00:00:00"},
    )


def _case_03(store: ArtifactStore) -> SimpleNamespace:
    return _profile(
        want={"target_role": "AI Agent 开发"},
        guidance={"brief_shown_at": "2026-11-09T00:00:00"},
    )


def _case_04(store: ArtifactStore) -> SimpleNamespace:
    return _confirmed_profile()


def _case_05(store: ArtifactStore) -> SimpleNamespace:
    _seed_to_gap(store)
    return _confirmed_profile()


def _case_06(store: ArtifactStore) -> SimpleNamespace:
    _seed_to_gap(store)
    return _confirmed_profile(
        gap={"match_score": 58},
        gap_stale_at="2026-11-09T00:00:00",
    )


def _case_07(store: ArtifactStore) -> SimpleNamespace:
    # legacy 场景：fixture 显式 seed Phase 4 将由 core/legacy.py 生成的 anchor
    # artifacts；state.py 本身不读 legacy_mode。
    _seed_to_baseline(store)
    return _profile(
        who={"name": "旧用户"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        tasks=[SimpleNamespace(status="pending")],
        guidance={"goal_confirmed_at": "2026-11-09T00:00:00"},
        summary="旧档案",
    )


def _case_08(store: ArtifactStore) -> SimpleNamespace:
    requirement_id, baseline_id = _seed_to_requirement(store)
    old_plan_id = _save_plan(store, requirement_id, baseline_id)
    _save_plan(store, requirement_id, baseline_id)
    _save_execution(store, old_plan_id)
    return _confirmed_profile()


def _case_09(store: ArtifactStore) -> SimpleNamespace:
    _seed_to_baseline(store)
    return _confirmed_profile(
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        guidance={
            "goal_confirmed_at": "2026-11-09T00:00:00",
            "enterprise_alignment_skipped_at": "2026-11-09T00:00:00",
        },
    )


def _case_10(store: ArtifactStore) -> SimpleNamespace:
    _seed_to_pool(store)
    return _confirmed_profile(
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        guidance={
            "goal_confirmed_at": "2026-11-09T00:00:00",
            "enterprise_alignment_skipped_at": "2026-11-09T00:00:00",
        },
    )


def _case_11(store: ArtifactStore) -> SimpleNamespace:
    _seed_to_evidence(
        store,
        counts={"kept_jobs": 3, "list_only": 3, "list_only_kept": 3},
    )
    return _confirmed_profile()


def _case_13(store: ArtifactStore) -> SimpleNamespace:
    evidence_id = _seed_to_evidence(store)
    _save_requirement(store, evidence_id, validation={"status": "draft"})
    return _confirmed_profile()


def _case_14(store: ArtifactStore) -> SimpleNamespace:
    requirement_id, baseline_id = _seed_to_requirement(store)
    _save_plan(store, requirement_id, baseline_id)
    _save_execution(store, "ep_old_generation")
    return _confirmed_profile()


_CASES: tuple[tuple[str, Callable[[ArtifactStore], SimpleNamespace]], ...] = (
    ("01", _case_01),
    ("02", _case_02),
    ("03", _case_03),
    ("04", _case_04),
    ("05", _case_05),
    ("06", _case_06),
    ("07", _case_07),
    ("08", _case_08),
    ("09", _case_09),
    ("10", _case_10),
    ("11", _case_11),
    ("13", _case_13),
    ("14", _case_14),
)


def _snapshot(label: str, store: ArtifactStore):
    case = dict(_CASES)[label]
    snapshot = resolve_state(case(store), store)
    assert allowed_tools(snapshot) == snapshot.allowed_tools
    return snapshot


def _artifacts_from_snapshot(
    store: ArtifactStore, snapshot: Any
) -> dict[str, Any]:
    return {
        stage: store.load(snapshot.artifact_ids.get(progress.STAGE_KEYS[stage], ""))
        if snapshot.artifact_ids.get(progress.STAGE_KEYS[stage])
        else None
        for stage in progress.STAGE_ORDER
    }


def test_fixture_01_empty(store: ArtifactStore) -> None:
    snapshot = _snapshot("01", store)

    assert snapshot.state is State.EMPTY
    assert snapshot.next_tool == "parse_resume"
    assert {"parse_resume", "intake"} <= snapshot.allowed_tools
    assert snapshot.stage_index == 1


def test_fixture_02_profile_collecting_without_target(store: ArtifactStore) -> None:
    snapshot = _snapshot("02", store)

    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.next_tool == "explore_goals"
    assert snapshot.user_decision == "确认方向/城市/届别"
    assert snapshot.stage_index == 2


def test_fixture_03_goal_unconfirmed(store: ArtifactStore) -> None:
    snapshot = _snapshot("03", store)

    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.next_tool == "intake(want)"
    assert snapshot.user_decision == "确认方向/城市/届别"


def test_fixture_04_goal_confirmed_not_finalized(store: ArtifactStore) -> None:
    snapshot = _snapshot("04", store)

    assert snapshot.state is State.PROFILE_READY
    assert snapshot.next_tool == "finalize_profile"
    assert "finalize_profile" in snapshot.allowed_tools
    assert snapshot.stage_index == 1


def test_fixture_05_gap_generated(store: ArtifactStore) -> None:
    snapshot = _snapshot("05", store)

    assert snapshot.state is State.BASELINE_PLAN_PENDING
    assert snapshot.next_tool == "generate_roadmap"
    assert snapshot.completion[progress.STAGE_GAP] is True
    assert snapshot.user_decision == "开始规划"


def test_fixture_06_gap_stale(store: ArtifactStore) -> None:
    snapshot = _snapshot("06", store)

    assert snapshot.state is State.GAP_PENDING
    assert snapshot.next_tool == "analyze_gaps"
    assert "analyze_gaps" in snapshot.allowed_tools
    assert any(blocker.code == "gap_stale" for blocker in snapshot.blockers)


def test_fixture_07_legacy_downstream(store: ArtifactStore) -> None:
    snapshot = _snapshot("07", store)

    assert snapshot.state is State.COMPANY_PENDING
    assert snapshot.next_tool == "select_target_companies"
    assert snapshot.user_decision == "企业适配或先按基线执行"
    assert "select_target_companies" in snapshot.allowed_tools


def test_fixture_08_second_execution_plan_apply(store: ArtifactStore) -> None:
    snapshot = _snapshot("08", store)

    assert snapshot.state is State.EXECUTION_READY
    assert snapshot.next_tool == "detail_current_phase"
    assert any(
        blocker.code == "execution_state_stale" for blocker in snapshot.blockers
    )
    assert {"detail_current_phase", "generate_tasks"} <= snapshot.allowed_tools


def test_fixture_09_enterprise_skip(store: ArtifactStore) -> None:
    snapshot = _snapshot("09", store)

    assert snapshot.state is State.EXECUTION_READY
    assert snapshot.next_tool == "detail_current_phase"
    assert snapshot.skip_flags["enterprise_alignment"] is True
    assert any(
        blocker.code == "enterprise_alignment_skipped"
        for blocker in snapshot.blockers
    )
    assert "generate_tasks" in snapshot.allowed_tools


def test_fixture_10_enterprise_chain_restored(store: ArtifactStore) -> None:
    snapshot = _snapshot("10", store)

    assert snapshot.state is State.EVIDENCE_PENDING
    assert snapshot.next_tool == "collect_company_evidence"
    assert snapshot.user_decision == "开始采集"
    assert "collect_company_evidence" in snapshot.allowed_tools


def test_fixture_11_boss_list_only(store: ArtifactStore) -> None:
    snapshot = _snapshot("11", store)

    assert snapshot.state is State.REQUIREMENT_DRAFT
    assert snapshot.next_tool == "analyze_company_requirements"
    assert "analyze_company_requirements" in snapshot.allowed_tools
    assert any(blocker.code == "boss_list_only" for blocker in snapshot.blockers)


def test_fixture_13_requirement_draft(store: ArtifactStore) -> None:
    snapshot = _snapshot("13", store)

    assert snapshot.state is State.REQUIREMENT_DRAFT
    assert snapshot.next_tool == "save_requirement_profile"
    assert "save_requirement_profile" in snapshot.allowed_tools
    assert any(blocker.code == "requirement_draft" for blocker in snapshot.blockers)


def test_fixture_14_execution_state_old_generation(store: ArtifactStore) -> None:
    snapshot = _snapshot("14", store)

    assert snapshot.state is State.EXECUTION_READY
    assert snapshot.next_tool == "detail_current_phase"
    assert any(
        blocker.code == "execution_state_stale" for blocker in snapshot.blockers
    )
    assert "generate_tasks" in snapshot.allowed_tools


def _assert_contract_agreement(
    label: str, snapshot: Any, artifacts: dict[str, Any]
) -> None:
    def ready(stage: str) -> bool:
        return contracts.STAGE_CONTRACTS[stage].ready(artifacts)

    state = snapshot.state
    if state in (State.EXECUTING, State.MAINTENANCE):
        assert ready(progress.STAGE_EXECUTION) is True, label
    elif state is State.EXECUTION_READY:
        assert ready(progress.STAGE_EXECUTION) is False, label
    elif state is State.EXECUTION_PLAN_DRAFT:
        plan = artifacts[progress.STAGE_EXECUTION_PLAN]
        assert isinstance(plan, dict) and not plan.get("applied"), label
        assert ready(progress.STAGE_EXECUTION_PLAN) is False, label
    elif state is State.REQUIREMENT_READY:
        assert ready(progress.STAGE_REQUIREMENT) is True, label
        assert ready(progress.STAGE_EXECUTION_PLAN) is False, label
    elif state is State.REQUIREMENT_DRAFT:
        assert ready(progress.STAGE_REQUIREMENT) is False, label
    elif state is State.EVIDENCE_PENDING:
        assert ready(progress.STAGE_EVIDENCE) is False, label
    elif state is State.COMPANY_PENDING:
        assert ready(progress.STAGE_COMPANY_POOL) is False, label
    elif state is State.BASELINE_PLAN_PENDING:
        assert ready(progress.STAGE_BASELINE_PLAN) is False, label
    elif state is State.GAP_PENDING:
        if not any(blocker.code == "gap_stale" for blocker in snapshot.blockers):
            assert ready(progress.STAGE_GAP) is False, label
    elif state is State.MARKET_PENDING:
        assert ready(progress.STAGE_MARKET) is False, label
    elif state is State.PROFILE_READY:
        assert ready(progress.STAGE_PROFILE) is False, label
    elif state is State.PROFILE_COLLECTING:
        assert ready(progress.STAGE_TARGET) is False, label
    elif state is State.EMPTY:
        assert ready(progress.STAGE_PROFILE) is False, label


def test_state_and_contracts_ready_agree(tmp_path: Path) -> None:
    for label, case in _CASES:
        store = ArtifactStore(tmp_path / label / "career-kit.db")
        snapshot = resolve_state(case(store), store)
        artifacts = _artifacts_from_snapshot(store, snapshot)
        _assert_contract_agreement(label, snapshot, artifacts)
