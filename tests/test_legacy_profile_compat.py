"""旧档案兼容回归——无 core_state、旧 plan/tasks/research 在新代码下的行为。

覆盖点：
1. 旧 JSON 档案能加载，core_state 默认 {}，who/have/want/gap/plan/tasks 原样保留；
2. 旧 plan（{"roadmap": {...}}）下 get_workflow_status / get_progress / generate_tasks 不崩；
3. 应用执行版后 completed 保留、pending 删除、plan_history/adjustments 写入、进入 executing；
4. ArtifactStore 在只有 profiles 表的旧库上自动建 artifacts 表且不破坏 profiles；
5. 无 artifact 时 state_machine.next_action 给出 select_target_companies；
6. 旧档案调用 check_plan_fit 返回 incomplete_chain，不被跳过；
7. 旧 research 报告字段不影响新流程。

全部用例使用 tmp_path 隔离数据目录，不联网，不写真实 ~/.career-kit。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths  # noqa: E402
from src.core.artifacts.models import (  # noqa: E402
    ArtifactMeta,
    CompanyPool,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.core.orchestrator import state_machine  # noqa: E402
from src.core.stages import execution_plan as execution_stage  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402
from src.tools.task_tools import generate_tasks, get_progress, get_workflow_status  # noqa: E402

PROFILE_NAME = "default"


def _legacy_roadmap() -> dict[str, Any]:
    return {
        "roadmap": {
            "strategy_summary": "旧版基线策略",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "旧阶段一",
                    "goal": "补齐基础",
                    "milestones": [
                        {
                            "id": "phase_1_ms_1",
                            "name": "旧里程碑一",
                            "tasks": [{"name": "旧任务A", "priority": "high"}],
                        }
                    ],
                },
                {
                    "id": "phase_2",
                    "type": "project",
                    "name": "旧阶段二",
                    "goal": "做项目",
                    "milestones": [
                        {
                            "id": "phase_2_ms_1",
                            "name": "旧里程碑二",
                            "tasks": [{"name": "旧任务B", "priority": "medium"}],
                        }
                    ],
                },
            ],
        }
    }


def _legacy_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "task_001",
            "name": "旧已完成任务",
            "phase_id": "phase_1",
            "milestone_id": "phase_1_ms_1",
            "status": "completed",
            "completed_at": "2025-03-01T10:00:00",
            "how_to": ["读文档", "写练习"],
            "done_criteria": "能独立跑通",
        },
        {
            "id": "task_002",
            "name": "旧待办任务",
            "phase_id": "phase_1",
            "milestone_id": "phase_1_ms_1",
            "status": "pending",
        },
        {
            "id": "task_003",
            "name": "旧进行中任务",
            "phase_id": "phase_2",
            "milestone_id": "phase_2_ms_1",
            "status": "in_progress",
        },
    ]


def _legacy_document() -> dict[str, Any]:
    return {
        "who": {"name": "旧用户", "education": "双非本", "city": "北京"},
        "have": {"skills": ["Python", "LangChain"]},
        "want": {"target_role": "AI Agent 开发", "city": "北京", "target_tiers": ["大厂"]},
        # 旧档案迁移后目标由用户确认（Phase 4 legacy adapter 等价事实）；显式
        # legacy 标记是旧链路兜底的唯一依据，「有下游产物」不再算 legacy。
        "guidance": {
            "goal_confirmed_at": "2025-01-01T00:00:00",
            "legacy_migrated_at": "2025-01-01T00:00:00",
        },
        # anchor 回填需要的旧调研事实（报告存在即视为市场基线已落地）。
        "research": {"report_md": "C:/old/research.md", "counts": {}},
        "gap": {"match_score": 58, "start_level": "小厂"},
        "plan": _legacy_roadmap(),
        "tasks": _legacy_tasks(),
        "version": 4,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-03-05T12:00:00",
    }


def _write_legacy(
    data_dir: Path,
    name: str = PROFILE_NAME,
    document: dict[str, Any] | None = None,
) -> Path:
    path = data_dir / f"{name}.json"
    path.write_text(
        json.dumps(document if document is not None else _legacy_document(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _seed_requirement(profile_name: str = PROFILE_NAME, evidence_id: str = "JD001") -> str:
    store = ArtifactStore()
    meta = ArtifactMeta(
        id=store.new_id("rp"),
        stage=state_machine.STAGE_REQUIREMENT,
        profile_name=profile_name,
        created_at=datetime.now().isoformat(),
    )
    return store.save(
        RequirementProfile(
            meta=meta,
            evidence_run_id="",
            sample_size_jd=1,
            high_frequency=[
                RequirementItem(
                    term="RAG",
                    category="skill",
                    jd_count=1,
                    jd_frequency=1.0,
                    company_count=1,
                    company_frequency=1.0,
                    companies=["字节跳动"],
                    evidence_ids=[evidence_id],
                )
            ],
        )
    )


@pytest.fixture()
def compat_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "legacy-data"
    data_dir.mkdir()
    monkeypatch.setattr(profile_store, "PROFILE_DIR", data_dir)
    monkeypatch.setattr(paths, "PROFILE_DIR", data_dir)
    return data_dir


def test_legacy_judgment_ignores_downstream_for_new_flow() -> None:
    """「有下游产物」不等于旧档案：新流程必须仍要求目标确认与 finalize。"""
    from src.core.progress import is_legacy_profile

    new_flow = CareerProfile(
        who={"name": "新用户"},
        want={"target_role": "AI Agent 开发"},
        guidance={"brief_shown_at": "2026-11-09T00:00:00"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan=_legacy_roadmap(),
        tasks=_legacy_tasks(),
        applications=[],
    )
    assert is_legacy_profile(new_flow) is False

    legacy = CareerProfile(
        who={"name": "旧用户"},
        want={"target_role": "AI Agent 开发"},
        research={"jd_samples": [{"title": "AI Agent"}]},
        gap={"match_score": 58},
        plan=_legacy_roadmap(),
        tasks=_legacy_tasks(),
    )
    assert is_legacy_profile(legacy) is True


def test_legacy_json_profile_loads_without_core_state(compat_env: Path) -> None:
    document = _legacy_document()
    _write_legacy(compat_env, document=document)

    profile = profile_store.load_profile(PROFILE_NAME)

    assert isinstance(profile, CareerProfile)
    assert profile.core_state == {}
    assert profile.who == document["who"]
    assert profile.have == document["have"]
    assert profile.want == document["want"]
    assert profile.gap == document["gap"]
    assert profile.plan == document["plan"]
    assert [(task.id, task.name, task.status) for task in profile.tasks] == [
        ("task_001", "旧已完成任务", "completed"),
        ("task_002", "旧待办任务", "pending"),
        ("task_003", "旧进行中任务", "in_progress"),
    ]
    assert profile.tasks[0].completed_at == "2025-03-01T10:00:00"
    assert profile.tasks[0].how_to == ["读文档", "写练习"]
    assert profile.version == document["version"]
    assert profile.created_at == document["created_at"]
    assert profile.updated_at == document["updated_at"]


def test_legacy_plan_supports_workflow_progress_and_generate_tasks(compat_env: Path) -> None:
    _write_legacy(compat_env)

    status = get_workflow_status()
    assert isinstance(status, str)
    assert "企业适配（Core v2）" in status
    assert "select_target_companies" in status

    progress = get_progress()
    assert isinstance(progress, str)
    assert "阶段进度" in progress

    generated = generate_tasks()
    assert isinstance(generated, str)
    assert "已为当前阶段" in generated

    reloaded = profile_store.load_profile(PROFILE_NAME)
    assert reloaded.plan["roadmap"]["phases"][0]["name"] == "旧阶段一"
    assert reloaded.tasks
    assert any(task.phase_id == "phase_1" for task in reloaded.tasks)
    # 全 12 阶段迁移后，旧档案会在 get_workflow_status / generate_tasks 时补齐 core_state。
    assert reloaded.core_state["profile_id"]
    # 没有 applied ExecutionPlan 时不写半成品 ExecutionState（I5）。
    assert "execution_state_id" not in reloaded.core_state


def test_applying_execution_plan_preserves_legacy_progress(compat_env: Path) -> None:
    _write_legacy(compat_env)
    requirement_id = _seed_requirement()

    alignment = {
        "requirement_profile_id": requirement_id,
        "strategy_summary": "按企业需求重排",
        "roadmap": {
            "strategy_summary": "按企业需求重排",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "project",
                    "name": "RAG 项目",
                    "goal": "补齐 RAG 证据",
                    "kpi": {"metric": "RAG 项目", "target": "可演示", "evidence": "GitHub"},
                    "milestones": [
                        {
                            "id": "phase_1_ms_1",
                            "name": "RAG MVP",
                            "done_criteria": "能回答真实问题",
                            "tasks": [{"name": "实现 RAG 检索", "priority": "high"}],
                        }
                    ],
                },
                {
                    "id": "phase_2",
                    "type": "intern",
                    "name": "投递实习",
                    "goal": "拿到面试机会",
                    "milestones": [
                        {
                            "id": "phase_2_ms_1",
                            "name": "投递",
                            "tasks": [{"name": "投递目标公司", "priority": "medium"}],
                        }
                    ],
                },
            ],
        },
        "changes": [
            {
                "type": "add_task",
                "phase_id": "phase_1",
                "details": {"name": "实现 RAG 检索"},
                "reason": "JD 高频要求 RAG",
                "evidence_ids": ["JD001"],
            }
        ],
        "diff_summary": "保留已完成历史，移除旧 pending/in_progress 任务",
    }

    result = execution_stage.save_execution_alignment(
        json.dumps(alignment, ensure_ascii=False), confirmed=True
    )

    assert result["applied"] is True
    assert result["preserved_task_count"] == 1
    assert result["removed_task_count"] == 2

    profile = profile_store.load_profile(PROFILE_NAME)
    assert [task.id for task in profile.tasks] == ["task_001"]
    assert profile.tasks[0].status == "completed"
    assert profile.tasks[0].completed_at == "2025-03-01T10:00:00"
    assert profile.tasks[0].how_to == ["读文档", "写练习"]
    assert profile.plan["roadmap"]["strategy_summary"] == "按企业需求重排"
    assert [phase["name"] for phase in profile.plan["roadmap"]["phases"]] == [
        "RAG 项目",
        "投递实习",
    ]
    assert len(profile.plan_history) == 1
    assert profile.plan_history[0].source == "company_alignment"
    assert profile.adjustments[-1].trigger == "company_alignment"
    assert profile.adjustments[-1].trigger_type == "event"
    assert profile.core_state["stage"] == "executing"
    assert profile.core_state["requirement_profile_id"] == requirement_id
    assert profile.core_state["execution_plan_id"] == result["execution_plan_id"]


def test_artifact_store_creates_tables_on_legacy_profiles_db(compat_env: Path) -> None:
    db_path = compat_env / "career-kit.db"
    legacy_data = json.dumps({"who": {"name": "数据库旧档案"}}, ensure_ascii=False)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE profiles ("
            "name TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO profiles(name, data, updated_at) VALUES (?, ?, ?)",
            (PROFILE_NAME, legacy_data, "2025-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    store = ArtifactStore(db_path=db_path)
    meta = ArtifactMeta(
        id=store.new_id("cp"),
        stage=state_machine.STAGE_COMPANY_POOL,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
    )
    artifact_id = store.save(
        CompanyPool(
            meta=meta,
            target_spec=TargetSpec(role="AI Agent 开发"),
            companies=[],
        )
    )

    assert store.load(artifact_id) is not None

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "profiles" in tables, "旧库 profiles 表被破坏"
        assert "artifacts" in tables, "首次使用未自动创建 artifacts 表"

        profile_row = conn.execute(
            "SELECT data FROM profiles WHERE name = ?", (PROFILE_NAME,)
        ).fetchone()
        assert profile_row is not None, "旧库 profiles 数据丢失"
        assert json.loads(profile_row[0]) == {"who": {"name": "数据库旧档案"}}

        artifact_count = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()[0]
        assert artifact_count == 1
    finally:
        conn.close()

    legacy_loaded = profile_store.load_profile(PROFILE_NAME)
    assert legacy_loaded.who["name"] == "数据库旧档案"
    assert legacy_loaded.core_state == {}


def test_state_machine_handles_legacy_profile_without_artifacts(compat_env: Path) -> None:
    _write_legacy(compat_env)

    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert action["next_tool"] == "select_target_companies"
    assert "CompanyPool" in action["reason"]
    assert all(value == "" for value in action["artifact_ids"].values())


def test_check_plan_fit_reports_reasonable_status_for_legacy_profile(compat_env: Path) -> None:
    from src.core import plan_fit

    _write_legacy(compat_env)

    result = plan_fit.check_plan_fit(PROFILE_NAME)

    assert isinstance(result, dict)
    assert result["status"] == "incomplete_chain", (
        f"旧档案应判为 incomplete_chain，实际为 {result['status']!r}"
    )
    assert result["signals"], "incomplete_chain 应带至少一条信号"
    assert result["artifact_ids"] == {
        "company_pool_id": "",
        "evidence_run_id": "",
        "requirement_profile_id": "",
        "execution_plan_id": "",
    }


def test_legacy_research_report_does_not_break_core_flow(compat_env: Path) -> None:
    document = _legacy_document()
    document["research"] = {
        "report_md": "C:/old/research.md",
        "report_html": "C:/old/research.html",
        "generated_at": "2025-02-01T00:00:00",
        "counts": {"jd_samples": 12, "cases": 3},
        "index": "C:/old/index.html",
    }
    _write_legacy(compat_env, document=document)

    profile = profile_store.load_profile(PROFILE_NAME)
    assert profile.research["report_md"] == "C:/old/research.md"
    assert profile.research["counts"]["jd_samples"] == 12

    status = get_workflow_status()
    assert isinstance(status, str)
    assert "市场调研（来源真实）" in status
    assert "岗位样本 12 条" in status

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert action["next_tool"] == "select_target_companies"
