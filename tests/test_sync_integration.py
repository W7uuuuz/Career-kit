"""工具 → sync 层接入回归：关键操作成功写入 artifact 与 core_state。

全部用例使用 tmp_path 隔离档案与 artifact 数据库，不联网、不读写真实
~/.career-kit；资产目录由 tests/conftest.py 的 autouse fixture 重定向。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths  # noqa: E402
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.models import Application, CareerProfile, Task  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402

PROFILE_NAME = "default"


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    return root


def _load_artifact(artifact_id: str) -> dict:
    data = ArtifactStore().load(artifact_id)
    assert data is not None, f"artifact 不存在：{artifact_id}"
    return data


def _seed_legacy_profile() -> CareerProfile:
    roadmap = {
        "roadmap": {
            "strategy_summary": "旧基线策略",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "基础补齐",
                    "milestones": [
                        {
                            "id": "phase_1_ms_1",
                            "name": "基础",
                            "tasks": [{"name": "学 Python"}],
                        }
                    ],
                }
            ],
        }
    }
    profile = CareerProfile(
        who={"name": "旧用户", "education": "双非本", "city": "北京"},
        have={"skills": ["Python"]},
        want={"target_role": "AI Agent 开发", "city": "北京"},
        research={
            "report_md": "C:/old/research.md",
            "jd_samples": [{"title": "AI Agent", "company": "字节跳动", "url": "u1"}],
            "cases": [{"title": "双非进大厂", "source": "nowcoder", "url": "u2"}],
            "counts": {"jd_samples": 1, "cases": 1},
        },
        gap={"match_score": 58, "start_level": "小厂"},
        plan=roadmap,
        tasks=[
            Task(id="task_001", name="学 Python", phase_id="phase_1"),
        ],
        version=3,
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    return profile


def test_finalize_profile_syncs_profile_artifact(data_dir: Path) -> None:
    from src.tools.session_tools import finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": []}')
    intake("want", '{"target_role": "AI 工程师"}')
    out = finalize_profile()
    assert "档案已确认" in out

    profile = profile_store.load_profile(PROFILE_NAME)
    profile_id = profile.core_state.get("profile_id")
    assert profile_id and profile_id.startswith("pf_")
    assert _load_artifact(profile_id)["meta"]["stage"] == "profile"


def test_save_gap_analysis_syncs_gap_artifact(data_dir: Path) -> None:
    from src.tools.analysis_tools import save_gap_analysis

    gap = {"match_score": 60, "skill_gaps": [{"skill": "RAG", "source": "JD"}]}
    out = save_gap_analysis(gap_json=json.dumps(gap, ensure_ascii=False))
    assert json.loads(out).get("isError") is not True

    profile = profile_store.load_profile(PROFILE_NAME)
    gap_id = profile.core_state.get("gap_report_id")
    assert gap_id and gap_id.startswith("gr_")
    assert _load_artifact(gap_id)["match_score"] == 60


def test_save_roadmap_syncs_baseline_plan_artifact(data_dir: Path) -> None:
    from src.tools.roadmap_tools import save_roadmap

    roadmap = {
        "roadmap": {
            "strategy_summary": "基线策略",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "基础学习",
                    "kpi": {"metric": "掌握", "target": "1 项"},
                    "milestones": [
                        {"id": "m1", "name": "基础", "tasks": [{"name": "学 Python"}]}
                    ],
                }
            ],
        }
    }
    out = save_roadmap(roadmap_json=json.dumps(roadmap, ensure_ascii=False))
    assert "路线图已保存" in out

    profile = profile_store.load_profile(PROFILE_NAME)
    plan_id = profile.core_state.get("baseline_plan_id")
    assert plan_id and plan_id.startswith("bp_")
    artifact = _load_artifact(plan_id)
    assert artifact["strategy_summary"] == "基线策略"
    assert artifact["roadmap"]["phases"][0]["name"] == "基础学习"


def test_generate_tasks_and_checkin_sync_execution_state(data_dir: Path) -> None:
    from src.tools.task_tools import checkin_task, generate_tasks

    profile = profile_store.load_profile(PROFILE_NAME)
    profile.plan = {
        "roadmap": {
            "phases": [
                {
                    "id": "phase_1",
                    "name": "基础",
                    "milestones": [
                        {"id": "m1", "name": "M1", "tasks": [{"name": "任务A"}]}
                    ],
                }
            ]
        }
    }
    profile_store.save_profile(profile, PROFILE_NAME)

    out = generate_tasks()
    assert "已为当前阶段" in out

    profile = profile_store.load_profile(PROFILE_NAME)
    execution_id = profile.core_state.get("execution_state_id")
    assert execution_id and execution_id.startswith("es_")
    assert profile.tasks, "应已生成任务"

    task_id = profile.tasks[0].id
    checkin_task(task_id=task_id, status="completed")
    profile = profile_store.load_profile(PROFILE_NAME)
    assert profile.core_state.get("execution_state_id")
    artifact = _load_artifact(profile.core_state["execution_state_id"])
    assert artifact["task_counts"]["completed"] >= 1


def test_record_application_syncs_application_state_artifact(data_dir: Path) -> None:
    from src.tools.application_tools import record_application

    out = record_application(company="字节跳动", role="AI Agent 开发")
    assert "已记录投递" in out

    profile = profile_store.load_profile(PROFILE_NAME)
    app_id = profile.core_state.get("application_state_id")
    assert app_id and app_id.startswith("as_")
    artifact = _load_artifact(app_id)
    assert len(artifact["applications"]) == 1
    assert artifact["applications"][0]["company"] == "字节跳动"


def test_get_weekly_review_syncs_review_artifact(data_dir: Path) -> None:
    from src.tools.task_tools import get_weekly_review

    profile = profile_store.load_profile(PROFILE_NAME)
    profile.applications = [Application(id="app_001", company="字节跳动", role="Agent")]
    profile_store.save_profile(profile, PROFILE_NAME)

    out = get_weekly_review()
    assert isinstance(out, str) and out

    profile = profile_store.load_profile(PROFILE_NAME)
    review_id = profile.core_state.get("review_report_id")
    assert review_id and review_id.startswith("rr_")
    artifact = _load_artifact(review_id)
    assert artifact["weekly_facts"]
    assert isinstance(artifact["recommendations"], list)


def test_workflow_status_backfills_legacy_and_returns_12_stage(data_dir: Path) -> None:
    from src.tools.task_tools import get_workflow_status

    _seed_legacy_profile()

    out = get_workflow_status()
    assert isinstance(out, str)

    profile = profile_store.load_profile(PROFILE_NAME)
    state = profile.core_state
    assert state.get("profile_id", "").startswith("pf_")
    assert state.get("target_spec_id", "").startswith("ts_")
    assert state.get("market_baseline_id", "").startswith("mb_")
    assert state.get("gap_report_id", "").startswith("gr_")
    assert state.get("baseline_plan_id", "").startswith("bp_")
    assert state.get("execution_state_id", "").startswith("es_")

    # 12 阶段位置：企业基线链路已补齐，当前停在阶段 6（目标企业筛选）
    assert "12 步" in out
    assert "6/12" in out
    assert "目标企业筛选" in out
    # 保留旧的企业适配区块与旧流程提示
    assert "企业适配（Core v2）" in out
    assert "select_target_companies" in out


def test_workflow_status_keeps_existing_core_keys(data_dir: Path) -> None:
    from src.tools.task_tools import get_workflow_status

    profile = _seed_legacy_profile()
    profile.core_state = {"target_spec_id": "ts_keep", "custom_key": "keep"}
    profile_store.save_profile(profile, PROFILE_NAME)

    get_workflow_status()

    profile = profile_store.load_profile(PROFILE_NAME)
    assert profile.core_state.get("target_spec_id") == "ts_keep", "已有 key 不应重建"
    assert profile.core_state.get("custom_key") == "keep"
    assert profile.core_state.get("profile_id", "").startswith("pf_")
