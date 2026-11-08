"""引导状态机回归：位置推导、目标确认、单一文案源、与状态机一致。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src import paths  # noqa: E402
from src.core.artifacts.models import (  # noqa: E402
    ApplicationState,
    ArtifactMeta,
    BaselinePlan,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    ExecutionPlan,
    ExecutionState,
    GapReport,
    MarketBaseline,
    ProfileSnapshot,
    RequirementProfile,
    ReviewReport,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.core.orchestrator import state_machine  # noqa: E402
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
from src.tools import profile as profile_module  # noqa: E402

PROFILE_NAME = "default"


class _ProfileArtifact(ProfileSnapshot):
    meta: ArtifactMeta


class _TargetArtifact(TargetSpec):
    meta: ArtifactMeta


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_module, "PROFILE_DIR", root)
    return root


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
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


def _meta(store: ArtifactStore, stage: str, prefix: str) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
    )


def _save_profile_artifact(store: ArtifactStore) -> str:
    return store.save(
        _ProfileArtifact(
            meta=_meta(store, state_machine.STAGE_PROFILE, "pf"),
            name="张三",
            who={"name": "张三"},
            summary="应届生",
        )
    )


def _save_target(store: ArtifactStore) -> str:
    return store.save(
        _TargetArtifact(
            meta=_meta(store, state_machine.STAGE_TARGET, "ts"),
            role="AI Agent 开发",
            city="上海",
        )
    )


def _save_market(store: ArtifactStore) -> str:
    return store.save(
        MarketBaseline(
            meta=_meta(store, state_machine.STAGE_MARKET, "mb"),
            target_spec=TargetSpec(role="AI Agent 开发"),
        )
    )


def _save_gap(store: ArtifactStore) -> str:
    return store.save(
        GapReport(meta=_meta(store, state_machine.STAGE_GAP, "gr"), match_score=60)
    )


def _save_baseline(store: ArtifactStore) -> str:
    return store.save(
        BaselinePlan(
            meta=_meta(store, state_machine.STAGE_BASELINE_PLAN, "bp"),
            roadmap={"phases": []},
        )
    )


def _save_pool(store: ArtifactStore) -> str:
    return store.save(
        CompanyPool(
            meta=_meta(store, state_machine.STAGE_COMPANY_POOL, "cp"),
            target_spec=TargetSpec(role="AI Agent 开发"),
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


def _save_evidence(store: ArtifactStore, pool_id: str) -> str:
    return store.save(
        EvidenceRun(
            meta=_meta(store, state_machine.STAGE_EVIDENCE, "ev"),
            target_spec=TargetSpec(role="AI Agent 开发"),
            company_pool_id=pool_id,
        )
    )


def _save_requirement(store: ArtifactStore, evidence_id: str) -> str:
    return store.save(
        RequirementProfile(
            meta=_meta(store, state_machine.STAGE_REQUIREMENT, "rp"),
            evidence_run_id=evidence_id,
        )
    )


def _save_plan(store: ArtifactStore, requirement_id: str, applied: bool) -> str:
    return store.save(
        ExecutionPlan(
            meta=_meta(store, state_machine.STAGE_EXECUTION_PLAN, "ep"),
            requirement_profile_id=requirement_id,
            applied=applied,
        )
    )


def _save_execution(store: ArtifactStore, plan_id: str) -> str:
    return store.save(
        ExecutionState(
            meta=_meta(store, state_machine.STAGE_EXECUTION, "es"),
            execution_plan_id=plan_id,
        )
    )


def _save_application(store: ArtifactStore) -> str:
    return store.save(
        ApplicationState(meta=_meta(store, state_machine.STAGE_APPLICATIONS, "as"))
    )


def _save_review(store: ArtifactStore) -> str:
    return store.save(
        ReviewReport(meta=_meta(store, state_machine.STAGE_REVIEW, "rr"))
    )


def _seed_chain(
    store: ArtifactStore,
    *,
    applied: bool = True,
    with_execution: bool = True,
) -> dict[str, str]:
    ids: dict[str, str] = {}
    ids["profile_id"] = _save_profile_artifact(store)
    ids["target_spec_id"] = _save_target(store)
    ids["market_baseline_id"] = _save_market(store)
    ids["gap_report_id"] = _save_gap(store)
    ids["baseline_plan_id"] = _save_baseline(store)
    ids["company_pool_id"] = _save_pool(store)
    ids["evidence_run_id"] = _save_evidence(store, ids["company_pool_id"])
    ids["requirement_profile_id"] = _save_requirement(store, ids["evidence_run_id"])
    ids["execution_plan_id"] = _save_plan(store, ids["requirement_profile_id"], applied)
    if with_execution:
        ids["execution_state_id"] = _save_execution(store, ids["execution_plan_id"])
    return ids


_STAGE_INDEX = {
    "profile": 1,
    "target": 2,
    "market_baseline": 3,
    "gap": 4,
    "baseline_plan": 5,
    "company_pool": 6,
    "evidence": 7,
    "requirement": 8,
    "execution_plan": 9,
    "execution": 10,
    "executing": 10,
}


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
    profile = CareerProfile()
    mark_brief_shown(profile)
    mark_goal_confirmed(profile)
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()

    assert build_guide(profile).status == "profile"

    profile.core_state["profile_id"] = _save_profile_artifact(store)
    assert build_guide(profile).status == "target"

    profile.core_state["target_spec_id"] = _save_target(store)
    assert build_guide(profile).status == "market"

    profile.core_state["market_baseline_id"] = _save_market(store)
    assert build_guide(profile).status == "gap"

    profile.core_state["gap_report_id"] = _save_gap(store)
    assert build_guide(profile).status == "plan"

    profile.core_state["baseline_plan_id"] = _save_baseline(store)
    assert build_guide(profile).status == "company"

    pool_id = _save_pool(store)
    profile.core_state["company_pool_id"] = pool_id
    assert build_guide(profile).status == "evidence"

    evidence_id = _save_evidence(store, pool_id)
    profile.core_state["evidence_run_id"] = evidence_id
    assert build_guide(profile).status == "requirement"

    requirement_id = _save_requirement(store, evidence_id)
    profile.core_state["requirement_profile_id"] = requirement_id
    assert build_guide(profile).status == "alignment"

    # 执行版已生成但未应用：仍停在阶段 9（对齐），不能当成执行。
    profile.core_state["execution_plan_id"] = _save_plan(store, requirement_id, applied=False)
    assert build_guide(profile).status == "alignment"

    plan_id = _save_plan(store, requirement_id, applied=True)
    profile.core_state["execution_plan_id"] = plan_id
    guide = build_guide(profile)
    assert guide.status == "execution"
    assert "细化" in guide.ask
    assert guide.options[0].startswith("推荐：")

    profile.core_state["execution_state_id"] = _save_execution(store, plan_id)
    guide = build_guide(profile)
    assert guide.status == "execution"
    assert guide.options[0] == "推荐：先看下一步任务"
    assert "登记已投递" in guide.options
    assert "做周检视/计划检查" in guide.options


def test_optional_application_and_review_do_not_block_execution():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state = _seed_chain(store)
    profile.core_state["application_state_id"] = _save_application(store)
    profile.core_state["review_report_id"] = _save_review(store)

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

    # 旧档案有 tasks 视为已进入执行；没有企业池 artifact 时与状态机一样停在阶段 6。
    profile.tasks = [Task(id="task_001", name="任务", phase_id="phase_1")]
    assert build_guide(profile).status == "company"

    profile.tasks[0].status = "completed"
    assert build_guide(profile).status == "company"


def test_legacy_gap_without_research_counts_market_done():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.gap = {"match_score": 60}

    assert build_guide(profile).status == "plan"


def test_guidance_matches_next_action_on_normal_chain():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.core_state = _seed_chain(ArtifactStore())
    profile_module.save_profile(profile, PROFILE_NAME)

    guide = build_guide(profile)
    action = state_machine.next_action(PROFILE_NAME)

    assert guide.status == "execution"
    assert guide.index == _STAGE_INDEX[action["stage"]] == 10


def test_guidance_matches_next_action_on_chain_mismatch():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state = _seed_chain(store)
    # 换成另一个已确认企业池，但证据仍引用旧池：链路失配，停在证据阶段。
    new_pool_id = _save_pool(store)
    profile.core_state["company_pool_id"] = new_pool_id
    profile_module.save_profile(profile, PROFILE_NAME)

    guide = build_guide(profile)
    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EVIDENCE
    assert guide.status == "evidence"
    assert guide.index == _STAGE_INDEX[action["stage"]] == 7


def test_guidance_matches_next_action_on_legacy_profile():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.research = {"report_md": "report.md"}
    profile.gap = {"match_score": 65}
    profile.plan = {"roadmap": {"phases": []}}
    profile.tasks = [Task(id="task_001", name="任务", phase_id="phase_1")]
    profile_module.save_profile(profile, PROFILE_NAME)

    guide = build_guide(profile)
    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_COMPANY_POOL
    assert guide.status == "company"
    assert guide.index == _STAGE_INDEX[action["stage"]] == 6


def test_applied_plan_without_execution_state_stays_at_stage_ten():
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.core_state = _seed_chain(ArtifactStore(), with_execution=False)
    profile_module.save_profile(profile, PROFILE_NAME)

    guide = build_guide(profile)
    action = state_machine.next_action(PROFILE_NAME)

    assert action["stage"] == state_machine.STAGE_EXECUTION
    assert guide.status == "execution"
    assert guide.index == _STAGE_INDEX[action["stage"]] == 10
    assert "细化" in guide.ask


def test_warnings_surface_failed_sources():
    profile = _confirmed_profile()
    profile.research = {
        "report_md": "report.md",
        "source_status": [{"source": "boss", "status": "failed"}],
    }

    notes = warnings(profile)
    assert any("boss" in note for note in notes)
    assert build_guide(profile).warnings


def test_user_brief_summarizes_three_phases():
    brief = user_brief()

    assert "全流程共 12 步" in brief
    assert "归为三段" in brief
    for phase_name in ("定位", "规划", "执行"):
        assert phase_name in brief
    assert "顺序定、节奏自己掌握" in brief
    # 不再逐条列出 12 步
    assert "职业档案构建" not in brief
    assert "周期复盘与计划调整" not in brief
    assert "每步你都能拿到实际的东西" not in brief


def test_login_action_points_to_harness():
    """BOSS 登录询问必须说明 Agent 会直接运行脚本，用户只需扫码。"""
    from src.guidance import BOSS_LOGIN_URL, login_action

    data = login_action("python -m src.scrapers.boss.login")

    assert data["harness_can_run"] is True
    assert data["login_url"] == BOSS_LOGIN_URL == "https://www.zhipin.com/web/user/?ka=header-login"
    assert "harness" in data["agent_action"]
    assert "不要把命令丢给用户" in data["agent_action"]
    assert "同一会话只提示一次" in data["agent_action"]
    assert "扫码" in data["user_instruction"]
    assert "右上角" in data["user_instruction"]
    assert "浏览器会自动关闭" in data["user_instruction"]
    assert "打断这次会话" in data["user_instruction"]


def test_phase_type_label_maps_internal_types_to_chinese():
    """learn/project/intern/research 只在内部使用，对外必须显示中文。"""
    from src.guidance import phase_type_label

    assert phase_type_label("learn") == "学习"
    assert phase_type_label("project") == "项目"
    assert phase_type_label("intern") == "实习"
    assert phase_type_label("research") == "调研"
    assert phase_type_label("") == "阶段"


def test_render_guide_has_one_question_and_no_internal_ids():
    guide = build_guide(CareerProfile())
    text = render_guide(guide)

    assert "位置：" in text and "本轮只问一个问题" in text
    assert "转述纪律" in text
    assert "JD01" in text  # 只作为禁用示例出现，不代表允许展示


def test_gap_guide_asks_expected_outcome_with_research_cases():
    """目标与差距衔接处先问「最终想要什么结果」，并引用真实同背景去向。"""
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)
    profile.core_state["market_baseline_id"] = _save_market(store)
    profile.research = {"cases": [{
        "kind": "success_experience",
        "title": "双非本 AI Agent 上岸复盘",
        "company": "字节跳动",
        "position": "AI Agent 开发",
    }]}

    guide = build_guide(profile)
    assert guide.status == "gap"
    assert "最终想要什么结果" in guide.ask
    assert "字节跳动" in guide.ask, "应引用已有同背景案例的去向"
    assert "大厂/平台" in guide.options and "先上车再发展" in guide.options
    assert "稳定优先" in guide.options and "薪资优先" in guide.options
    assert "成长/技术优先" in guide.options
    assert "expected_outcome" in guide.next_action
    assert "intake" in guide.next_action


def test_gap_guide_marks_missing_case_samples_without_fabricating():
    """没有同背景案例时说明后续调研会补，不编造去向。"""
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)
    profile.core_state["market_baseline_id"] = _save_market(store)
    profile.research = {}

    guide = build_guide(profile)
    assert guide.status == "gap"
    assert "最终想要什么结果" in guide.ask
    assert "后续调研会补" in guide.ask
    assert "去向包括" not in guide.ask


def test_execution_guide_frames_stage_ten_as_maintenance():
    """第 10 步执行期是持续推进与维护，保留打卡/投递/周检视入口。"""
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state = _seed_chain(store)

    guide = build_guide(profile)
    assert guide.status == "execution"
    assert "持续推进与维护" in guide.ask
    assert "登记已投递" in guide.options
    assert "做周检视/计划检查" in guide.options
    assert "checkin_task" in guide.next_action


def test_start_session_emits_brief_and_guide(temp_profile):
    """入口工具直接下发 [USER_BRIEF]/[GUIDE]，不要求模型自己拼开场白。"""
    from src.server import start_session

    out = start_session()

    assert "[USER_BRIEF]" in out and "[GUIDE]" in out
    assert "全流程共 12 步" in out


def test_workflow_status_includes_brief_for_new_profile(temp_profile):
    """模型若直接调 get_workflow_status，也必须拿到完整首屏，而不是悬空提示。"""
    from src.server import get_workflow_status

    out = get_workflow_status()

    assert "[USER_BRIEF]" in out and "全流程共 12 步" in out
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
    assert "我先确认目标" not in after
    assert "[GUIDE]" in after


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


def test_intake_want_before_finalize_does_not_jump_to_market(temp_profile):
    """BUG #12-13：目标写入/确认后仍未 finalize，引导不能跳到市场调研（第 3 步）。"""
    from src.server import get_workflow_status, intake, start_session

    start_session()
    intake("want", '{"target_role": "AI Agent", "city": "上海"}')

    guide = build_guide(profile_module.load_profile())
    assert guide.status in ("profile", "goal")
    assert guide.index < 3
    assert "finalize_profile" in get_workflow_status()

    intake(
        "want",
        '{"target_role": "AI Agent", "city": "上海", "user_confirmed": true}',
    )

    guide = build_guide(profile_module.load_profile())
    assert guide.status == "profile"
    assert guide.index == 1
    # 状态报告读档时也不能因为已有 want/下游 artifact 而补出已 finalize 的假象
    status = get_workflow_status()
    assert "**下一步**：finalize_profile" in status


@pytest.mark.parametrize(
    ("section", "payload"),
    [
        ("who", '{"name": "张三"}'),
        ("have", '{"skills": ["Python"]}'),
    ],
)
def test_intake_section_never_repeats_familiarity_question(
    temp_profile, section, payload
):
    """BUG #14：填过任意 section 后，GUIDE 不再重复首屏「了解多少」。"""
    from src.server import intake, start_session

    start_session()
    intake(section, payload)

    guide = build_guide(profile_module.load_profile())
    assert guide.status not in ("brief", "familiarity")
    assert "你对毕业后的方向了解多少" not in guide.ask


def test_intake_want_unconfirmed_enters_goal_confirmation(temp_profile):
    """BUG #14：已有 want 且未确认时进入目标确认，而不是重复首屏。"""
    from src.server import intake, start_session

    start_session()
    intake("want", '{"target_role": "AI Agent", "city": "上海"}')

    guide = build_guide(profile_module.load_profile())
    assert guide.status == "goal"
    assert "我先确认目标" in guide.ask
    assert "你对毕业后的方向了解多少" not in guide.ask


def test_market_guide_matches_research_market_four_step_template():
    """BUG #15：市场引导按 4 步模板播报，耗时口径与 research_market 一致。"""
    from src.server import research_market

    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)

    guide = build_guide(profile)
    assert guide.status == "market"
    assert "要现在开始吗" not in guide.ask
    assert "先跳过" not in " ".join(guide.options)
    text = render_guide(guide)
    assert "4 步" in text
    assert "30-50 秒" in text
    assert "本轮不用等确认" in text
    assert "本轮只问一个问题" not in text

    steps = ("范围宣告", "批量抓取", "报告落地", "衔接分析")
    assert all(name in text for name in steps)

    profile_module.save_profile(profile, PROFILE_NAME)
    market_context = research_market()
    assert all(name in market_context for name in steps)


def test_evidence_and_requirement_guides_start_without_confirmation_pause():
    """名单确认后直接采集、证据就绪后直接分析，不再问「要现在开始吗」。"""
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)
    profile.core_state["market_baseline_id"] = _save_market(store)
    profile.core_state["gap_report_id"] = _save_gap(store)
    profile.core_state["baseline_plan_id"] = _save_baseline(store)
    pool_id = _save_pool(store)
    profile.core_state["company_pool_id"] = pool_id

    guide = build_guide(profile)
    assert guide.status == "evidence"
    assert "现在直接" in guide.ask
    assert "要现在开始吗" not in guide.ask
    assert "开始采集" not in guide.options
    assert "补充 BOSS 薪资" in guide.options
    assert "不要问是否开始" in guide.next_action

    profile.core_state["evidence_run_id"] = _save_evidence(store, pool_id)
    guide = build_guide(profile)
    assert guide.status == "requirement"
    assert "现在直接" in guide.ask
    assert "要现在分析吗" not in guide.ask
    assert guide.next_action.startswith("直接调用 analyze_company_requirements")
