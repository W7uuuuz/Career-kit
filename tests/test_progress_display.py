"""进度展示回归：阶段优先，新增任务不让主进度倒退。"""

from __future__ import annotations

from src.models import CareerProfile, Task
from src.tools.task_manager import format_progress_overview


def _profile() -> CareerProfile:
    profile = CareerProfile()
    profile.plan = {
        "roadmap": {
            "phases": [
                {"id": "phase_1", "name": "Agent 基础"},
                {"id": "phase_2", "name": "RAG 项目"},
            ]
        }
    }
    profile.tasks = [
        Task(id="task_001", name="学 LangGraph", phase_id="phase_1", status="completed"),
        Task(id="task_002", name="做 Agent demo", phase_id="phase_1", status="completed"),
        Task(id="task_003", name="搭检索服务", phase_id="phase_2", status="pending"),
    ]
    return profile


def test_progress_is_stage_first():
    text = format_progress_overview(_profile())
    assert "阶段进度：1/2（50%）" in text
    assert "当前阶段：RAG 项目（0/1）" in text
    assert "任务总计：已完成 2 / 3" in text


def test_adding_task_does_not_drop_stage_progress():
    profile = _profile()
    before = format_progress_overview(profile)
    profile.tasks.append(Task(id="task_004", name="补评测集", phase_id="phase_2"))
    after = format_progress_overview(profile)

    assert "阶段进度：1/2（50%）" in before
    assert "阶段进度：1/2（50%）" in after
    assert "任务总计：已完成 2 / 4" in after
