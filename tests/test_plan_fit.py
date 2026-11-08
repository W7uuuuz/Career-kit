"""计划失配检测回归——信号、状态、只读性与工具返回格式。

所有用例使用 tmp_path 隔离数据目录，不读写真实 ~/.career-kit，不联网。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.tools.profile as profile_module
from src import paths
from src.core.artifacts.models import (
    ApplicationState,
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    ExecutionPlan,
    JDEvidence,
    RequirementItem,
    RequirementProfile,
    ReviewReport,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.plan_fit import check_plan_fit
from src.models import Application, CareerProfile, Task
from src.tools.plan_fit_tools import check_plan_fit as check_plan_fit_tool

PROFILE_NAME = "default"


def _iso(days: float = 0) -> str:
    return (datetime.now() + timedelta(days=days)).isoformat()


def _meta(
    store: ArtifactStore,
    stage: str,
    prefix: str,
    *,
    created_at: str | None = None,
    inputs: dict[str, str] | None = None,
) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage,
        profile_name=PROFILE_NAME,
        created_at=created_at or _iso(),
        inputs=inputs or {},
    )


def _save_pool(store: ArtifactStore, *, created_at: str | None = None) -> str:
    return store.save(
        CompanyPool(
            meta=_meta(store, state_machine.STAGE_COMPANY_POOL, "cp", created_at=created_at),
            target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
            companies=[
                CompanyEntry(
                    id="bytedance",
                    name="字节跳动",
                    tier="大厂",
                    industry="互联网",
                    scrapable=True,
                    status="confirmed",
                )
            ],
        )
    )


def _save_evidence(
    store: ArtifactStore,
    pool_id: str,
    *,
    created_at: str | None = None,
    confidence: tuple[str, str] = ("high", "high"),
) -> str:
    jd_items = [
        JDEvidence(
            id=f"JD{index:03d}",
            company_id=f"company_{index}",
            company=f"公司{index}",
            tier="大厂",
            title="AI Agent 工程师",
            detail_status="ok",
        )
        for index in (1, 2)
    ]
    return store.save(
        EvidenceRun(
            meta=_meta(
                store,
                state_machine.STAGE_EVIDENCE,
                "ev",
                created_at=created_at,
                inputs={"company_pool_id": pool_id},
            ),
            target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
            company_pool_id=pool_id,
            jd_items=jd_items,
            confidence={"jd": confidence[0], "interview": confidence[1]},
        )
    )


def _requirement_items(terms: tuple[str, ...], evidence_ids: tuple[str, ...]) -> list[RequirementItem]:
    return [
        RequirementItem(
            term=term,
            category="skill",
            jd_count=len(evidence_ids),
            jd_frequency=1.0,
            company_count=2,
            company_frequency=1.0,
            companies=["公司1", "公司2"],
            evidence_ids=list(evidence_ids),
        )
        for term in terms
    ]


def _save_requirement(
    store: ArtifactStore,
    evidence_id: str,
    *,
    terms: tuple[str, ...] = ("RAG",),
    interview_terms: tuple[str, ...] = (),
    confidence: tuple[str, str] = ("high", "high"),
    created_at: str | None = None,
) -> str:
    return store.save(
        RequirementProfile(
            meta=_meta(
                store,
                state_machine.STAGE_REQUIREMENT,
                "rp",
                created_at=created_at,
                inputs={"evidence_run_id": evidence_id},
            ),
            evidence_run_id=evidence_id,
            sample_size_jd=30 if confidence[0] == "high" else 4,
            sample_size_interview=20 if confidence[1] == "high" else 2,
            confidence_jd=confidence[0],
            confidence_interview=confidence[1],
            high_frequency=_requirement_items(terms, ("JD001", "JD002")),
            interview_topics=_requirement_items(interview_terms, ("IV001",)),
        )
    )


def _save_plan(
    store: ArtifactStore,
    requirement_id: str,
    *,
    created_at: str | None = None,
    applied: bool = True,
    roadmap: dict[str, Any] | None = None,
) -> str:
    return store.save(
        ExecutionPlan(
            meta=_meta(
                store,
                state_machine.STAGE_EXECUTION_PLAN,
                "ep",
                created_at=created_at,
            ),
            requirement_profile_id=requirement_id,
            strategy_summary="执行版",
            roadmap=roadmap
            or {
                "strategy_summary": "执行版",
                "phases": [
                    {
                        "id": "phase_1",
                        "type": "learn",
                        "name": "阶段",
                        "goal": "目标",
                        "milestones": [
                            {
                                "name": "里程碑",
                                "tasks": [{"name": "实现 RAG 检索", "priority": "high"}],
                            }
                        ],
                    }
                ],
            },
            diff_summary="按企业需求校准",
            applied=applied,
        )
    )


def _save_profile(
    *,
    tasks: list[Task] | None = None,
    core_state: dict[str, Any] | None = None,
    gap_stale_at: str = "",
    plan_saved_at: str = "",
    section_updated_at: dict[str, str] | None = None,
    applications: list[Application] | None = None,
    have: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> CareerProfile:
    profile = CareerProfile(
        who={"name": "张三"},
        have=have if have is not None else {"skills": ["Python"]},
        want={"target_role": "AI Agent 开发", "city": "北京"},
        plan=plan
        if plan is not None
        else {
            "roadmap": {
                "phases": [
                    {
                        "id": "phase_1",
                        "type": "learn",
                        "name": "阶段",
                        "goal": "目标",
                        "milestones": [{"name": "里程碑", "tasks": []}],
                    }
                ]
            }
        },
        tasks=tasks or [],
        core_state=core_state or {},
        gap_stale_at=gap_stale_at,
        plan_saved_at=plan_saved_at,
        section_updated_at=section_updated_at or {},
        applications=applications or [],
    )
    profile_module.save_profile(profile, PROFILE_NAME)
    return profile


def _core_state(pool_id: str, evidence_id: str, requirement_id: str, plan_id: str) -> dict[str, str]:
    return {
        "stage": "executing",
        "company_pool_id": pool_id,
        "evidence_run_id": evidence_id,
        "requirement_profile_id": requirement_id,
        "execution_plan_id": plan_id,
    }


def _rag_task() -> Task:
    return Task(id="task_rag", name="实现 RAG 检索", phase_id="phase_1", status="pending")


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_module, "PROFILE_DIR", root)
    return SimpleNamespace(root=root, store=ArtifactStore())


def _seed_aligned(workspace: SimpleNamespace) -> dict[str, str]:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-2))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    plan_id = _save_plan(store, requirement_id, created_at=_iso())
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
        plan_saved_at=_iso(-1),
    )
    return {
        "pool_id": pool_id,
        "evidence_id": evidence_id,
        "requirement_id": requirement_id,
        "plan_id": plan_id,
    }


def _seed_chain(
    workspace: SimpleNamespace,
    *,
    terms: tuple[str, ...],
    tasks: list[Task],
    have: dict[str, Any] | None = None,
    profile_plan: dict[str, Any] | None = None,
    roadmap: dict[str, Any] | None = None,
    confidence: tuple[str, str] = ("high", "high"),
) -> dict[str, str]:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(
        store, pool_id, created_at=_iso(-3), confidence=confidence
    )
    requirement_id = _save_requirement(
        store, evidence_id, terms=terms, confidence=confidence, created_at=_iso(-2)
    )
    plan_id = _save_plan(store, requirement_id, created_at=_iso(-1), roadmap=roadmap)
    _save_profile(
        tasks=tasks,
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
        plan_saved_at=_iso(-1),
        have=have,
        plan=profile_plan,
    )
    return {
        "pool_id": pool_id,
        "evidence_id": evidence_id,
        "requirement_id": requirement_id,
        "plan_id": plan_id,
    }


def test_aligned_is_read_only(workspace: SimpleNamespace) -> None:
    ids = _seed_aligned(workspace)
    before = profile_module.load_profile(PROFILE_NAME).model_dump()

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "aligned"
    assert result["trigger"] == "manual"
    assert result["signals"] == []
    assert result["recommended_action"] == "continue"
    assert result["next_tool"] == ""
    assert result["question_for_user"] == ""
    assert result["artifact_ids"] == {
        "company_pool_id": ids["pool_id"],
        "evidence_run_id": ids["evidence_id"],
        "requirement_profile_id": ids["requirement_id"],
        "execution_plan_id": ids["plan_id"],
    }
    after = profile_module.load_profile(PROFILE_NAME).model_dump()
    assert after == before


def test_stale_evidence(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-12))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-10))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-9))
    plan_id = _save_plan(store, requirement_id, created_at=_iso(-8))
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
        plan_saved_at=_iso(-8),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "stale_evidence"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["stale_evidence"]["severity"] == "medium"
    assert signals["stale_evidence"]["evidence_ids"] == [evidence_id]
    assert result["recommended_action"] == "refresh_evidence"
    assert result["next_tool"] == "collect_company_evidence"
    assert result["question_for_user"]


def test_alignment_missing(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-2))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    _save_profile(
        tasks=[_rag_task()],
        core_state={
            "stage": "need_execution_plan",
            "company_pool_id": pool_id,
            "evidence_run_id": evidence_id,
            "requirement_profile_id": requirement_id,
        },
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "major_drift"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["alignment_missing"]["severity"] == "high"
    assert signals["alignment_missing"]["evidence_ids"] == [evidence_id]
    assert result["next_tool"] == "plan_execution_alignment"
    assert result["recommended_action"] == "rerun_alignment"
    assert result["question_for_user"]


def test_alignment_stale(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-4))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-1))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    plan_id = _save_plan(store, "rp_not_the_latest", created_at=_iso(-2))
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "major_drift"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["alignment_stale"]["severity"] == "high"
    assert result["next_tool"] == "plan_execution_alignment"


def test_uncovered_requirement_high_confidence_is_major(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-3))
    requirement_id = _save_requirement(store, evidence_id, terms=("RAG",), created_at=_iso(-2))
    plan_id = _save_plan(store, requirement_id, created_at=_iso(-1))
    _save_profile(
        tasks=[Task(id="task_python", name="学习 Python 基础", phase_id="phase_1", status="pending")],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "major_drift"
    uncovered = [
        signal for signal in result["signals"] if signal["code"] == "uncovered_requirement"
    ]
    assert uncovered
    assert uncovered[0]["severity"] == "high"
    assert uncovered[0]["evidence_ids"] == ["JD001", "JD002"]
    assert result["next_tool"] == "plan_execution_alignment"


def test_uncovered_requirement_low_confidence_is_observation_only(
    workspace: SimpleNamespace,
) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(
        store, pool_id, created_at=_iso(-3), confidence=("low", "low")
    )
    requirement_id = _save_requirement(
        store,
        evidence_id,
        terms=("RAG",),
        confidence=("low", "low"),
        created_at=_iso(-2),
    )
    plan_id = _save_plan(store, requirement_id, created_at=_iso(-1))
    _save_profile(
        tasks=[Task(id="task_python", name="学习 Python 基础", phase_id="phase_1", status="pending")],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] != "major_drift"
    assert all(signal["severity"] != "high" for signal in result["signals"])
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["uncovered_requirement"]["severity"] == "info"
    assert signals["insufficient_sample"]["severity"] == "info"


def test_alias_coverage_avoids_false_major_drift(workspace: SimpleNamespace) -> None:
    tasks = [
        Task(
            id="task_fastapi",
            name="用 FastAPI 实现简历解析服务",
            phase_id="phase_1",
            status="pending",
        ),
        Task(
            id="task_agent",
            name="搭建 Agent + RAG 问答项目",
            phase_id="phase_1",
            status="pending",
        ),
        Task(
            id="task_pr",
            name="给开源项目提交 PR 并参与 Code Review 评审",
            phase_id="phase_1",
            status="pending",
        ),
    ]
    _seed_chain(
        workspace,
        terms=("Python", "大模型", "协作", "产品"),
        tasks=tasks,
    )

    result = check_plan_fit(PROFILE_NAME)

    uncovered = {
        signal["message"]: signal
        for signal in result["signals"]
        if signal["code"] == "uncovered_requirement"
    }
    joined = "\n".join(uncovered)
    assert "Python" not in joined
    assert "大模型" not in joined
    assert "协作" not in joined
    assert any("产品" in message for message in uncovered)
    product = next(
        signal for message, signal in uncovered.items() if "产品" in message
    )
    assert product["severity"] == "info"
    assert all(signal["severity"] != "high" for signal in result["signals"])
    assert result["status"] != "major_drift"
    assert result["status"] == "aligned"


def test_truly_uncovered_hard_skill_stays_high(workspace: SimpleNamespace) -> None:
    _seed_chain(
        workspace,
        terms=("Kubernetes",),
        tasks=[_rag_task()],
    )

    result = check_plan_fit(PROFILE_NAME)

    uncovered = [
        signal for signal in result["signals"] if signal["code"] == "uncovered_requirement"
    ]
    assert len(uncovered) == 1
    assert "Kubernetes" in uncovered[0]["message"]
    assert uncovered[0]["severity"] == "high"
    assert result["status"] == "major_drift"
    assert result["next_tool"] == "plan_execution_alignment"


def test_have_skills_participate_in_coverage(workspace: SimpleNamespace) -> None:
    _seed_chain(
        workspace,
        terms=("Python",),
        tasks=[],
        have={"skills": [{"name": "FastAPI", "skill": "FastAPI"}]},
    )

    result = check_plan_fit(PROFILE_NAME)

    uncovered = [
        signal for signal in result["signals"] if signal["code"] == "uncovered_requirement"
    ]
    assert uncovered == []
    assert result["status"] == "aligned"


def test_phase_goal_and_kpi_participate_in_coverage(
    workspace: SimpleNamespace,
) -> None:
    profile_plan = {
        "roadmap": {
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "阶段",
                    "goal": "掌握后端微服务架构",
                    "kpi": {
                        "metric": "服务数",
                        "target": "完成 3 个分布式服务",
                        "evidence": "仓库链接",
                    },
                    "milestones": [
                        {
                            "name": "里程碑",
                            "done_criteria": "能独立部署",
                            "deliverable": "可运行仓库",
                            "tasks": [],
                        }
                    ],
                }
            ]
        }
    }
    _seed_chain(
        workspace,
        terms=("后端", "微服务", "分布式", "架构"),
        tasks=[],
        profile_plan=profile_plan,
    )

    result = check_plan_fit(PROFILE_NAME)

    uncovered = [
        signal for signal in result["signals"] if signal["code"] == "uncovered_requirement"
    ]
    assert uncovered == []
    assert result["status"] == "aligned"


def test_goal_changed(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-2))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    plan_id = _save_plan(store, requirement_id, created_at=_iso())
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
        gap_stale_at=_iso(),
        plan_saved_at=_iso(-1),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "major_drift"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["goal_changed"]["severity"] == "high"
    assert result["recommended_action"] == "rerun_gap"
    assert result["next_tool"] == "analyze_gaps"


def test_funnel_signal_suggests_review(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-2))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    plan_id = _save_plan(store, requirement_id, created_at=_iso())
    applications = [
        Application(
            id=f"app_{index:03d}",
            company=f"公司{index}",
            status="applied",
            events=[{"status": "applied", "at": _iso(-1)}],
        )
        for index in range(1, 6)
    ]
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
        applications=applications,
    )

    result = check_plan_fit(PROFILE_NAME, trigger="weekly_review")

    assert result["status"] == "minor_drift"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["funnel_signal"]["severity"] == "medium"
    assert result["recommended_action"] == "review"
    assert result["next_tool"] == "get_weekly_review"
    assert result["trigger"] == "weekly_review"


def test_old_profile_without_artifacts_is_incomplete_chain(
    workspace: SimpleNamespace,
) -> None:
    _save_profile(tasks=[])

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "incomplete_chain"
    assert result["recommended_action"] == "continue"
    assert result["next_tool"] == ""
    assert result["question_for_user"] == ""
    assert result["artifact_ids"] == {
        "company_pool_id": "",
        "evidence_run_id": "",
        "requirement_profile_id": "",
        "execution_plan_id": "",
    }
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["incomplete_chain"]["severity"] == "info"


def test_tool_returns_json_string(workspace: SimpleNamespace) -> None:
    _seed_aligned(workspace)

    raw = check_plan_fit_tool(trigger="milestone")

    assert isinstance(raw, str)
    data = json.loads(raw)
    assert data["status"] == "aligned"
    assert data["trigger"] == "milestone"


def test_tool_is_read_only(workspace: SimpleNamespace) -> None:
    _seed_aligned(workspace)
    before_profile = profile_module.load_profile(PROFILE_NAME).model_dump()
    before_reviews = workspace.store.list(PROFILE_NAME, state_machine.STAGE_REVIEW)

    raw = check_plan_fit_tool(trigger="manual")

    assert json.loads(raw)["status"] == "aligned"
    assert profile_module.load_profile(PROFILE_NAME).model_dump() == before_profile
    assert workspace.store.list(PROFILE_NAME, state_machine.STAGE_REVIEW) == before_reviews


def test_tool_does_not_advance_empty_profile(workspace: SimpleNamespace) -> None:
    profile_module.save_profile(CareerProfile(), PROFILE_NAME)

    raw = check_plan_fit_tool(trigger="manual")

    assert json.loads(raw)["status"] == "incomplete_chain"
    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_PROFILE
    assert action["next_tool"] == "finalize_profile"


def test_unapplied_execution_plan_is_not_aligned(workspace: SimpleNamespace) -> None:
    store = workspace.store
    pool_id = _save_pool(store, created_at=_iso(-3))
    evidence_id = _save_evidence(store, pool_id, created_at=_iso(-2))
    requirement_id = _save_requirement(store, evidence_id, created_at=_iso(-1))
    plan_id = _save_plan(store, requirement_id, created_at=_iso(), applied=False)
    _save_profile(
        tasks=[_rag_task()],
        core_state=_core_state(pool_id, evidence_id, requirement_id, plan_id),
    )

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] != "aligned"
    signals = {signal["code"]: signal for signal in result["signals"]}
    assert signals["plan_not_applied"]["severity"] == "high"
    assert result["recommended_action"] == "rerun_alignment"
    assert result["next_tool"] == "save_execution_alignment"


def test_optional_artifacts_do_not_complete_chain(workspace: SimpleNamespace) -> None:
    store = workspace.store
    store.save(
        ApplicationState(
            meta=_meta(store, state_machine.STAGE_APPLICATIONS, "as")
        )
    )
    store.save(
        ReviewReport(meta=_meta(store, state_machine.STAGE_REVIEW, "rr"))
    )
    _save_profile(tasks=[])

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "incomplete_chain"


def test_cleared_core_state_ignores_stale_artifacts(workspace: SimpleNamespace) -> None:
    _seed_aligned(workspace)
    assert workspace.store.list(PROFILE_NAME), "测试前置：库中应已有 artifact"

    profile = profile_module.load_profile(PROFILE_NAME)
    profile.core_state = {}
    profile_module.save_profile(profile, PROFILE_NAME)

    result = check_plan_fit(PROFILE_NAME)

    assert result["status"] == "incomplete_chain"
    assert result["recommended_action"] == "continue"
    assert result["next_tool"] == ""
    assert result["artifact_ids"] == {
        "company_pool_id": "",
        "evidence_run_id": "",
        "requirement_profile_id": "",
        "execution_plan_id": "",
    }
