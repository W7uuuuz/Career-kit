"""Core v2 基座层回归——artifact 存储、模型、旧档案适配与状态机。

所有用例使用 tmp_path 隔离数据目录，不读写真实 ~/.career-kit。
"""

from __future__ import annotations

import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths
from src.core.adapters.legacy_profile import profile_snapshot, target_spec
from src.core.artifacts.models import (
    ArtifactMeta,
    BaselinePlan,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    ExecutionPlan,
    ExecutionState,
    GapReport,
    HardRequirement,
    InterviewEvidence,
    JDEvidence,
    MarketBaseline,
    PlanChange,
    ProfileSnapshot,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.models import CareerProfile

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


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    return root


@pytest.fixture()
def store(data_dir: Path) -> ArtifactStore:
    return ArtifactStore()


@pytest.fixture()
def core_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {"value": {}}
    monkeypatch.setattr(
        state_machine,
        "load_profile",
        lambda name: SimpleNamespace(core_state=state["value"]),
    )
    return state


def _meta(
    store: ArtifactStore,
    stage: str,
    profile_name: str = "alice",
    inputs: dict[str, str] | None = None,
) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(PREFIXES[stage]),
        stage=stage,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
        inputs=inputs or {},
    )


class _ProfileArtifact(ProfileSnapshot):
    meta: ArtifactMeta


class _TargetArtifact(TargetSpec):
    meta: ArtifactMeta


def _seed_upstream(store: ArtifactStore, profile_name: str = "alice") -> dict[str, str]:
    """阶段 1-5 的完整上游链，供阶段 6+ 的引用校验使用。"""
    profile_id = store.save(
        _ProfileArtifact(
            meta=_meta(store, state_machine.STAGE_PROFILE, profile_name),
            name="张三",
            who={"name": "张三"},
            summary="测试档案",
        )
    )
    target_id = store.save(
        _TargetArtifact(
            meta=_meta(
                store,
                state_machine.STAGE_TARGET,
                profile_name,
                {"profile_id": profile_id},
            ),
            role="AI Agent 开发",
            city="北京",
        )
    )
    market_id = store.save(
        MarketBaseline(
            meta=_meta(
                store,
                state_machine.STAGE_MARKET,
                profile_name,
                {"target_spec_id": target_id},
            ),
            target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
        )
    )
    gap_id = store.save(
        GapReport(
            meta=_meta(store, state_machine.STAGE_GAP, profile_name),
            profile_snapshot_id=profile_id,
            market_baseline_id=market_id,
            match_score=60,
        )
    )
    baseline_id = store.save(
        BaselinePlan(
            meta=_meta(store, state_machine.STAGE_BASELINE_PLAN, profile_name),
            gap_report_id=gap_id,
            roadmap={"phases": [{"name": "基础", "milestones": []}]},
        )
    )
    return {
        "profile_id": profile_id,
        "target_spec_id": target_id,
        "market_baseline_id": market_id,
        "gap_report_id": gap_id,
        "baseline_plan_id": baseline_id,
    }


def _pool(
    store: ArtifactStore,
    confirmed: bool,
    profile_name: str = "alice",
    role: str = "AI Agent 开发",
    baseline_plan_id: str = "",
) -> CompanyPool:
    return CompanyPool(
        meta=_meta(
            store,
            state_machine.STAGE_COMPANY_POOL,
            profile_name,
            {"baseline_plan_id": baseline_plan_id},
        ),
        target_spec=TargetSpec(role=role, city="北京"),
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


def _evidence(store: ArtifactStore, company_pool_id: str, profile_name: str = "alice") -> EvidenceRun:
    return EvidenceRun(
        meta=_meta(
            store,
            state_machine.STAGE_EVIDENCE,
            profile_name,
            inputs={"company_pool_id": company_pool_id},
        ),
        target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
        company_pool_id=company_pool_id,
        jd_items=[
            JDEvidence(
                id="JD001",
                company_id="bytedance",
                company="字节跳动",
                tier="大厂",
                title="AI Agent 工程师",
                detail_status="ok",
            )
        ],
    )


def _requirement(
    store: ArtifactStore, evidence_run_id: str, profile_name: str = "alice"
) -> RequirementProfile:
    return RequirementProfile(
        meta=_meta(
            store,
            state_machine.STAGE_REQUIREMENT,
            profile_name,
            inputs={"evidence_run_id": evidence_run_id},
        ),
        evidence_run_id=evidence_run_id,
        sample_size_jd=1,
    )


def _plan(
    store: ArtifactStore, requirement_profile_id: str, applied: bool, profile_name: str = "alice"
) -> ExecutionPlan:
    return ExecutionPlan(
        meta=_meta(
            store,
            state_machine.STAGE_EXECUTION_PLAN,
            profile_name,
            inputs={"requirement_profile_id": requirement_profile_id},
        ),
        requirement_profile_id=requirement_profile_id,
        applied=applied,
    )


def test_artifact_store_roundtrip_versions_and_listing(
    store: ArtifactStore, data_dir: Path
) -> None:
    first_id = store.save(_pool(store, confirmed=True))
    loaded = store.load(first_id)
    assert loaded is not None
    assert loaded["meta"]["id"] == first_id
    assert loaded["meta"]["version"] == 1
    assert store.latest("alice", state_machine.STAGE_COMPANY_POOL) == loaded

    second_id = store.save(_pool(store, confirmed=True))
    second = store.load(second_id)
    assert second is not None
    assert second["meta"]["version"] == 2
    latest = store.latest("alice", state_machine.STAGE_COMPANY_POOL)
    assert latest is not None
    assert latest["meta"]["id"] == second_id

    items = store.list("alice", state_machine.STAGE_COMPANY_POOL)
    assert [item["meta"]["id"] for item in items] == [second_id, first_id]
    assert store.list("alice") == items
    assert store.list("alice", state_machine.STAGE_EVIDENCE) == []
    assert store.load("missing") is None
    assert store.latest("alice", state_machine.STAGE_EVIDENCE) is None
    assert (data_dir / "career-kit.db").exists()


def test_artifact_store_profile_isolation(store: ArtifactStore) -> None:
    alice_id = store.save(_pool(store, confirmed=True, profile_name="alice"))
    bob_id = store.save(_pool(store, confirmed=True, profile_name="bob"))
    assert store.latest("alice", state_machine.STAGE_COMPANY_POOL)["meta"]["id"] == alice_id
    assert store.latest("bob", state_machine.STAGE_COMPANY_POOL)["meta"]["id"] == bob_id
    assert len(store.list("alice")) == 1
    assert len(store.list("bob")) == 1
    assert store.list("carol") == []


def test_artifact_store_concurrent_saves_unique_versions(store: ArtifactStore) -> None:
    pools = [_pool(store, confirmed=True) for _ in range(12)]
    ids: list[str] = [""] * len(pools)
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(pools))

    def worker(index: int) -> None:
        try:
            barrier.wait()
            ids[index] = store.save(pools[index])
        except BaseException as exc:  # noqa: BLE001 - 测试收集所有线程异常
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(pools))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    versions = sorted(store.load(item)["meta"]["version"] for item in ids)
    assert versions == list(range(1, len(pools) + 1))
    latest = store.latest("alice", state_machine.STAGE_COMPANY_POOL)
    assert latest is not None
    assert latest["meta"]["version"] == len(pools)


def test_artifact_store_save_does_not_mutate_caller_meta(store: ArtifactStore) -> None:
    pool = _pool(store, confirmed=True)
    pool.meta.created_at = ""
    before = pool.meta.model_dump()

    artifact_id = store.save(pool)

    assert pool.meta.model_dump() == before
    stored = store.load(artifact_id)
    assert stored is not None
    assert stored["meta"]["created_at"]
    assert stored["meta"]["version"] == 1


def test_artifact_store_latest_orders_by_version_not_created_at(store: ArtifactStore) -> None:
    older = _pool(store, confirmed=True)
    older.meta.created_at = "2030-01-01T00:00:00"
    older_id = store.save(older)

    newer = _pool(store, confirmed=True)
    newer.meta.created_at = "2000-01-01T00:00:00"
    newer_id = store.save(newer)

    latest = store.latest("alice", state_machine.STAGE_COMPANY_POOL)
    assert latest is not None
    assert latest["meta"]["id"] == newer_id
    assert store.list("alice", state_machine.STAGE_COMPANY_POOL)[0]["meta"]["id"] == newer_id
    assert older_id != newer_id


def test_artifact_store_dedupes_identical_content(store: ArtifactStore) -> None:
    first = store.save(_pool(store, confirmed=True), dedupe=True)
    second = store.save(_pool(store, confirmed=True), dedupe=True)
    third = store.save(_pool(store, confirmed=True), dedupe=True)

    assert first == second == third
    items = store.list("alice", state_machine.STAGE_COMPANY_POOL)
    assert len(items) == 1
    assert items[0]["meta"]["id"] == first
    assert items[0]["meta"]["version"] == 1


def test_artifact_store_same_id_same_content_keeps_version(store: ArtifactStore) -> None:
    pool = _pool(store, confirmed=True)
    first = store.save(pool)
    second = store.save(pool)

    assert first == second
    loaded = store.load(first)
    assert loaded is not None
    assert loaded["meta"]["version"] == 1
    assert len(store.list("alice", state_machine.STAGE_COMPANY_POOL)) == 1


def test_artifact_store_same_id_content_change_bumps_version(store: ArtifactStore) -> None:
    pool = _pool(store, confirmed=True)
    artifact_id = store.save(pool)

    pool.companies[0].name = "字节跳动（改名）"
    again = store.save(pool)

    assert again == artifact_id
    loaded = store.load(artifact_id)
    assert loaded is not None
    assert loaded["meta"]["version"] == 2
    assert loaded["companies"][0]["name"] == "字节跳动（改名）"
    assert len(store.list("alice", state_machine.STAGE_COMPANY_POOL)) == 1


def test_artifact_store_new_ids_increment_version(store: ArtifactStore) -> None:
    first = store.save(_pool(store, confirmed=True, role="角色一"))
    second = store.save(_pool(store, confirmed=True, role="角色二"))

    assert first != second
    assert store.load(first)["meta"]["version"] == 1
    assert store.load(second)["meta"]["version"] == 2


def test_artifact_store_prunes_old_versions(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ArtifactStore, "MAX_PER_STAGE", 2)
    ids = [
        store.save(_pool(store, confirmed=True, role=f"角色{i}"))
        for i in range(4)
    ]

    items = store.list("alice", state_machine.STAGE_COMPANY_POOL)
    assert [item["meta"]["id"] for item in items] == [ids[3], ids[2]]
    assert store.load(ids[0]) is None
    assert store.load(ids[1]) is None
    assert store.load(ids[2]) is not None
    assert store.load(ids[3]) is not None
    latest = store.latest("alice", state_machine.STAGE_COMPANY_POOL)
    assert latest is not None
    assert latest["meta"]["id"] == ids[3]


def test_new_id_prefix_format_and_uniqueness(store: ArtifactStore) -> None:
    ids = [store.new_id("cp_") for _ in range(200)]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"cp_\d{8}_\d{6}_[0-9a-f]{6}", item) for item in ids)
    with pytest.raises(ValueError):
        store.new_id("  ")


def test_artifact_models_minimal_construction() -> None:
    meta = ArtifactMeta(
        id="cp_20260101_000000_abcdef",
        stage=state_machine.STAGE_COMPANY_POOL,
        profile_name="alice",
        created_at="2026-01-01T00:00:00",
    )
    assert meta.version == 1
    assert meta.inputs == {}
    assert TargetSpec().target_tiers == []
    assert ProfileSnapshot().name == ""
    entry = CompanyEntry(id="bytedance", name="字节跳动", tier="大厂", industry="互联网", scrapable=True)
    assert entry.status == "recommended"
    pool = CompanyPool(meta=meta, target_spec=TargetSpec(), companies=[entry])
    assert pool.counts == {}
    jd = JDEvidence(id="JD001", company_id="bytedance", company="字节跳动", tier="大厂", title="后端")
    assert jd.detail_status == "missing"
    interview = InterviewEvidence(id="IV001")
    assert interview.highlights == []
    run = EvidenceRun(meta=meta, target_spec=TargetSpec(), company_pool_id="cp_x")
    assert run.jd_items == []
    item = RequirementItem(
        term="Python",
        category="skill",
        jd_count=1,
        jd_frequency=1.0,
        company_count=1,
        company_frequency=1.0,
    )
    assert item.ci_low is None
    hard = HardRequirement(evidence_id="JD001")
    assert hard.company == ""
    requirement = RequirementProfile(meta=meta, evidence_run_id="ev_x")
    assert requirement.interpretation == {}
    change = PlanChange(type="add_task")
    assert change.evidence_ids == []
    plan = ExecutionPlan(meta=meta)
    assert plan.applied is False
    assert plan.changes == []


def test_legacy_adapter_maps_snapshot_and_target_spec() -> None:
    profile = CareerProfile(
        who={"name": "张三", "city": "上海", "graduation_year": "2027"},
        have={"skills": ["Python"]},
        want={
            "target_role": "AI Agent 开发",
            "direction": "AI 应用",
            "city": "北京",
            "target_tiers": ["大厂", "中厂"],
            "bridge_tiers": ["小厂"],
            "constraints": ["不加班", "上海优先"],
        },
        gap={"summary": "缺项目"},
        plan={"roadmap": {"phases": []}},
        summary="测试档案",
        updated_at="2026-01-02T03:04:05",
    )
    snapshot = profile_snapshot(profile)
    assert snapshot.name == "张三"
    assert snapshot.who["city"] == "上海"
    assert snapshot.have["skills"] == ["Python"]
    assert snapshot.summary == "测试档案"
    assert snapshot.updated_at == "2026-01-02T03:04:05"

    profile.who["name"] = "李四"
    assert snapshot.who["name"] == "张三"

    spec = target_spec(profile)
    assert spec.role == "AI Agent 开发"
    assert spec.direction == "AI 应用"
    assert spec.city == "北京"
    assert spec.target_tiers == ["大厂", "中厂"]
    assert spec.bridge_tiers == ["小厂"]
    assert spec.graduation_year == "2027"
    assert spec.constraints == ["不加班", "上海优先"]


def test_legacy_adapter_defaults_for_empty_profile() -> None:
    profile = CareerProfile()
    spec = target_spec(profile)
    assert spec.role == ""
    assert spec.direction == ""
    assert spec.city == ""
    assert spec.target_tiers == ["大厂"]
    assert spec.bridge_tiers == ["中厂"]
    assert spec.graduation_year == ""
    assert spec.constraints == []
    snapshot = profile_snapshot(profile)
    assert snapshot.name == ""
    assert snapshot.who == {}
    assert snapshot.plan == {}

    profile.want["target_role"] = "数据分析"
    profile.who["city"] = "杭州"
    profile.want["graduation_year"] = "2028"
    assert target_spec(profile).role == "数据分析"
    assert target_spec(profile).city == "杭州"
    assert target_spec(profile).graduation_year == "2028"


def test_state_machine_without_artifacts(store: ArtifactStore, core_state: dict[str, Any]) -> None:
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_PROFILE
    # 空档案还没有任何内容：先走采集卡，而不是 finalize 空档案。
    assert result["next_tool"] == "intake(section='bundle')"
    assert all(value == "" for value in result["artifact_ids"].values())
    assert result["optional_next_tools"] == []


def test_state_machine_unconfirmed_pool_requires_selection(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    store.save(
        _pool(store, confirmed=False, baseline_plan_id=chain["baseline_plan_id"])
    )
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_COMPANY_POOL
    assert result["next_tool"] == "select_target_companies"


def test_state_machine_confirmed_pool_collects_evidence(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EVIDENCE
    assert result["next_tool"] == "collect_company_evidence"
    assert result["artifact_ids"]["company_pool_id"] == pool_id
    assert result["artifact_ids"]["evidence_run_id"] == ""


def test_state_machine_evidence_analyzes_requirements(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    evidence_id = store.save(_evidence(store, pool_id))
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_REQUIREMENT
    assert result["next_tool"] == "analyze_company_requirements"
    assert result["artifact_ids"]["evidence_run_id"] == evidence_id


def test_state_machine_requirement_plans_execution(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    evidence_id = store.save(_evidence(store, pool_id))
    requirement_id = store.save(_requirement(store, evidence_id))
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert result["next_tool"] == "plan_execution_alignment"
    assert result["artifact_ids"]["requirement_profile_id"] == requirement_id


def test_state_machine_unapplied_plan_awaits_confirmation(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    evidence_id = store.save(_evidence(store, pool_id))
    requirement_id = store.save(_requirement(store, evidence_id))
    plan_id = store.save(_plan(store, requirement_id, applied=False))
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert result["next_tool"] == "save_execution_alignment"
    assert result["artifact_ids"]["execution_plan_id"] == plan_id


def test_state_machine_applied_plan_enters_execution(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    evidence_id = store.save(_evidence(store, pool_id))
    requirement_id = store.save(_requirement(store, evidence_id))
    store.save(_plan(store, requirement_id, applied=True))
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EXECUTION
    assert result["next_tool"] == "generate_tasks"
    assert result["artifact_ids"]["execution_plan_id"] != ""


def test_state_machine_stale_execution_state_requires_regeneration(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    evidence_id = store.save(_evidence(store, pool_id))
    requirement_id = store.save(_requirement(store, evidence_id))
    old_plan_id = store.save(_plan(store, requirement_id, applied=True))
    current_plan_id = store.save(_plan(store, requirement_id, applied=True))
    stale_execution_id = store.save(
        ExecutionState(
            meta=_meta(store, state_machine.STAGE_EXECUTION),
            execution_plan_id=old_plan_id,
        )
    )
    core_state["value"] = {
        "execution_plan_id": current_plan_id,
        "execution_state_id": stale_execution_id,
    }
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EXECUTION
    assert result["next_tool"] == "generate_tasks"
    assert result["artifact_ids"]["execution_state_id"] == ""


def test_state_machine_prefers_core_state_artifact_ids(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    old_pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    old_evidence_id = store.save(_evidence(store, old_pool_id))
    core_state["value"] = {
        "company_pool_id": old_pool_id,
        "evidence_run_id": old_evidence_id,
    }
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_REQUIREMENT
    assert result["artifact_ids"]["company_pool_id"] == old_pool_id
    assert result["artifact_ids"]["evidence_run_id"] == old_evidence_id


def test_state_machine_stale_evidence_forces_recollection(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    old_pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    new_pool_id = store.save(
        _pool(store, confirmed=True, baseline_plan_id=chain["baseline_plan_id"])
    )
    stale_evidence_id = store.save(_evidence(store, old_pool_id))
    core_state["value"] = {
        "company_pool_id": new_pool_id,
        "evidence_run_id": stale_evidence_id,
    }
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_EVIDENCE
    assert result["next_tool"] == "collect_company_evidence"
    assert result["artifact_ids"]["company_pool_id"] == new_pool_id
    assert result["artifact_ids"]["evidence_run_id"] == ""

def test_market_baseline_without_target_spec_cannot_advance(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    store.save(
        MarketBaseline(
            meta=_meta(store, state_machine.STAGE_MARKET),
            target_spec=TargetSpec(role="AI Agent 开发"),
        )
    )
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_MARKET
    assert result["next_tool"] == "gather_research_data"
    assert "target_spec_id" in result["reason"]
    assert result["artifact_ids"]["market_baseline_id"] == ""
    assert result["artifact_ids"]["target_spec_id"] == chain["target_spec_id"]


def test_gap_report_without_market_baseline_cannot_advance(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    chain = _seed_upstream(store)
    store.save(
        GapReport(
            meta=_meta(store, state_machine.STAGE_GAP),
            profile_snapshot_id=chain["profile_id"],
        )
    )
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_GAP
    assert result["next_tool"] == "analyze_gaps"
    assert "market_baseline_id" in result["reason"]


def test_company_pool_without_baseline_plan_cannot_advance(
    store: ArtifactStore, core_state: dict[str, Any]
) -> None:
    _seed_upstream(store)
    store.save(_pool(store, confirmed=True))
    result = state_machine.next_action("alice")
    assert result["stage"] == state_machine.STAGE_COMPANY_POOL
    assert result["next_tool"] == "select_target_companies"
    assert "baseline_plan_id" in result["reason"]
