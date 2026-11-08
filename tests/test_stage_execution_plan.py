"""阶段 9 执行方案校准回归——预览门禁、应用、证据校验与状态机衔接。

所有用例使用 tmp_path 隔离数据目录，不读写真实 ~/.career-kit，不联网。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.tools.profile as profile_module
from src import paths
from src.core.artifacts.models import (
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    JDEvidence,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import execution_plan as stage
from src.models import CareerProfile, Task

PROFILE_NAME = "default"
DIFF_SUMMARY = "移除旧 pending 任务，新增 RAG 任务"


def _meta(store: ArtifactStore, stage_id: str, prefix: str, inputs: dict[str, str] | None = None) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage_id,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
        inputs=inputs or {},
    )


def _seed_chain() -> dict[str, Any]:
    store = ArtifactStore()
    pool_id = store.save(
        CompanyPool(
            meta=_meta(store, state_machine.STAGE_COMPANY_POOL, "cp"),
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
    evidence_id = store.save(
        EvidenceRun(
            meta=_meta(
                store,
                state_machine.STAGE_EVIDENCE,
                "ev",
                inputs={"company_pool_id": pool_id},
            ),
            target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
            company_pool_id=pool_id,
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
    )
    requirement_id = store.save(
        RequirementProfile(
            meta=_meta(
                store,
                state_machine.STAGE_REQUIREMENT,
                "rp",
                inputs={"evidence_run_id": evidence_id},
            ),
            evidence_run_id=evidence_id,
            sample_size_jd=1,
            confidence_jd="low",
            high_frequency=[
                RequirementItem(
                    term="RAG",
                    category="skill",
                    jd_count=1,
                    jd_frequency=1.0,
                    company_count=1,
                    company_frequency=1.0,
                    companies=["字节跳动"],
                    evidence_ids=["JD001"],
                )
            ],
        )
    )
    return {
        "store": store,
        "pool_id": pool_id,
        "evidence_id": evidence_id,
        "requirement_id": requirement_id,
    }


def _baseline_plan() -> dict[str, Any]:
    return {
        "roadmap": {
            "strategy_summary": "旧策略：先打基础",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "基础补齐",
                    "goal": "掌握基础",
                    "milestones": [
                        {
                            "id": "phase_1_ms_1",
                            "name": "基础里程碑",
                            "done_criteria": "能独立完成",
                            "tasks": [{"name": "旧基础任务", "priority": "high"}],
                        }
                    ],
                },
                {
                    "id": "phase_2",
                    "type": "project",
                    "name": "项目实战",
                    "goal": "做出项目",
                    "milestones": [
                        {
                            "id": "phase_2_ms_1",
                            "name": "项目里程碑",
                            "tasks": [{"name": "旧项目任务", "priority": "medium"}],
                        }
                    ],
                },
            ],
        }
    }


def _seed_profile(chain: dict[str, Any]) -> CareerProfile:
    profile = CareerProfile(
        who={"name": "张三"},
        have={
            "skills": ["Python"],
            "capability_evidence": [
                {"task": "旧基础任务", "completed_at": "2026-01-02T10:00:00"}
            ],
        },
        want={"target_role": "AI Agent 开发", "city": "北京"},
        plan=_baseline_plan(),
        plan_saved_at="2026-01-01T00:00:00",
        tasks=[
            Task(
                id="task_001",
                name="旧基础任务",
                phase_id="phase_1",
                milestone_id="phase_1_ms_1",
                status="completed",
                completed_at="2026-01-02T10:00:00",
                how_to=["看文档", "写代码"],
                done_criteria="能独立完成",
            ),
            Task(
                id="task_002",
                name="旧跳过任务",
                phase_id="phase_1",
                milestone_id="phase_1_ms_1",
                status="skipped",
                completed_at="2026-01-03T10:00:00",
            ),
            Task(
                id="task_003",
                name="旧待办任务",
                phase_id="phase_2",
                milestone_id="phase_2_ms_1",
                status="pending",
            ),
            Task(
                id="task_004",
                name="旧进行中任务",
                phase_id="phase_2",
                milestone_id="phase_2_ms_1",
                status="in_progress",
                started_at="2026-01-04T10:00:00",
            ),
        ],
        core_state={
            "stage": "need_execution_plan",
            "company_pool_id": chain["pool_id"],
            "evidence_run_id": chain["evidence_id"],
            "requirement_profile_id": chain["requirement_id"],
        },
    )
    profile_module.save_profile(profile, PROFILE_NAME)
    return profile


def _new_roadmap() -> dict[str, Any]:
    return {
        "strategy_summary": "按企业需求重排",
        "phases": [
            {
                "type": "project",
                "name": "RAG 项目",
                "goal": "补齐 RAG 证据",
                "kpi": {"metric": "RAG 项目", "target": "可演示", "evidence": "GitHub 仓库"},
                "milestones": [
                    {
                        "name": "RAG MVP",
                        "done_criteria": "能回答真实文档问题",
                        "tasks": [
                            {
                                "name": "实现 RAG 检索",
                                "description": "接入向量检索",
                                "priority": "high",
                            }
                        ],
                    }
                ],
            },
            {
                "type": "intern",
                "name": "投递实习",
                "goal": "拿到面试机会",
                "milestones": [
                    {"name": "投递", "tasks": [{"name": "投递字节跳动", "priority": "medium"}]}
                ],
            },
        ],
    }


def _changes() -> list[dict[str, Any]]:
    return [
        {
            "type": "add_task",
            "phase_id": "phase_1",
            "details": {"name": "实现 RAG 检索"},
            "reason": "JD 高频要求",
            "evidence_ids": ["JD001"],
        },
        {
            "type": "remove_task",
            "task_id": "task_003",
            "reason": "旧任务无对应需求",
            "evidence_ids": ["JD001"],
        },
    ]


def _alignment(
    requirement_id: str,
    *,
    roadmap: dict[str, Any] | None = None,
    changes: list[dict[str, Any]] | None = None,
    diff_summary: str = DIFF_SUMMARY,
) -> dict[str, Any]:
    return {
        "requirement_profile_id": requirement_id,
        "strategy_summary": "按企业需求重排",
        "roadmap": _new_roadmap() if roadmap is None else roadmap,
        "changes": _changes() if changes is None else changes,
        "diff_summary": diff_summary,
    }


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_module, "PROFILE_DIR", root)
    chain = _seed_chain()
    _seed_profile(chain)
    return SimpleNamespace(
        root=root,
        store=chain["store"],
        pool_id=chain["pool_id"],
        evidence_id=chain["evidence_id"],
        requirement_id=chain["requirement_id"],
    )


@pytest.fixture()
def state_machine_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        state_machine,
        "load_profile",
        lambda name: profile_module.load_profile(name),
    )


def test_plan_execution_alignment_returns_baseline_and_completed_evidence(
    workspace: SimpleNamespace,
) -> None:
    payload = stage.plan_execution_alignment(workspace.requirement_id)

    assert payload["status"] == "ok"
    assert [phase["name"] for phase in payload["baseline_plan"]["phases"]] == [
        "基础补齐",
        "项目实战",
    ]
    completed = payload["completed_evidence"]
    assert [entry["task_id"] for entry in completed] == ["task_001", "task_002"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["how_to"] == ["看文档", "写代码"]
    assert completed[0]["done_criteria"] == "能独立完成"
    assert completed[1]["status"] == "skipped"
    assert payload["capability_evidence"][0]["task"] == "旧基础任务"
    assert payload["requirement"]["requirement_profile_id"] == workspace.requirement_id
    assert payload["requirement"]["high_frequency"][0]["term"] == "RAG"
    prompt = payload["alignment_prompt"]
    assert prompt["requirement_profile_id"] == workspace.requirement_id
    assert prompt["available_evidence_ids"] == ["JD001"]
    assert "evidence_ids" in prompt["rules"][0]
    assert prompt["output_json"]["changes"][0]["evidence_ids"] == [""]
    assert payload["next_steps"] == ["save_execution_alignment"]

    latest_payload = stage.plan_execution_alignment("")
    assert latest_payload["requirement"]["requirement_profile_id"] == workspace.requirement_id


def test_preview_does_not_modify_profile_and_awaits_confirmation(
    workspace: SimpleNamespace,
    state_machine_profiles: None,
) -> None:
    before = profile_module.load_profile(PROFILE_NAME).model_dump()
    alignment = _alignment(workspace.requirement_id)

    result = stage.save_execution_alignment(
        json.dumps(alignment, ensure_ascii=False), confirmed=False
    )

    assert result["status"] == "needs_confirmation"
    assert result["applied"] is False
    assert result["execution_plan_id"].startswith("ep_")
    assert result["diff_summary"] == DIFF_SUMMARY
    assert result["change_counts"] == {"add_task": 1, "remove_task": 1}
    assert [task["task_id"] for task in result["preserved_tasks"]] == ["task_001", "task_002"]
    assert [task["task_id"] for task in result["removed_tasks"]] == ["task_003", "task_004"]
    assert result["next_steps"] == ["save_execution_alignment"]

    after = profile_module.load_profile(PROFILE_NAME)
    assert after.model_dump() == before

    artifact = workspace.store.latest(PROFILE_NAME, state_machine.STAGE_EXECUTION_PLAN)
    assert artifact is not None
    assert artifact["meta"]["id"] == result["execution_plan_id"]
    assert artifact["applied"] is False
    assert artifact["requirement_profile_id"] == workspace.requirement_id
    assert all(change["evidence_ids"] for change in artifact["changes"])

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTION_PLAN
    assert action["next_tool"] == "save_execution_alignment"
    assert action["artifact_ids"]["execution_plan_id"] == result["execution_plan_id"]


def test_confirm_applies_plan_and_enters_executing(
    workspace: SimpleNamespace,
    state_machine_profiles: None,
) -> None:
    before = profile_module.load_profile(PROFILE_NAME)
    alignment = _alignment(workspace.requirement_id)

    result = stage.save_execution_alignment(
        json.dumps(alignment, ensure_ascii=False), confirmed=True
    )

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert result["preserved_task_count"] == 2
    assert result["removed_task_count"] == 2
    assert result["next_steps"] == ["get_next_tasks", "generate_tasks"]

    profile = profile_module.load_profile(PROFILE_NAME)
    roadmap = profile.plan["roadmap"]
    assert roadmap["strategy_summary"] == "按企业需求重排"
    assert [phase["name"] for phase in roadmap["phases"]] == ["RAG 项目", "投递实习"]
    assert [phase["id"] for phase in roadmap["phases"]] == ["phase_1", "phase_2"]
    assert roadmap["phases"][0]["milestones"][0]["tasks"][0]["name"] == "实现 RAG 检索"

    retained_ids = {task.id for task in profile.tasks}
    assert retained_ids == {"task_001", "task_002"}
    retained = {task.id: task for task in profile.tasks}
    assert retained["task_001"].status == "completed"
    assert retained["task_001"].completed_at == "2026-01-02T10:00:00"
    assert retained["task_001"].how_to == ["看文档", "写代码"]
    assert retained["task_002"].status == "skipped"

    assert len(profile.plan_history) == 1
    assert profile.plan_history[0].source == "company_alignment"
    assert profile.plan_history[0].content == _baseline_plan()

    adjustment = profile.adjustments[-1]
    assert adjustment.trigger == "company_alignment"
    assert adjustment.trigger_type == "event"
    assert adjustment.reason == DIFF_SUMMARY
    assert len(adjustment.changes) == 2
    assert adjustment.changes[0]["evidence_ids"] == ["JD001"]

    assert profile.plan_saved_at != before.plan_saved_at
    assert profile.section_updated_at["plan"] == profile.plan_saved_at
    assert profile.core_state["stage"] == "executing"
    assert profile.core_state["execution_plan_id"] == result["execution_plan_id"]
    assert profile.core_state["requirement_profile_id"] == workspace.requirement_id
    assert profile.core_state["updated_at"]

    artifact = workspace.store.latest(PROFILE_NAME, state_machine.STAGE_EXECUTION_PLAN)
    assert artifact is not None
    assert artifact["meta"]["id"] == result["execution_plan_id"]
    assert artifact["applied"] is True
    assert artifact["meta"]["validation"]["applied"] is True

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTING
    assert action["next_tool"] == "get_next_tasks"
    assert action["artifact_ids"]["execution_plan_id"] == result["execution_plan_id"]


def test_change_without_evidence_ids_is_rejected(workspace: SimpleNamespace) -> None:
    before = profile_module.load_profile(PROFILE_NAME).model_dump()
    alignment = _alignment(
        workspace.requirement_id,
        changes=[
            {
                "type": "add_task",
                "phase_id": "phase_1",
                "details": {"name": "无证据任务"},
                "reason": "拍脑袋",
            }
        ],
    )

    with pytest.raises(stage.ExecutionPlanError) as exc_info:
        stage.save_execution_alignment(json.dumps(alignment, ensure_ascii=False), confirmed=False)

    assert exc_info.value.code == "INVALID_CHANGES"
    assert "evidence_ids" in json.dumps(exc_info.value.details, ensure_ascii=False)
    assert workspace.store.latest(PROFILE_NAME, state_machine.STAGE_EXECUTION_PLAN) is None
    assert profile_module.load_profile(PROFILE_NAME).model_dump() == before


@pytest.mark.parametrize(
    "roadmap",
    [
        {"strategy_summary": "空阶段", "phases": []},
        {
            "strategy_summary": "缺目标",
            "phases": [{"type": "learn", "name": "阶段", "goal": "", "milestones": []}],
        },
        {
            "strategy_summary": "缺任务名",
            "phases": [
                {
                    "type": "learn",
                    "name": "阶段",
                    "goal": "目标",
                    "milestones": [
                        {"name": "里程碑", "tasks": [{"description": "没有名字", "priority": "high"}]}
                    ],
                }
            ],
        },
        {
            "strategy_summary": "里程碑类型错",
            "phases": [
                {"type": "learn", "name": "阶段", "goal": "目标", "milestones": "not-a-list"}
            ],
        },
    ],
)
def test_invalid_roadmap_is_rejected(
    workspace: SimpleNamespace, roadmap: dict[str, Any]
) -> None:
    before = profile_module.load_profile(PROFILE_NAME).model_dump()
    alignment = _alignment(workspace.requirement_id, roadmap=roadmap)

    with pytest.raises(stage.ExecutionPlanError) as exc_info:
        stage.save_execution_alignment(json.dumps(alignment, ensure_ascii=False), confirmed=False)

    assert exc_info.value.code == "INVALID_ROADMAP"
    assert workspace.store.latest(PROFILE_NAME, state_machine.STAGE_EXECUTION_PLAN) is None
    assert profile_module.load_profile(PROFILE_NAME).model_dump() == before


def test_requirement_chain_mismatch_is_rejected(workspace: SimpleNamespace) -> None:
    other_id = workspace.store.save(
        RequirementProfile(
            meta=_meta(
                workspace.store,
                state_machine.STAGE_REQUIREMENT,
                "rp",
                inputs={"evidence_run_id": workspace.evidence_id},
            ),
            evidence_run_id=workspace.evidence_id,
            sample_size_jd=1,
        )
    )
    alignment = _alignment(other_id)

    with pytest.raises(stage.ExecutionPlanError) as exc_info:
        stage.save_execution_alignment(json.dumps(alignment, ensure_ascii=False), confirmed=False)

    assert exc_info.value.code == "REQUIREMENT_MISMATCH"
    assert workspace.store.latest(PROFILE_NAME, state_machine.STAGE_EXECUTION_PLAN) is None
