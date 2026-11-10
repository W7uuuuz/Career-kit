"""Phase 3a 工具门禁：期望全部来自 StateSnapshot.allowed_tools。

不维护第二套工具→状态映射；合法/非法 smoke 覆盖 13 个状态。
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
    READ_ONLY_TOOLS,
    State,
    StateSnapshot,
    resolve_state,
)
from src.models import CareerProfile, Task  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402
from src.tools.state_gate import require_state  # noqa: E402

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

_LEGAL_CANDIDATES = (
    "generate_tasks",
    "detail_current_phase",
    "save_current_detail",
    "checkin_task",
    "generate_roadmap",
    "save_roadmap",
    "save_execution_alignment",
    "save_requirement_profile",
    "collect_company_evidence",
    "select_target_companies",
    "finalize_profile",
    "intake",
    "analyze_gaps",
    "plan_execution_alignment",
    "build_application_list",
)


def _build_state(state: State, store: ArtifactStore) -> tuple[SimpleNamespace, StateSnapshot]:
    if state in _CUSTOM_CASES:
        profile = _CUSTOM_CASES[state](store)
    else:
        profile, _ = build_case(_LABEL_BY_STATE[state], store)
    return profile, resolve_state(profile, store)


def test_all_states_covered() -> None:
    states = set(_CUSTOM_CASES) | set(_LABEL_BY_STATE)
    assert states == set(State)


@pytest.mark.parametrize("state", list(State), ids=[state.value for state in State])
def test_legal_and_illegal_smoke_for_every_state(
    state: State, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    legal = sorted(snapshot.allowed_tools - READ_ONLY_TOOLS)
    assert legal, f"{state} 没有可门禁工具"
    legal_result = require_state(profile, legal[0])
    assert isinstance(legal_result, StateSnapshot), legal_result

    illegal = next(
        tool for tool in _LEGAL_CANDIDATES if tool not in snapshot.allowed_tools
    )
    payload = json.loads(require_state(profile, illegal))
    assert payload["isError"] is True
    assert payload["code"] == "INVALID_STATE"
    assert payload["details"]["state"] == state.value
    assert payload["details"]["tool"] == illegal
    assert payload["details"]["allowed_tools"] == sorted(snapshot.allowed_tools)
    assert payload["details"]["next_tool"] == snapshot.next_tool


GATED_TOOLS: tuple[str, ...] = (
    "finalize_profile",
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


@pytest.mark.parametrize("state", list(State), ids=[state.value for state in State])
def test_gated_tool_decision_follows_snapshot(
    state: State, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    for tool in GATED_TOOLS:
        result = require_state(profile, tool)
        if tool in snapshot.allowed_tools:
            assert isinstance(result, StateSnapshot), (tool, state)
            continue
        payload = json.loads(result)
        assert payload["isError"] is True, (tool, state)
        assert payload["code"] == "INVALID_STATE", (tool, state)
        assert payload["details"]["state"] == state.value
        assert payload["details"]["tool"] == tool
        assert payload["details"]["allowed_tools"] == sorted(snapshot.allowed_tools)
        assert payload["details"]["next_tool"] == snapshot.next_tool


# 修复/补齐路径的正向门禁：期望表显式写死 (state, tool)，不从 snapshot 反推。
_POSITIVE_GATES: tuple[tuple[State, str], ...] = (
    (State.REQUIREMENT_READY, "save_execution_alignment"),
    (State.EXECUTING, "select_target_companies"),
    (State.EXECUTING, "collect_company_evidence"),
    (State.COMPANY_PENDING, "generate_tasks"),
    (State.COMPANY_PENDING, "detail_current_phase"),
    (State.MARKET_PENDING, "save_gap_analysis"),
    (State.MARKET_PENDING, "save_roadmap"),
)


@pytest.mark.parametrize(
    ("state", "tool"),
    _POSITIVE_GATES,
    ids=[f"{state.value}:{tool}" for state, tool in _POSITIVE_GATES],
)
def test_repair_path_tools_are_allowed(
    state: State, tool: str, store: ArtifactStore
) -> None:
    profile, snapshot = _build_state(state, store)
    assert snapshot.state is state

    result = require_state(profile, tool)

    assert isinstance(result, StateSnapshot), result
    assert result.state is state


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
