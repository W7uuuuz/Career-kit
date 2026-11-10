"""入口一致性：GUIDE 只消费 resolve_state 的 StateSnapshot。

期望值全部写死在下面的表里，不从 snapshot/guide 反推；13 个持久化 fixture
覆盖 docs/internal/state-model.md 的状态表。
"""

from __future__ import annotations

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

from test_state_matrix import build_case, persisted_case_labels  # noqa: E402


class ExpectedEntry(NamedTuple):
    label: str
    fixture: str
    state: State
    stage_index: int
    guide_status: str
    next_tool: str


EXPECTED: tuple[ExpectedEntry, ...] = (
    ExpectedEntry(
        "01", "空档案", State.EMPTY, 1, "brief", "parse_resume"
    ),
    ExpectedEntry(
        "02",
        "who/have 有、目标无",
        State.PROFILE_COLLECTING,
        2,
        "goal",
        "explore_goals",
    ),
    ExpectedEntry(
        "03",
        "目标未确认",
        State.PROFILE_COLLECTING,
        2,
        "goal",
        "intake(want)",
    ),
    ExpectedEntry(
        "04",
        "目标已确认未 finalize",
        State.PROFILE_READY,
        1,
        "profile",
        "finalize_profile",
    ),
    ExpectedEntry(
        "05",
        "gap 已生成、无 BaselinePlan",
        State.BASELINE_PLAN_PENDING,
        5,
        "plan",
        "generate_roadmap",
    ),
    ExpectedEntry(
        "06", "gap_stale", State.GAP_PENDING, 4, "gap", "analyze_gaps"
    ),
    ExpectedEntry(
        "07",
        "legacy 有 research/gap/plan/tasks",
        State.COMPANY_PENDING,
        6,
        "company",
        "select_target_companies",
    ),
    ExpectedEntry(
        "08",
        "第二次应用 ExecutionPlan",
        State.EXECUTION_READY,
        10,
        "execution",
        "detail_current_phase",
    ),
    ExpectedEntry(
        "09",
        "企业适配跳过",
        State.EXECUTION_READY,
        10,
        "execution",
        "detail_current_phase",
    ),
    ExpectedEntry(
        "10",
        "企业链路补齐后恢复",
        State.EVIDENCE_PENDING,
        7,
        "evidence",
        "collect_company_evidence",
    ),
    ExpectedEntry(
        "11",
        "BOSS list-only 大量行",
        State.REQUIREMENT_DRAFT,
        8,
        "requirement",
        "analyze_company_requirements",
    ),
    ExpectedEntry(
        "13",
        "RequirementProfile draft",
        State.REQUIREMENT_DRAFT,
        8,
        "requirement",
        "save_requirement_profile",
    ),
    ExpectedEntry(
        "14",
        "ExecutionState 旧代际",
        State.EXECUTION_READY,
        10,
        "execution",
        "detail_current_phase",
    ),
)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    return root


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
    assert guide.status == expected.guide_status
    assert guide.index == expected.stage_index
    assert snapshot.next_tool == expected.next_tool
    assert expected.next_tool in guide.next_action
