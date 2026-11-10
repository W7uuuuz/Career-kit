"""入口一致性：GUIDE 只消费 resolve_state 的 StateSnapshot。

期望值全部写死在下面的表里，不从 snapshot/guide 反推；13 个持久化 fixture
覆盖 docs/internal/state-model.md 的状态表。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from src import paths  # noqa: E402
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.core.state import State  # noqa: E402
from src.guidance import build_guide  # noqa: E402
from src.models import CareerProfile, Task  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402
from src.tools.roadmap_tools import save_roadmap  # noqa: E402
from src.tools.task_tools import get_workflow_status  # noqa: E402

from test_state_matrix import (  # noqa: E402
    PROFILE_NAME,
    build_case,
    persisted_case_labels,
)


class ExpectedEntry(NamedTuple):
    label: str
    fixture: str
    state: State
    stage_index: int
    stage_name: str
    guide_status: str
    next_tool: str


EXPECTED: tuple[ExpectedEntry, ...] = (
    ExpectedEntry(
        "01", "空档案", State.EMPTY, 1, "职业档案构建", "brief", "parse_resume"
    ),
    ExpectedEntry(
        "02",
        "who/have 有、目标无",
        State.PROFILE_COLLECTING,
        2,
        "目标岗位定位",
        "goal",
        "explore_goals",
    ),
    ExpectedEntry(
        "03",
        "目标未确认",
        State.PROFILE_COLLECTING,
        2,
        "目标岗位定位",
        "goal",
        "intake(want)",
    ),
    ExpectedEntry(
        "04",
        "目标已确认未 finalize",
        State.PROFILE_READY,
        1,
        "职业档案构建",
        "profile",
        "finalize_profile",
    ),
    ExpectedEntry(
        "05",
        "gap 已生成、无 BaselinePlan",
        State.BASELINE_PLAN_PENDING,
        5,
        "培养方案规划",
        "plan",
        "generate_roadmap",
    ),
    ExpectedEntry(
        "06",
        "gap_stale",
        State.GAP_PENDING,
        4,
        "能力差距诊断",
        "gap",
        "analyze_gaps",
    ),
    ExpectedEntry(
        "07",
        "legacy 有 research/gap/plan/tasks",
        State.COMPANY_PENDING,
        6,
        "目标企业筛选",
        "company",
        "select_target_companies",
    ),
    ExpectedEntry(
        "08",
        "第二次应用 ExecutionPlan",
        State.EXECUTION_READY,
        10,
        "任务执行与打卡",
        "execution",
        "detail_current_phase",
    ),
    ExpectedEntry(
        "09",
        "企业适配跳过",
        State.EXECUTION_READY,
        10,
        "任务执行与打卡",
        "execution",
        "detail_current_phase",
    ),
    ExpectedEntry(
        "10",
        "企业链路补齐后恢复",
        State.EVIDENCE_PENDING,
        7,
        "岗位与面经采集",
        "evidence",
        "collect_company_evidence",
    ),
    ExpectedEntry(
        "11",
        "BOSS list-only 大量行",
        State.REQUIREMENT_DRAFT,
        8,
        "企业需求分析",
        "requirement",
        "analyze_company_requirements",
    ),
    ExpectedEntry(
        "13",
        "RequirementProfile draft",
        State.REQUIREMENT_DRAFT,
        8,
        "企业需求分析",
        "requirement",
        "save_requirement_profile",
    ),
    ExpectedEntry(
        "14",
        "ExecutionState 旧代际",
        State.EXECUTION_READY,
        10,
        "任务执行与打卡",
        "execution",
        "detail_current_phase",
    ),
    ExpectedEntry(
        "15",
        "market skipped（无 MarketBaseline）",
        State.GAP_PENDING,
        4,
        "能力差距诊断",
        "gap",
        "analyze_gaps",
    ),
)

# save_roadmap 适用 fixture 的显式后置期望（不从 snapshot 反推）。
ROADMAP_EXPECTED: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "05",
        ("select_target_companies", "detail_current_phase"),
        ("select_target_companies", "detail_current_phase", "generate_tasks", "按基线", "跳过"),
    ),
    (
        "06",
        ("analyze_gaps",),
        ("analyze_gaps",),
    ),
    (
        "07",
        ("select_target_companies", "detail_current_phase"),
        ("select_target_companies", "按基线"),
    ),
    (
        "09",
        ("detail_current_phase",),
        ("detail_current_phase",),
    ),
)

_ROADMAP_PAYLOAD = {
    "roadmap": {
        "strategy_summary": "入口一致性路线图",
        "start_level": "小厂",
        "phases": [
            {
                "id": "phase_1",
                "type": "project",
                "name": "入口阶段",
                "resume_value": "可演示项目",
                "kpi": {"metric": "完成", "target": "1个"},
            }
        ],
    }
}


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    return root


def _persist_fixture(profile, snapshot) -> None:
    """把内存 fixture 落成真实档案 + core_state，供工具入口读取。"""
    data = vars(profile).copy()
    data.pop("name", None)
    data["core_state"] = {
        key: value for key, value in snapshot.artifact_ids.items() if value
    }
    data["tasks"] = [
        Task(
            id=f"task_{index + 1:03d}",
            name=f"任务 {index + 1}",
            phase_id="phase_1",
            status=str(getattr(task, "status", "pending") or "pending"),
        )
        for index, task in enumerate(profile.tasks)
    ]
    data["applications"] = []
    profile_store.save_profile(CareerProfile.model_validate(data), PROFILE_NAME)
    profile_store.set_active_profile_name(PROFILE_NAME)


@pytest.fixture()
def store(data_dir: Path) -> ArtifactStore:
    return ArtifactStore()


def test_entrypoint_covers_all_persisted_cases() -> None:
    assert tuple(entry.label for entry in EXPECTED) == persisted_case_labels()


@pytest.mark.parametrize("expected", EXPECTED, ids=[e.label for e in EXPECTED])
def test_guide_status_and_position_follow_snapshot(
    expected: ExpectedEntry, store: ArtifactStore
) -> None:
    profile, snapshot = build_case(expected.label, store)
    guide = build_guide(profile)

    assert snapshot.state == expected.state
    assert snapshot.stage_index == expected.stage_index
    assert snapshot.stage_name == expected.stage_name
    assert guide.status == expected.guide_status
    assert guide.index == expected.stage_index
    assert snapshot.next_tool == expected.next_tool
    assert expected.next_tool in guide.next_action


@pytest.mark.parametrize("expected", EXPECTED, ids=[e.label for e in EXPECTED])
def test_workflow_status_follows_snapshot(
    expected: ExpectedEntry, store: ArtifactStore
) -> None:
    profile, snapshot = build_case(expected.label, store)
    _persist_fixture(profile, snapshot)

    status = get_workflow_status()
    next_line = next(
        line for line in status.splitlines() if line.startswith("**下一步**")
    )

    assert next_line.startswith(f"**下一步**：{expected.next_tool}")
    assert (
        f"## 当前阶段（12 步）：{expected.stage_index}/12 {expected.stage_name}"
        in status
    )
    assert f"- 该阶段下一步：{expected.next_tool}" in status


@pytest.mark.parametrize(
    ("label", "expected_steps", "message_tokens"),
    ROADMAP_EXPECTED,
    ids=[entry[0] for entry in ROADMAP_EXPECTED],
)
def test_save_roadmap_follows_snapshot(
    label: str,
    expected_steps: tuple[str, ...],
    message_tokens: tuple[str, ...],
    store: ArtifactStore,
) -> None:
    profile, snapshot = build_case(label, store)
    _persist_fixture(profile, snapshot)

    result = json.loads(
        save_roadmap(json.dumps(_ROADMAP_PAYLOAD, ensure_ascii=False))
    )

    assert tuple(result["next_steps"]) == expected_steps
    for token in message_tokens:
        assert token in result["message"]
