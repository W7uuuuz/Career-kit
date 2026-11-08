"""引导状态机回归：位置推导、目标确认、单一文案源。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.guidance import (  # noqa: E402
    build_guide,
    goal_confirmed,
    mark_brief_shown,
    mark_goal_confirmed,
    render_guide,
    user_brief,
    warnings,
)
from src.models import CareerProfile, Task  # noqa: E402


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    import src.tools.profile as profile_module

    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _confirmed_profile() -> CareerProfile:
    profile = CareerProfile()
    mark_brief_shown(profile)
    mark_goal_confirmed(profile)
    profile.who = {"name": "张三"}
    profile.have = {"skills": ["Python"]}
    profile.summary = "应届生"
    return profile


def test_empty_profile_starts_with_brief():
    guide = build_guide(CareerProfile())

    assert guide.status == "brief"
    assert guide.index == 1 and guide.brief_needed
    assert "了解多少" in guide.ask
    assert "首次进入" in render_guide(guide)  # 提示模型先发 [USER_BRIEF]


def test_after_brief_asks_familiarity_before_goal():
    profile = CareerProfile()
    mark_brief_shown(profile)

    guide = build_guide(profile)
    assert guide.status == "familiarity"
    assert "了解多少" in guide.ask

    profile.want = {"scan_completed_at": "2026-11-03T10:00:00"}
    assert build_guide(profile).status == "goal"


def test_mark_brief_then_goal_confirmation():
    profile = CareerProfile()
    mark_brief_shown(profile)
    profile.want = {"target_role": "AI Agent", "city": "上海"}

    guide = build_guide(profile)
    assert guide.status == "goal"
    assert "AI Agent" in guide.ask and "上海" in guide.ask
    assert not goal_confirmed(profile)

    mark_goal_confirmed(profile)
    assert goal_confirmed(profile)
    assert build_guide(profile).status == "profile"


def test_legacy_profile_skips_brief_and_goal():
    profile = CareerProfile()
    profile.gap = {"match_score": 60}

    guide = build_guide(profile)
    assert guide.status not in ("brief", "goal")


def test_guide_follows_twelve_core_stages():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}

    profile.core_state = {"stage": "profile"}
    assert build_guide(profile).status == "profile"

    profile.core_state["profile_id"] = "pf_1"
    assert build_guide(profile).status == "target"

    profile.core_state["target_spec_id"] = "ts_1"
    assert build_guide(profile).status == "market"

    profile.core_state["market_baseline_id"] = "mb_1"
    assert build_guide(profile).status == "gap"

    profile.core_state["gap_report_id"] = "gr_1"
    assert build_guide(profile).status == "plan"

    profile.core_state["baseline_plan_id"] = "bp_1"
    assert build_guide(profile).status == "company"

    profile.core_state["company_pool_id"] = "cp_1"
    assert build_guide(profile).status == "evidence"

    profile.core_state["evidence_run_id"] = "ev_1"
    assert build_guide(profile).status == "requirement"

    profile.core_state["requirement_profile_id"] = "rp_1"
    assert build_guide(profile).status == "alignment"

    profile.core_state["execution_plan_id"] = "ep_1"
    profile.core_state["stage"] = "executing"
    guide = build_guide(profile)
    assert guide.status == "execution"
    assert "细化" in guide.ask

    profile.core_state["execution_state_id"] = "es_1"
    profile.core_state["stage"] = "execution"
    guide = build_guide(profile)
    assert guide.status == "execution"
    assert "登记投递" in guide.options
    assert "做周检视/计划检查" in guide.options


def test_optional_application_and_review_do_not_block_execution():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.core_state = {
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
        "stage": "execution",
    }

    guide = build_guide(profile)
    assert guide.status == "execution"
    assert "application_state_id" not in guide.next_action
    assert "review_report_id" not in guide.next_action


def test_legacy_fields_do_not_force_redo():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.research = {"report_md": "report.md"}
    profile.gap = {"match_score": 65}
    profile.plan = {"roadmap": {"phases": []}}
    assert build_guide(profile).status == "company"

    profile.tasks = [Task(id="task_001", name="任务", phase_id="phase_1")]
    assert build_guide(profile).status == "execution"

    profile.tasks[0].status = "completed"
    assert build_guide(profile).status == "review"


def test_legacy_gap_without_research_counts_market_done():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.gap = {"match_score": 60}

    assert build_guide(profile).status == "plan"


def test_warnings_surface_failed_sources():
    profile = _confirmed_profile()
    profile.research = {
        "report_md": "report.md",
        "source_status": [{"source": "boss", "status": "failed"}],
    }

    notes = warnings(profile)
    assert any("boss" in note for note in notes)
    assert build_guide(profile).warnings


def test_user_brief_has_all_twelve_steps():
    brief = user_brief()

    assert "从起步到上岸全流程 12 步" in brief
    for name in (
        "职业档案构建",
        "目标岗位定位",
        "市场基线调研",
        "能力差距诊断",
        "培养方案规划",
        "目标企业筛选",
        "岗位与面经采集",
        "企业需求分析",
        "执行方案校准",
        "任务执行与打卡",
        "求职投递管理",
        "周期复盘与计划调整",
    ):
        assert name in brief
    assert "顺序定、节奏自己掌握" in brief


def test_login_action_points_to_harness():
    """BOSS 登录询问必须说明 Agent 会直接运行脚本，用户只需扫码。"""
    from src.guidance import login_action

    data = login_action("python -m src.scrapers.boss.login")

    assert data["harness_can_run"] is True
    assert "harness" in data["agent_action"]
    assert "不要把命令丢给用户" in data["agent_action"]
    assert "扫码" in data["user_instruction"]


def test_render_guide_has_one_question_and_no_internal_ids():
    guide = build_guide(CareerProfile())
    text = render_guide(guide)

    assert "位置：" in text and "本轮只问一个问题" in text
    assert "转述纪律" in text
    assert "JD01" in text  # 只作为禁用示例出现，不代表允许展示


def test_start_session_emits_brief_and_guide(temp_profile):
    """入口工具直接下发 [USER_BRIEF]/[GUIDE]，不要求模型自己拼开场白。"""
    from src.server import start_session

    out = start_session()

    assert "[USER_BRIEF]" in out and "[GUIDE]" in out
    assert "从起步到上岸全流程 12 步" in out


def test_workflow_status_includes_brief_for_new_profile(temp_profile):
    """模型若直接调 get_workflow_status，也必须拿到完整首屏，而不是悬空提示。"""
    from src.server import get_workflow_status

    out = get_workflow_status()

    assert "[USER_BRIEF]" in out and "从起步到上岸全流程 12 步" in out
    assert "[GUIDE]" in out


def test_intake_want_requires_user_confirmation(temp_profile):
    """简历推断的目标不能直接进入下一步：先停在目标确认状态。"""
    from src.server import intake, start_session

    start_session()
    before = intake("want", '{"target_role": "AI Agent", "city": "上海"}')
    assert "我先确认目标" in before

    after = intake(
        "want",
        '{"target_role": "AI Agent", "city": "上海", "user_confirmed": true}',
    )
    assert "有简历文件吗" in after


def test_analyze_blocks_unconfirmed_goal_in_guided_flow(temp_profile):
    """引导流程内，未确认目标时 analyze_gaps 必须拒绝，而不是替用户假设。"""
    import json

    from src.server import analyze_gaps, intake, start_session

    start_session()
    intake("want", '{"target_role": "AI Agent", "city": "上海"}')

    blocked = json.loads(analyze_gaps())
    assert blocked["code"] == "GOAL_CONFIRMATION_REQUIRED"
    assert "[GUIDE]" in blocked["message"]

    intake(
        "want",
        '{"target_role": "AI Agent", "city": "上海", "user_confirmed": true}',
    )
    assert "methodologies" in analyze_gaps()
