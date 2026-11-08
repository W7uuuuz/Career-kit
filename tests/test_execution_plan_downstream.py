"""执行版路线图下游回归：generate_tasks / get_next_tasks / get_progress / 地图导出。

覆盖阶段 9 应用执行版之后最容易断的一环：历史任务与新路线图共用 phase_id 时，
generate_tasks 必须继续生成新阶段的未生成任务，同时保留 completed/skipped 历史、
不复活旧 pending、不清空打卡与能力证据。

所有用例用 tmp_path 隔离档案与 artifact 目录，资产目录由 conftest 重定向，不联网。
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

import src.tools.profile as profile_store
from src import paths
from src.core.artifacts.models import (
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    HardRequirement,
    JDEvidence,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import execution_plan as stage
from src.models import CareerProfile, CheckIn, Task
from src.tools import task_tools

PROFILE_NAME = "default"
DIFF_SUMMARY = "按企业需求重排：新增 RAG 检索，移除旧 pending 任务"
EVIDENCE_RUN_ID = "ev_seed"


def _meta(store: ArtifactStore, stage_id: str, prefix: str, inputs: dict[str, str] | None = None) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage_id,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
        inputs=inputs or {},
    )


def _seed_chain(store: ArtifactStore) -> dict[str, str]:
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
            counts={"total": 1, "confirmed": 1},
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
                    requirements="熟悉 RAG、Agent 工具调用",
                )
            ],
            counts={"jd_kept": 1},
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
            sample_size_jd=3,
            sample_size_interview=1,
            confidence_jd="medium",
            confidence_interview="low",
            high_frequency=[
                RequirementItem(
                    term="RAG",
                    category="skill",
                    jd_count=3,
                    jd_frequency=0.75,
                    company_count=2,
                    company_frequency=0.66,
                    companies=["字节跳动", "京东"],
                    evidence_ids=["JD001"],
                )
            ],
            company_specific=[
                RequirementItem(
                    term="Agent 工具调用",
                    category="skill",
                    jd_count=2,
                    jd_frequency=0.5,
                    company_count=1,
                    company_frequency=0.33,
                    companies=["字节跳动"],
                    evidence_ids=["JD001"],
                )
            ],
            interview_topics=[
                RequirementItem(
                    term="RAG 检索链路",
                    category="topic",
                    jd_count=1,
                    jd_frequency=0.25,
                    company_count=1,
                    company_frequency=0.33,
                    companies=["字节跳动"],
                    evidence_ids=["JD001"],
                )
            ],
            hard_requirements=[
                HardRequirement(
                    evidence_id="JD001",
                    company="字节跳动",
                    title="AI Agent 工程师",
                    education="本科",
                    experience="3年以上",
                )
            ],
            nice_to_have=[
                RequirementItem(
                    term="LangGraph",
                    category="tool",
                    jd_count=1,
                    jd_frequency=0.25,
                    company_count=1,
                    company_frequency=1.0,
                    companies=["字节跳动"],
                    evidence_ids=["JD001"],
                )
            ],
            gaps=["面经样本不足"],
            interpretation={"summary": "RAG 与 Agent 工具调用是核心缺口"},
        )
    )
    return {"pool_id": pool_id, "evidence_id": evidence_id, "requirement_id": requirement_id}


def _baseline_plan() -> dict[str, Any]:
    return {
        "roadmap": {
            "strategy_summary": "基线：先打基础",
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


def _seed_profile(chain: dict[str, str]) -> CareerProfile:
    profile = CareerProfile(
        who={"name": "张三", "education": "双非本", "city": "北京"},
        have={
            "skills": ["Python"],
            "capability_evidence": [
                {"task": "旧基础任务", "completed_at": "2026-01-02T10:00:00", "notes": "手写练习"}
            ],
        },
        want={"target_role": "AI Agent 开发", "city": "北京"},
        gap={"start_level": "小厂", "match_score": 60},
        plan=_baseline_plan(),
        plan_saved_at="2026-01-01T00:00:00",
        checkins=[
            CheckIn(
                task_id="task_001",
                timestamp="2026-01-02T10:00:00",
                status="completed",
                notes="手写练习",
            )
        ],
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
                name="旧项目任务",
                phase_id="phase_2",
                milestone_id="phase_2_ms_1",
                status="pending",
            ),
        ],
        core_state={
            "stage": "need_execution_plan",
            "company_pool_id": chain["pool_id"],
            "evidence_run_id": chain["evidence_id"],
            "requirement_profile_id": chain["requirement_id"],
        },
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    return profile


def _execution_roadmap() -> dict[str, Any]:
    return {
        "strategy_summary": "按企业需求重排",
        "phases": [
            {
                "id": "phase_1",
                "type": "project",
                "name": "RAG 项目",
                "goal": "补齐 RAG 与 Agent 证据",
                "kpi": {"metric": "RAG 项目", "target": "可演示", "evidence": "GitHub 仓库"},
                "milestones": [
                    {
                        "id": "phase_1_ms_1",
                        "name": "RAG MVP",
                        "done_criteria": "能回答真实文档问题",
                        "tasks": [
                            {
                                "name": "实现 RAG 检索",
                                "description": "接入向量检索",
                                "priority": "high",
                            },
                            {
                                "name": "完成 Agent 工具调用",
                                "description": "实现工具编排",
                                "priority": "high",
                            },
                        ],
                    }
                ],
            },
            {
                "id": "phase_2",
                "type": "intern",
                "name": "投递实习",
                "goal": "拿到字节跳动面试机会",
                "milestones": [
                    {
                        "id": "phase_2_ms_1",
                        "name": "投递",
                        "done_criteria": "完成投递记录",
                        "tasks": [{"name": "投递字节跳动", "priority": "medium"}],
                    }
                ],
            },
        ],
    }


def _alignment(requirement_id: str) -> dict[str, Any]:
    return {
        "requirement_profile_id": requirement_id,
        "strategy_summary": "按企业需求重排",
        "roadmap": _execution_roadmap(),
        "changes": [
            {
                "type": "add_task",
                "phase_id": "phase_1",
                "details": {"name": "实现 RAG 检索"},
                "reason": "JD 高频要求 RAG",
                "evidence_ids": ["JD001"],
            },
            {
                "type": "remove_task",
                "task_id": "task_002",
                "reason": "旧任务无对应需求",
                "evidence_ids": ["JD001"],
            },
        ],
        "diff_summary": DIFF_SUMMARY,
    }


@pytest.fixture()
def applied_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)

    store = ArtifactStore()
    chain = _seed_chain(store)
    _seed_profile(chain)
    result = stage.save_execution_alignment(
        json.dumps(_alignment(chain["requirement_id"]), ensure_ascii=False), confirmed=True
    )
    return SimpleNamespace(
        root=root,
        store=store,
        chain=chain,
        result=result,
        requirement_id=chain["requirement_id"],
    )


def test_generate_tasks_after_alignment_adds_new_and_keeps_history(
    applied_workspace: SimpleNamespace,
) -> None:
    before = profile_store.load_profile(PROFILE_NAME)
    assert applied_workspace.result["applied"] is True
    assert {task.id for task in before.tasks} == {"task_001"}

    payload = json.loads(task_tools.generate_tasks())

    assert not payload.get("isError")
    assert payload["context"]["phase"] == "tasks_generated"
    assert payload["context"]["phase_id"] == "phase_1"
    assert payload["context"]["phase_name"] == "RAG 项目"
    assert payload["context"]["task_count"] == 2

    after = profile_store.load_profile(PROFILE_NAME)
    by_name = {task.name: task for task in after.tasks}
    assert "实现 RAG 检索" in by_name
    assert "完成 Agent 工具调用" in by_name
    assert "投递字节跳动" not in by_name  # 后续阶段保留里程碑，不生成空壳任务

    historical = by_name["旧基础任务"]
    assert historical.id == "task_001"
    assert historical.status == "completed"
    assert historical.completed_at == "2026-01-02T10:00:00"
    assert historical.how_to == ["看文档", "写代码"]
    assert "旧项目任务" not in by_name  # 旧 pending 任务不复活

    ids = [task.id for task in after.tasks]
    assert len(ids) == len(set(ids))
    assert len(after.tasks) == 3

    assert [checkin.task_id for checkin in after.checkins] == ["task_001"]
    assert after.checkins[0].notes == "手写练习"
    assert after.have["capability_evidence"] == before.have["capability_evidence"]


def test_get_next_tasks_returns_new_execution_tasks(applied_workspace: SimpleNamespace) -> None:
    task_tools.generate_tasks()

    output = task_tools.get_next_tasks()

    assert isinstance(output, str) and output
    assert "RAG 项目" in output
    assert "投递实习" in output  # 全流程概览保留后续阶段
    assert "[当前]" in output
    assert "实现 RAG 检索" in output
    assert "完成 Agent 工具调用" in output
    assert "旧项目任务" not in output


def test_get_progress_reflects_alignment_adjustment(applied_workspace: SimpleNamespace) -> None:
    task_tools.generate_tasks()

    output = task_tools.get_progress()

    assert isinstance(output, str) and output
    assert "阶段进度" in output
    assert "RAG 项目" in output
    assert "投递实习" in output
    assert "## 调整历史" in output
    assert DIFF_SUMMARY in output


def test_export_dashboard_roadmap_contains_execution_phase(
    applied_workspace: SimpleNamespace,
) -> None:
    task_tools.generate_tasks()

    output = task_tools.export_dashboard(mode="roadmap")

    assert "职业地图已生成" in output
    path = Path(output.split("：", 1)[1].splitlines()[0].strip())
    assert path.exists()

    html = path.read_text(encoding="utf-8")
    assert "RAG 项目" in html
    assert "投递实习" in html
    assert "实现 RAG 检索" in html
    assert "旧项目任务" not in html

    embedded = html.split('id="career-data">')[1].split("</script>")[0]
    data = json.loads(embedded)
    assert [phase["name"] for phase in data["phases"]] == ["RAG 项目", "投递实习"]
    current = next(phase for phase in data["phases"] if phase["is_current"])
    assert current["id"] == "phase_1"


def test_workflow_status_enters_execution(applied_workspace: SimpleNamespace) -> None:
    task_tools.generate_tasks()

    output = task_tools.get_workflow_status()

    assert "## 当前状态：execution" in output
    assert "### 企业适配（Core v2）" in output
    assert "- 阶段：executing" in output
    assert "- 下一步：get_next_tasks" in output or "下一步**：get_next_tasks" in output


def _isolate_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "history"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)


def test_generate_tasks_keeps_finished_tasks_from_deleted_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """应用执行版删除整个阶段后，该阶段下的 completed/skipped 任务不能丢。"""
    _isolate_profile(tmp_path, monkeypatch)
    profile = CareerProfile(
        who={"name": "张三"},
        plan={
            "roadmap": {
                "phases": [
                    {
                        "id": "phase_1",
                        "name": "新阶段",
                        "milestones": [
                            {"id": "m1", "name": "M", "tasks": [{"name": "新任务"}]}
                        ],
                    }
                ]
            }
        },
        tasks=[
            Task(
                id="task_001",
                name="已完成旧阶段任务",
                phase_id="deleted_phase",
                milestone_id="old_ms",
                status="completed",
                completed_at="2026-01-01T00:00:00",
            ),
            Task(
                id="task_002",
                name="已跳过旧阶段任务",
                phase_id="deleted_phase",
                milestone_id="old_ms",
                status="skipped",
            ),
            Task(
                id="task_003",
                name="旧待办",
                phase_id="phase_1",
                milestone_id="m1",
                status="pending",
            ),
        ],
    )
    profile_store.save_profile(profile, PROFILE_NAME)

    payload = json.loads(task_tools.generate_tasks())

    assert payload["context"]["phase"] == "tasks_generated"
    after = profile_store.load_profile(PROFILE_NAME)
    by_id = {task.id: task for task in after.tasks}
    assert by_id["task_001"].status == "completed"
    assert by_id["task_002"].status == "skipped"
    assert "task_003" not in by_id  # 旧 pending 不复活
    assert any(task.name == "新任务" for task in after.tasks)


def test_create_tasks_reuses_old_id_when_milestone_id_is_missing() -> None:
    """旧任务 milestone_id 不规范时，用 phase + name 兜底，避免同名重复任务。"""
    from src.tools.task_manager import create_tasks_from_roadmap

    profile = CareerProfile(
        plan={
            "roadmap": {
                "phases": [
                    {
                        "id": "phase_1",
                        "name": "P",
                        "milestones": [
                            {"id": "m1", "name": "M", "tasks": [{"name": "同名任务"}]}
                        ],
                    }
                ]
            }
        },
        tasks=[
            Task(
                id="task_009",
                name="同名任务",
                phase_id="phase_1",
                milestone_id="",
                status="completed",
                completed_at="2026-01-01T00:00:00",
            )
        ],
    )

    tasks = create_tasks_from_roadmap(profile, only_phase_ids={"phase_1"})

    assert len(tasks) == 1
    assert tasks[0].id == "task_009"
    assert tasks[0].status == "completed"


def test_stage_position_fallback_walks_all_twelve_keys() -> None:
    """状态机不可用时，兜底要遍历完整 12 个 core_state key，而不是硬编码 10。"""
    profile = CareerProfile(
        core_state={
            "profile_id": "pf_1",
            "target_spec_id": "ts_1",
            "market_baseline_id": "mb_1",
            "gap_report_id": "gr_1",
            "baseline_plan_id": "bp_1",
            "company_pool_id": "cp_1",
            "evidence_run_id": "ev_1",
            "requirement_profile_id": "rp_1",
            "execution_plan_id": "ep_1",
            "execution_state_id": "es_1",
        }
    )

    index, name, next_tool = task_tools._stage_position(profile, {})

    assert index == 11
    assert name == "求职投递管理"
    assert next_tool == "record_application"


def test_workflow_status_plan_fit_does_not_override_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """执行中 plan_fit 指向上游采集时，只能作为提示，主下一步仍是 get_next_tasks。"""
    _isolate_profile(tmp_path, monkeypatch)
    profile = CareerProfile(
        who={"name": "张三"},
        summary="已确认",
        plan={
            "roadmap": {
                "phases": [
                    {
                        "id": "phase_1",
                        "name": "阶段",
                        "milestones": [
                            {"id": "m1", "name": "M", "tasks": [{"name": "任务A"}]}
                        ],
                    }
                ]
            }
        },
        tasks=[
            Task(id="task_001", name="任务A", phase_id="phase_1", milestone_id="m1")
        ],
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    monkeypatch.setattr(
        task_tools,
        "_plan_fit_result",
        lambda trigger: {
            "status": "major_drift",
            "next_tool": "collect_company_evidence",
            "recommended_action": "证据过期",
        },
    )

    output = task_tools.get_workflow_status()

    next_line = next(line for line in output.splitlines() if line.startswith("**下一步**"))
    assert "get_next_tasks" in next_line
    assert "collect_company_evidence" not in next_line


def test_workflow_status_all_finished_with_pending_phase_routes_generate_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """当前任务全部完成但路线图还有新阶段时，不能直接宣布「目标达成」。"""
    _isolate_profile(tmp_path, monkeypatch)
    profile = CareerProfile(
        who={"name": "张三"},
        summary="已确认",
        plan={
            "roadmap": {
                "phases": [
                    {
                        "id": "phase_1",
                        "name": "阶段一",
                        "milestones": [
                            {"id": "m1", "name": "M1", "tasks": [{"name": "任务A"}]}
                        ],
                    },
                    {
                        "id": "phase_2",
                        "name": "阶段二",
                        "milestones": [
                            {"id": "m2", "name": "M2", "tasks": [{"name": "任务B"}]}
                        ],
                    },
                ]
            }
        },
        tasks=[
            Task(
                id="task_001",
                name="任务A",
                phase_id="phase_1",
                milestone_id="m1",
                status="completed",
            )
        ],
    )
    profile_store.save_profile(profile, PROFILE_NAME)

    output = task_tools.get_workflow_status()

    next_line = next(line for line in output.splitlines() if line.startswith("**下一步**"))
    assert "generate_tasks" in next_line
    assert "目标达成" not in output
