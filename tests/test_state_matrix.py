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
from src.core.artifacts.store import ArtifactStore
from src.core.state import State, allowed_tools, resolve_state
from src.models import CareerProfile, Task
from src.tools import profile as profile_store
from src.tools.task_tools import get_workflow_status

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
    progress.STAGE_APPLICATIONS: "ap",
    progress.STAGE_REVIEW: "rv",
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


def _save_target(
    store: ArtifactStore, profile_id: str, *, fingerprint: str = ""
) -> str:
    inputs = {"profile_id": profile_id}
    if fingerprint:
        inputs[progress.TARGET_FINGERPRINT_KEY] = fingerprint
    return store.save(
        TargetArtifact(
            meta=_meta(store, progress.STAGE_TARGET, inputs=inputs),
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
    # fixture 显式 seed 到基线 artifacts，并保留下游 profile 字段。
    _seed_to_baseline(store)
    return _profile(
        who={"name": "已有档案"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        tasks=[SimpleNamespace(status="pending")],
        guidance={"goal_confirmed_at": "2026-11-09T00:00:00"},
        summary="已有档案",
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


def _case_15(store: ArtifactStore) -> SimpleNamespace:
    """F15：无 MarketBaseline，但已有 gap 事实 → 视为跳过市场调研。"""
    profile_id = _save_profile(store)
    _save_target(store, profile_id)
    return _confirmed_profile(gap={"match_score": 58})


def _case_16(store: ArtifactStore) -> SimpleNamespace:
    """F16：确认目标后只补 expected_outcome → 指纹不变，TargetSpec 不失效。"""
    profile = _confirmed_profile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={
            "target_role": "AI Agent 开发",
            "city": "北京",
            "expected_outcome": "薪资优先",
        },
    )
    fingerprint = progress.profile_target_fingerprint(
        _confirmed_profile(
            who={"name": "张三"},
            have={"skills": ["Python"]},
            want={"target_role": "AI Agent 开发", "city": "北京"},
        )
    )
    profile_id = _save_profile(store)
    _save_target(store, profile_id, fingerprint=fingerprint)
    return profile


def _case_17(store: ArtifactStore) -> SimpleNamespace:
    """F17：target_role 变化 → 指纹变化，旧 TargetSpec 失效回到目标确认。"""
    profile = _confirmed_profile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发", "city": "北京"},
    )
    profile_id = _save_profile(store)
    _save_target(
        store,
        profile_id,
        fingerprint=progress.profile_target_fingerprint(profile),
    )
    profile.want = {"target_role": "后端开发", "city": "北京"}
    return profile


def _case_18(store: ArtifactStore) -> SimpleNamespace:
    """F18：新流程已有 research/gap/plan/tasks 但目标未确认 → 仍 PROFILE_COLLECTING。"""
    return _profile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发"},
        guidance={"brief_shown_at": "2026-11-09T00:00:00"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        tasks=[SimpleNamespace(status="pending")],
    )


def _case_19(store: ArtifactStore) -> SimpleNamespace:
    """F19：新流程已确认但未 finalize，下游产物不得跳过建档。"""
    return _confirmed_profile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发"},
        guidance={
            "goal_confirmed_at": "2026-11-09T00:00:00",
            "brief_shown_at": "2026-11-09T00:00:00",
        },
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        tasks=[SimpleNamespace(status="pending")],
    )


def _case_21(store: ArtifactStore) -> SimpleNamespace:
    """F21：改 who.graduation_year（届别）→ 指纹变化，旧 TargetSpec 失效。"""
    profile = _confirmed_profile(
        who={"name": "张三", "graduation_year": "2027"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发", "city": "北京"},
    )
    profile_id = _save_profile(store)
    _save_target(
        store,
        profile_id,
        fingerprint=progress.profile_target_fingerprint(profile),
    )
    profile.who = {"name": "张三", "graduation_year": "2028"}
    return profile


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
    ("15", _case_15),
    ("16", _case_16),
    ("17", _case_17),
    ("18", _case_18),
    ("19", _case_19),
    ("21", _case_21),
)


def build_case(label: str, store: ArtifactStore) -> tuple[SimpleNamespace, Any]:
    """入口一致性测试复用同一套 fixture 构造，避免复制 13 套档案。"""
    case = dict(_CASES)[label]
    profile = case(store)
    snapshot = resolve_state(profile, store)
    assert allowed_tools(snapshot) == snapshot.allowed_tools
    return profile, snapshot


# Phase 1 持久化 fixture：入口一致性测试（tests/test_entrypoint_consistency.py）
# 逐条维护 EXPECTED，新增 fixture 只做状态矩阵断言。
_ENTRYPOINT_CASE_LABELS: tuple[str, ...] = (
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "13",
    "14",
    "15",
)


def persisted_case_labels() -> tuple[str, ...]:
    return _ENTRYPOINT_CASE_LABELS


def seed_executed_chain(store: ArtifactStore) -> dict[str, str]:
    """Seed 完整 1-10 artifact 链（applied plan + 当前代际 ExecutionState）。

    供入口测试复用：返回 {core_state key: artifact id}，可直接写入 profile.core_state。
    """
    profile_id = _save_profile(store)
    target_id = _save_target(store, profile_id)
    market_id = _save_market(store, target_id)
    gap_id = _save_gap(store, profile_id, market_id)
    baseline_id = _save_baseline(store, gap_id)
    pool_id = _save_pool(store, baseline_id)
    evidence_id = _save_evidence(store, pool_id)
    requirement_id = _save_requirement(
        store,
        evidence_id,
        validation={"status": "saved"},
        interpretation={"summary": "RAG 是核心要求"},
    )
    plan_id = _save_plan(store, requirement_id, baseline_id)
    execution_id = _save_execution(store, plan_id)
    return {
        progress.STAGE_KEYS[progress.STAGE_PROFILE]: profile_id,
        progress.STAGE_KEYS[progress.STAGE_TARGET]: target_id,
        progress.STAGE_KEYS[progress.STAGE_MARKET]: market_id,
        progress.STAGE_KEYS[progress.STAGE_GAP]: gap_id,
        progress.STAGE_KEYS[progress.STAGE_BASELINE_PLAN]: baseline_id,
        progress.STAGE_KEYS[progress.STAGE_COMPANY_POOL]: pool_id,
        progress.STAGE_KEYS[progress.STAGE_EVIDENCE]: evidence_id,
        progress.STAGE_KEYS[progress.STAGE_REQUIREMENT]: requirement_id,
        progress.STAGE_KEYS[progress.STAGE_EXECUTION_PLAN]: plan_id,
        progress.STAGE_KEYS[progress.STAGE_EXECUTION]: execution_id,
    }


def save_optional_stage_facts(
    store: ArtifactStore, execution_id: str
) -> dict[str, str]:
    """Seed 阶段 11/12 可选事实（投递/复盘），返回 core_state 指针。"""
    application_id = store.save(
        ApplicationState(
            meta=_meta(store, progress.STAGE_APPLICATIONS),
            applications=[{"company": "ACME", "role": "AI 工程师", "status": "applied"}],
            funnel={"applied": 1},
        )
    )
    review_id = store.save(
        ReviewReport(
            meta=_meta(store, progress.STAGE_REVIEW),
            execution_state_id=execution_id,
            weekly_facts={"days": 7, "checkins": 1},
            recommendations=["继续推进任务"],
        )
    )
    return {
        progress.STAGE_KEYS[progress.STAGE_APPLICATIONS]: application_id,
        progress.STAGE_KEYS[progress.STAGE_REVIEW]: review_id,
    }


def _snapshot(label: str, store: ArtifactStore):
    _profile, snapshot = build_case(label, store)
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


def test_fixture_07_baseline_with_downstream_fields(store: ArtifactStore) -> None:
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


def test_fixture_15_market_skipped(store: ArtifactStore) -> None:
    snapshot = _snapshot("15", store)

    assert snapshot.state is not State.MARKET_PENDING
    assert snapshot.state is State.GAP_PENDING
    assert snapshot.stage_index == 4
    assert snapshot.next_tool == "analyze_gaps"
    assert any(blocker.code == "market_skipped" for blocker in snapshot.blockers)


def test_fixture_16_expected_outcome_keeps_target_spec(store: ArtifactStore) -> None:
    snapshot = _snapshot("16", store)

    assert snapshot.state is State.MARKET_PENDING
    assert snapshot.next_tool == "gather_research_data"
    assert snapshot.artifact_ids[progress.STAGE_KEYS[progress.STAGE_TARGET]]
    assert not any(blocker.code == "target_stale" for blocker in snapshot.blockers)


def test_fixture_17_target_change_invalidates_old_target_spec(
    store: ArtifactStore,
) -> None:
    snapshot = _snapshot("17", store)

    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.next_tool == "intake(want)"
    assert not snapshot.artifact_ids[progress.STAGE_KEYS[progress.STAGE_TARGET]]
    assert any(blocker.code == "target_stale" for blocker in snapshot.blockers)


def test_fixture_18_new_flow_downstream_does_not_skip_goal_confirmation(
    store: ArtifactStore,
) -> None:
    snapshot = _snapshot("18", store)

    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.next_tool == "intake(want)"
    assert not snapshot.artifact_ids[progress.STAGE_KEYS[progress.STAGE_TARGET]]
    assert any(blocker.code == "target_unconfirmed" for blocker in snapshot.blockers)


def test_fixture_19_new_flow_confirmed_but_not_finalized(
    store: ArtifactStore,
) -> None:
    snapshot = _snapshot("19", store)

    assert snapshot.state is State.PROFILE_READY
    assert snapshot.next_tool == "finalize_profile"
    assert not snapshot.completion[progress.STAGE_PROFILE]


def test_fixture_21_graduation_year_change_invalidates_target(
    store: ArtifactStore,
) -> None:
    snapshot = _snapshot("21", store)

    assert snapshot.state is State.PROFILE_COLLECTING
    assert snapshot.next_tool == "intake(want)"
    assert not snapshot.artifact_ids[progress.STAGE_KEYS[progress.STAGE_TARGET]]
    assert any(blocker.code == "target_stale" for blocker in snapshot.blockers)


def test_new_flow_downstream_does_not_write_target_or_market(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新流程有 research/gap/plan/tasks 但目标未确认：回填不得写 TargetSpec/market。"""
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    profile = CareerProfile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发"},
        guidance={"brief_shown_at": "2026-11-09T00:00:00"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan={"roadmap": {"phases": [{"id": "phase_1", "name": "基础"}]}},
        tasks=[Task(id="task_001", name="任务", phase_id="phase_1")],
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    profile_store.set_active_profile_name(PROFILE_NAME)

    status = get_workflow_status()

    updated = profile_store.load_profile(PROFILE_NAME)
    assert not updated.core_state.get(progress.STAGE_KEYS[progress.STAGE_TARGET])
    assert not updated.core_state.get(progress.STAGE_KEYS[progress.STAGE_MARKET])
    assert not updated.core_state.get(progress.STAGE_KEYS[progress.STAGE_PROFILE])
    assert "**下一步**：intake(want)" in status


def test_optional_stage_facts_do_not_change_state(store: ArtifactStore) -> None:
    ids = seed_executed_chain(store)
    optional_ids = save_optional_stage_facts(
        store, ids[progress.STAGE_KEYS[progress.STAGE_EXECUTION]]
    )
    profile = _confirmed_profile(
        core_state={**ids, **optional_ids},
        tasks=[SimpleNamespace(status="pending")],
        applications=[{"company": "ACME", "status": "applied"}],
        last_review_at="2026-11-10T00:00:00",
    )

    executing = resolve_state(profile, store)
    assert executing.state is State.EXECUTING
    assert executing.stage_index == 10
    assert executing.next_tool == "get_next_tasks"
    assert executing.completion[progress.STAGE_APPLICATIONS] is True
    assert executing.completion[progress.STAGE_REVIEW] is True

    profile.tasks = [SimpleNamespace(status="completed")]
    maintenance = resolve_state(profile, store)
    assert maintenance.state is State.MAINTENANCE
    assert maintenance.stage_index == 10
    assert maintenance.next_tool == "build_application_list"


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


def test_workflow_status_shows_optional_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    store = ArtifactStore()
    ids = seed_executed_chain(store)
    optional_ids = save_optional_stage_facts(
        store, ids[progress.STAGE_KEYS[progress.STAGE_EXECUTION]]
    )
    profile = CareerProfile(
        who={"name": "张三"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发", "user_confirmed": True},
        guidance={"goal_confirmed_at": "2026-11-09T00:00:00"},
        summary="已确认",
        core_state={**ids, **optional_ids},
        tasks=[Task(id="task_001", name="任务", phase_id="phase_1", status="pending")],
        applications=[{"id": "app_001", "company": "ACME", "role": "AI 工程师"}],
        last_review_at="2026-11-10T00:00:00",
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    profile_store.set_active_profile_name(PROFILE_NAME)

    status = get_workflow_status()

    assert "## 当前阶段（12 步）：10/12 任务执行与打卡" in status
    assert "**下一步**：get_next_tasks" in status
    assert "投递记录：1 条" in status
    assert "上次周检视：2026-11-10T00:00:00" in status
