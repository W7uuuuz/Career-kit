"""Phase 3a 工具门禁：显式 state→tool 期望表，不从 snapshot.allowed_tools 反推。

合法/非法 smoke 覆盖 14 个状态，关键修复路径另有独立期望表；避免门禁实现
与状态表同错时测试仍然变绿。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from src import paths  # noqa: E402
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.core.state import (  # noqa: E402
    State,
    StateSnapshot,
    resolve_state,
)
from src.guidance import build_guide  # noqa: E402
from src.models import CareerProfile, Task  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402
from src.tools.state_gate import require_state  # noqa: E402
from src.tools.task_tools import get_workflow_status  # noqa: E402

from test_state_matrix import (  # noqa: E402
    PROFILE_NAME,
    _confirmed_profile,
    _save_plan,
    _save_profile,
    _save_requirement,
    _save_target,
    _seed_to_evidence,
    _seed_to_requirement,
    build_case,
    seed_executed_chain,
)


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    return root


@pytest.fixture()
def store(data_dir: Path) -> ArtifactStore:
    return ArtifactStore()


def _market_pending(store: ArtifactStore) -> SimpleNamespace:
    profile_id = _save_profile(store)
    _save_target(store, profile_id)
    return _confirmed_profile()


def _requirement_ready(store: ArtifactStore) -> SimpleNamespace:
    evidence_id = _seed_to_evidence(store)
    _save_requirement(
        store,
        evidence_id,
        validation={"status": "saved"},
        interpretation={"summary": "RAG 是核心要求"},
    )
    return _confirmed_profile()


def _execution_plan_draft(store: ArtifactStore) -> SimpleNamespace:
    requirement_id, baseline_id = _seed_to_requirement(store)
    _save_plan(store, requirement_id, baseline_id, applied=False)
    return _confirmed_profile()


def _executing(store: ArtifactStore) -> SimpleNamespace:
    ids = seed_executed_chain(store)
    return _confirmed_profile(
        core_state=ids, tasks=[SimpleNamespace(status="pending")]
    )


def _maintenance(store: ArtifactStore) -> SimpleNamespace:
    ids = seed_executed_chain(store)
    return _confirmed_profile(
        core_state=ids, tasks=[SimpleNamespace(status="completed")]
    )


_CUSTOM_CASES: dict[State, Callable[[ArtifactStore], SimpleNamespace]] = {
    State.MARKET_PENDING: _market_pending,
    State.REQUIREMENT_READY: _requirement_ready,
    State.EXECUTION_PLAN_DRAFT: _execution_plan_draft,
    State.EXECUTING: _executing,
    State.MAINTENANCE: _maintenance,
}

# 持久化 fixture 覆盖其余状态。
_LABEL_BY_STATE: dict[State, str] = {
    State.EMPTY: "01",
    State.PROFILE_COLLECTING: "02",
    State.PROFILE_READY: "04",
    State.BASELINE_PLAN_PENDING: "05",
    State.GAP_PENDING: "06",
    State.COMPANY_PENDING: "07",
    State.EXECUTION_READY: "09",
    State.EVIDENCE_PENDING: "10",
    State.REQUIREMENT_DRAFT: "13",
}

# 显式 state→工具 smoke 期望：合法/非法都写死，不从 snapshot.allowed_tools 反推。
_GATE_SMOKE: dict[State, tuple[str, str]] = {
    State.EMPTY: ("intake", "finalize_profile"),
    State.PROFILE_COLLECTING: ("intake", "finalize_profile"),
    State.PROFILE_READY: ("finalize_profile", "save_roadmap"),
    State.MARKET_PENDING: ("analyze_gaps", "finalize_profile"),
    State.GAP_PENDING: ("analyze_gaps", "finalize_profile"),
    State.BASELINE_PLAN_PENDING: ("generate_roadmap", "finalize_profile"),
    State.COMPANY_PENDING: ("select_target_companies", "finalize_profile"),
    State.EVIDENCE_PENDING: ("collect_company_evidence", "finalize_profile"),
    State.REQUIREMENT_DRAFT: ("analyze_company_requirements", "plan_execution_alignment"),
    State.REQUIREMENT_READY: ("plan_execution_alignment", "save_requirement_profile"),
    State.EXECUTION_PLAN_DRAFT: ("save_execution_alignment", "plan_execution_alignment"),
    State.EXECUTION_READY: ("detail_current_phase", "finalize_profile"),
    State.EXECUTING: ("checkin_task", "finalize_profile"),
    State.MAINTENANCE: ("detail_current_phase", "finalize_profile"),
}


def _build_state(state: State, store: ArtifactStore) -> tuple[SimpleNamespace, StateSnapshot]:
    if state in _CUSTOM_CASES:
        profile = _CUSTOM_CASES[state](store)
    else:
        profile, _ = build_case(_LABEL_BY_STATE[state], store)
    return profile, resolve_state(profile, store)


def test_all_states_covered() -> None:
    states = set(_CUSTOM_CASES) | set(_LABEL_BY_STATE)
    assert states == set(State)
    assert set(_GATE_SMOKE) == set(State)


@pytest.mark.parametrize("state", list(State), ids=[state.value for state in State])
def test_legal_and_illegal_smoke_for_every_state(
    state: State, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    legal, illegal = _GATE_SMOKE[state]
    legal_result = require_state(profile, legal)
    assert isinstance(legal_result, StateSnapshot), legal_result

    payload = json.loads(require_state(profile, illegal))
    assert payload["isError"] is True
    assert payload["code"] == "INVALID_STATE"
    assert payload["details"]["state"] == state.value
    assert payload["details"]["tool"] == illegal
    assert payload["details"]["allowed_tools"] == sorted(snapshot.allowed_tools)
    assert payload["details"]["next_tool"] == snapshot.next_tool


def test_execution_plan_draft_guide_and_status_follow_allowed_tools(
    store: ArtifactStore,
) -> None:
    """EXECUTION_PLAN_DRAFT 的下一步只能是应用，GUIDE/status 与门禁一致。"""
    profile, snapshot = _build_state(State.EXECUTION_PLAN_DRAFT, store)
    assert snapshot.state is State.EXECUTION_PLAN_DRAFT
    assert snapshot.next_tool == "save_execution_alignment"
    assert "plan_execution_alignment" not in snapshot.allowed_tools

    guide = build_guide(profile)
    assert guide.status == "alignment"
    assert guide.next_action.startswith("save_execution_alignment")
    assert "plan_execution_alignment" not in guide.next_action

    _persist_fixture(profile, snapshot)
    status = get_workflow_status()
    assert "**下一步**：save_execution_alignment" in status
    assert "该阶段下一步：save_execution_alignment" in status
    assert "plan_execution_alignment" not in status


GATED_TOOLS: tuple[str, ...] = (
    "finalize_profile",
    "analyze_gaps",
    "save_gap_analysis",
    "generate_roadmap",
    "save_roadmap",
    "select_target_companies",
    "collect_company_evidence",
    "analyze_company_requirements",
    "save_requirement_profile",
    "plan_execution_alignment",
    "save_execution_alignment",
    "generate_tasks",
    "detail_current_phase",
    "save_current_detail",
    "checkin_task",
)

# 显式 state→工具期望表：每个状态的合法门禁工具全部写死。
# 不从 snapshot.allowed_tools 反推，避免门禁与状态实现同错时测试仍然变绿。
_EXPECTED_GATED: dict[State, frozenset[str]] = {
    State.EMPTY: frozenset(),
    State.PROFILE_COLLECTING: frozenset(),
    State.PROFILE_READY: frozenset({"finalize_profile"}),
    State.MARKET_PENDING: frozenset({"analyze_gaps", "save_gap_analysis"}),
    State.GAP_PENDING: frozenset(
        {"analyze_gaps", "save_gap_analysis", "generate_roadmap", "save_roadmap"}
    ),
    State.BASELINE_PLAN_PENDING: frozenset(
        {"save_gap_analysis", "generate_roadmap", "save_roadmap"}
    ),
    State.COMPANY_PENDING: frozenset(
        {
            "select_target_companies",
            "detail_current_phase",
            "generate_tasks",
            "save_roadmap",
        }
    ),
    State.EVIDENCE_PENDING: frozenset(
        {"collect_company_evidence", "select_target_companies"}
    ),
    State.REQUIREMENT_DRAFT: frozenset(
        {
            "analyze_company_requirements",
            "save_requirement_profile",
            "select_target_companies",
            "collect_company_evidence",
        }
    ),
    State.REQUIREMENT_READY: frozenset(
        {
            "plan_execution_alignment",
            "save_execution_alignment",
            "select_target_companies",
            "collect_company_evidence",
        }
    ),
    State.EXECUTION_PLAN_DRAFT: frozenset(
        {
            "save_execution_alignment",
            "select_target_companies",
            "collect_company_evidence",
        }
    ),
    State.EXECUTION_READY: frozenset(
        {
            "detail_current_phase",
            "save_current_detail",
            "generate_tasks",
            "select_target_companies",
            "collect_company_evidence",
            "analyze_company_requirements",
            "plan_execution_alignment",
            "save_execution_alignment",
        }
    ),
    State.EXECUTING: frozenset(
        {
            "checkin_task",
            "detail_current_phase",
            "save_current_detail",
            "generate_tasks",
            "select_target_companies",
            "collect_company_evidence",
            "analyze_company_requirements",
            "plan_execution_alignment",
            "save_execution_alignment",
        }
    ),
    State.MAINTENANCE: frozenset(
        {
            "generate_tasks",
            "detail_current_phase",
            "save_current_detail",
            "select_target_companies",
            "collect_company_evidence",
            "analyze_company_requirements",
            "plan_execution_alignment",
            "save_execution_alignment",
        }
    ),
}


def test_gated_expectations_cover_all_states() -> None:
    assert set(_EXPECTED_GATED) == set(State)
    assert set(GATED_TOOLS) >= {tool for tools in _EXPECTED_GATED.values() for tool in tools}


@pytest.mark.parametrize("state", list(State), ids=[state.value for state in State])
def test_gated_tool_decision_matches_explicit_table(
    state: State, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    expected = _EXPECTED_GATED[state]
    assert snapshot.allowed_tools & frozenset(GATED_TOOLS) == expected, state

    for tool in GATED_TOOLS:
        result = require_state(profile, tool)
        if tool in expected:
            assert isinstance(result, StateSnapshot), (tool, state)
            continue
        payload = json.loads(result)
        assert payload["isError"] is True, (tool, state)
        assert payload["code"] == "INVALID_STATE", (tool, state)
        assert payload["details"]["state"] == state.value
        assert payload["details"]["tool"] == tool
        assert payload["details"]["allowed_tools"] == sorted(snapshot.allowed_tools)
        assert payload["details"]["next_tool"] == snapshot.next_tool


# 本轮修复/补齐路径的显式 (state, tool, 是否允许) 期望；合法与非法都由测试写死。
_ROUND_GATES: tuple[tuple[State, str, bool], ...] = (
    # 本轮 1：EXECUTION_PLAN_DRAFT 只能应用，不能回到校准。
    (State.EXECUTION_PLAN_DRAFT, "save_execution_alignment", True),
    (State.EXECUTION_PLAN_DRAFT, "plan_execution_alignment", False),
    # 本轮 4：阶段 8/9 允许改名单与刷新证据。
    (State.REQUIREMENT_DRAFT, "select_target_companies", True),
    (State.REQUIREMENT_DRAFT, "collect_company_evidence", True),
    (State.REQUIREMENT_READY, "select_target_companies", True),
    (State.REQUIREMENT_READY, "collect_company_evidence", True),
    (State.EXECUTION_PLAN_DRAFT, "select_target_companies", True),
    (State.EXECUTION_PLAN_DRAFT, "collect_company_evidence", True),
    # 本轮 5：MAINTENANCE 仍可细化/保存当前阶段详细路线。
    (State.MAINTENANCE, "detail_current_phase", True),
    (State.MAINTENANCE, "save_current_detail", True),
    # 既有修复路径回归。
    (State.REQUIREMENT_READY, "save_execution_alignment", True),
    (State.EXECUTING, "select_target_companies", True),
    (State.EXECUTING, "collect_company_evidence", True),
    (State.COMPANY_PENDING, "generate_tasks", True),
    (State.COMPANY_PENDING, "detail_current_phase", True),
    (State.MARKET_PENDING, "save_gap_analysis", True),
    (State.MAINTENANCE, "plan_execution_alignment", True),
)


@pytest.mark.parametrize(
    ("state", "tool", "allowed"),
    _ROUND_GATES,
    ids=[f"{state.value}:{tool}:{'allow' if allowed else 'deny'}" for state, tool, allowed in _ROUND_GATES],
)
def test_repair_path_gate_expectations(
    state: State, tool: str, allowed: bool, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    result = require_state(profile, tool)

    if allowed:
        assert isinstance(result, StateSnapshot), result
        assert result.state is state
        return
    payload = json.loads(result)
    assert payload["isError"] is True
    assert payload["code"] == "INVALID_STATE"
    assert payload["details"]["state"] == state.value
    assert payload["details"]["tool"] == tool
    assert payload["details"]["next_tool"] == snapshot.next_tool


def _persist_fixture(profile: SimpleNamespace, snapshot: StateSnapshot) -> None:
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


def _call_generate_tasks() -> str:
    from src.server import generate_tasks

    return generate_tasks()


def _call_detail_current_phase() -> str:
    from src.server import detail_current_phase

    return detail_current_phase()


def _call_save_current_detail() -> str:
    from src.server import save_current_detail

    return save_current_detail("{}")


def _call_checkin_task() -> str:
    from src.server import checkin_task

    return checkin_task(task_id="task_001", status="completed")


def _call_save_gap_analysis() -> str:
    from src.server import save_gap_analysis

    return save_gap_analysis("{}")


def _call_generate_roadmap() -> str:
    from src.server import generate_roadmap

    return generate_roadmap()


def _call_analyze_company_requirements() -> str:
    from src.server import analyze_company_requirements

    return analyze_company_requirements()


def _call_plan_execution_alignment() -> str:
    from src.server import plan_execution_alignment

    return plan_execution_alignment()


def _call_save_roadmap() -> str:
    from src.server import save_roadmap

    return save_roadmap("{}")


def _call_save_execution_alignment() -> str:
    from src.server import save_execution_alignment

    return save_execution_alignment("{}")


def _call_save_requirement_profile() -> str:
    from src.server import save_requirement_profile

    return save_requirement_profile("{}")


def _call_collect_company_evidence() -> str:
    from src.server import collect_company_evidence

    return asyncio.run(collect_company_evidence())


def _call_select_target_companies() -> str:
    from src.server import select_target_companies

    return select_target_companies()


def _call_finalize_profile() -> str:
    from src.server import finalize_profile

    return finalize_profile()


_INTEGRATION: tuple[tuple[str, str, Callable[[], str]], ...] = (
    ("generate_tasks", "05", _call_generate_tasks),
    ("detail_current_phase", "05", _call_detail_current_phase),
    ("save_current_detail", "05", _call_save_current_detail),
    ("checkin_task", "05", _call_checkin_task),
    ("save_gap_analysis", "04", _call_save_gap_analysis),
    ("generate_roadmap", "04", _call_generate_roadmap),
    ("save_roadmap", "04", _call_save_roadmap),
    ("analyze_company_requirements", "05", _call_analyze_company_requirements),
    ("plan_execution_alignment", "05", _call_plan_execution_alignment),
    ("save_execution_alignment", "05", _call_save_execution_alignment),
    ("save_requirement_profile", "05", _call_save_requirement_profile),
    ("collect_company_evidence", "05", _call_collect_company_evidence),
    ("select_target_companies", "05", _call_select_target_companies),
    ("finalize_profile", "05", _call_finalize_profile),
)


@pytest.mark.parametrize(
    ("tool", "label", "call"), _INTEGRATION, ids=[entry[0] for entry in _INTEGRATION]
)
def test_tool_entrypoints_enforce_gate(
    tool: str,
    label: str,
    call: Callable[[], str],
    store: ArtifactStore,
) -> None:
    profile, snapshot = build_case(label, store)
    _persist_fixture(profile, snapshot)

    payload = json.loads(call())

    assert payload["isError"] is True
    assert payload["code"] == "INVALID_STATE"
    assert payload["details"]["state"] == snapshot.state.value
    assert payload["details"]["tool"] == tool
    assert payload["details"]["next_tool"] == snapshot.next_tool
