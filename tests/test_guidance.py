"""引导状态机回归：位置推导、目标确认、单一文案源、与状态机一致。"""

from __future__ import annotations

import json
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
from src.core.progress import resolve_progress  # noqa: E402
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
    assert "简历" in guide.ask and "4 项" in guide.ask
    assert guide.kind == "intake"
    assert guide.options == ["我有简历，给路径", "我一次说 4 项", "先只定方向"]
    assert "首次进入" in render_guide(guide)  # 提示模型先发 [USER_BRIEF]


def test_after_brief_waits_for_intake_before_goal():
    profile = CareerProfile()
    mark_brief_shown(profile)

    guide = build_guide(profile)
    assert guide.status == "intake_wait"
    assert "写进档案" in guide.ask
    assert "不要重复提问" in guide.next_action
    assert "本轮不用等确认" in render_guide(guide)

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

    assert "位置：" in text and "本轮采集" in text
    assert "转述纪律" in text
    assert "不要追加第二个决策" in text
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


def test_intake_bundle_writes_sections_and_confirms_goal(temp_profile):
    """bundle 一次写入 who/have/want，并点亮用户确认的目标。"""
    from src.server import intake

    intake(
        "bundle",
        json.dumps(
            {
                "who": {"name": "张三", "graduation_year": "2028"},
                "have": {"skills": ["Python"]},
                "want": {"target_role": "AI Agent", "city": "上海"},
            },
            ensure_ascii=False,
        ),
        user_confirmed=True,
    )

    profile = profile_module.load_profile()
    assert profile.who["name"] == "张三"
    assert profile.have["skills"] == ["Python"]
    assert profile.want["target_role"] == "AI Agent"
    assert goal_confirmed(profile)


def test_intake_bundle_guide_does_not_repeat_card(temp_profile):
    """bundle 写全且目标确认后，GUIDE 不再重复采集卡，下一步与 progress 同为整理档案。"""
    from src.server import intake

    intake(
        "bundle",
        json.dumps(
            {
                "who": {"name": "张三"},
                "have": {"skills": ["Python"]},
                "want": {"target_role": "AI Agent"},
            },
            ensure_ascii=False,
        ),
        user_confirmed=True,
    )

    profile = profile_module.load_profile()
    progress = resolve_progress(profile)
    guide = build_guide(profile)

    assert progress["next_tool"] == "finalize_profile"
    assert "有简历就直接发我" not in guide.ask
    assert guide.options == ["开始整理"]
    assert "finalize_profile" in guide.next_action


def test_intake_fenced_json_stores_structured_payload(temp_profile):
    """markdown 围栏 JSON 写入结构化字段，不是 {"raw": ...}。"""
    from src.server import intake

    intake("who", '```json\n{"name": "李四", "education": "计算机本科"}\n```')

    profile = profile_module.load_profile()
    assert profile.who == {"name": "李四", "education": "计算机本科"}
    assert "raw" not in profile.who


def test_finalize_does_not_auto_confirm_inferred_goal(temp_profile):
    """finalize 不得代替用户确认目标；推断的 want 仍被 analyze_gaps 拒绝。"""
    from src.server import analyze_gaps, finalize_profile, intake

    intake("who", '{"name": "张三"}')
    intake("want", '{"target_role": "AI Agent", "city": "上海"}')
    out = finalize_profile()
    assert "档案已确认" in out

    profile = profile_module.load_profile()
    assert not goal_confirmed(profile)

    blocked = json.loads(analyze_gaps())
    assert blocked["code"] == "GOAL_CONFIRMATION_REQUIRED"


def test_finalize_rejects_empty_profile(temp_profile):
    """空档案 finalize 返回 MISSING_DATA，不生成摘要。"""
    from src.server import finalize_profile

    out = json.loads(finalize_profile())
    assert out.get("isError") is True
    assert out["code"] == "MISSING_DATA"


def test_next_step_shared_across_start_status_and_roadmap(temp_profile):
    """start_session / get_workflow_status / save_roadmap 的下一步与 resolve_progress 同源。"""
    from src.server import (
        finalize_profile,
        get_workflow_status,
        intake,
        save_roadmap,
        start_session,
    )

    intake("who", '{"name": "张三"}')
    intake("have", '{"skills": []}')
    intake("want", '{"target_role": "AI 工程师", "user_confirmed": true}')
    finalize_profile()

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "project",
                    "name": "做项目",
                    "resume_value": "项目经历",
                    "kpi": {"metric": "完成", "target": "1个"},
                }
            ],
        }
    }
    saved = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))
    expected = resolve_progress(profile_module.load_profile())["next_tool"]

    assert saved["next_steps"][0] == expected
    assert f"**下一步**：{expected}" in get_workflow_status()
    assert f"下一步：{expected}" in start_session()


def test_gap_stale_forces_gap_even_with_tasks():
    """gap_stale_at 存在时回到差距阶段，已有 tasks 不能覆盖。"""
    profile = CareerProfile()
    mark_brief_shown(profile)
    mark_goal_confirmed(profile)
    profile.who = {"name": "张三"}
    profile.want = {"target_role": "AI Agent"}
    profile.gap = {"match_score": 50}
    profile.gap_stale_at = datetime.now().isoformat()
    profile.tasks = [Task(id="task_001", name="任务", phase_id="phase_1")]

    progress = resolve_progress(profile)
    assert progress["stage"] == "gap"
    assert progress["next_tool"] == "analyze_gaps"
    assert build_guide(profile).status == "gap"


def test_save_current_detail_guides_generate_tasks(temp_profile):
    """保存详细路线后 GUIDE 不再推荐细化，下一步是 generate_tasks。"""
    from src.server import save_current_detail

    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    profile.plan = {"roadmap": {"phases": [{"id": "phase_1", "name": "基础学习"}]}}
    profile.core_state = _seed_chain(ArtifactStore(), with_execution=False)
    profile_module.save_profile(profile, PROFILE_NAME)

    save_current_detail(
        json.dumps(
            {"phase_id": "phase_1", "tasks": [{"name": "学 Python"}]},
            ensure_ascii=False,
        )
    )

    updated = profile_module.load_profile(PROFILE_NAME)
    guide = build_guide(updated)
    assert guide.status == "execution"
    assert "细化" not in guide.ask
    assert guide.next_action.startswith("generate_tasks")


def test_graduation_year_in_who_suppresses_pending_label(temp_profile):
    """graduation_year 写在 who 时，目标确认问句不再显示「届别（待确认）」。"""
    profile = CareerProfile()
    mark_brief_shown(profile)
    profile.who = {"name": "张三", "graduation_year": "2028"}
    profile.want = {"target_role": "AI Agent", "city": "上海"}

    guide = build_guide(profile)
    assert guide.status == "goal"
    assert "届别 2028" in guide.ask
    assert "届别（待确认）" not in guide.ask


def test_import_jd_returns_guide_and_confirmation_hint(temp_profile):
    """import_jd 附带 GUIDE，并提示先确认目标，不写死 analyze_gaps。"""
    from src.server import import_jd

    out = import_jd('{"company": "测试公司", "role": "AI 工程师"}')
    assert "[GUIDE]" in out
    assert "确认目标" in out
    assert "下一步：调用 analyze_gaps" not in out


def test_company_and_alignment_guides_have_no_skip_branch():
    """企业适配是执行前必做：company / alignment 引导不再提供跳过或按基线选项。"""
    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)
    profile.core_state["market_baseline_id"] = _save_market(store)
    profile.core_state["gap_report_id"] = _save_gap(store)
    profile.core_state["baseline_plan_id"] = _save_baseline(store)

    company = build_guide(profile)
    assert company.status == "company"
    company_text = render_guide(company)
    assert "跳过" not in company_text and "按基线" not in company_text
    assert company.options == ["生成目标企业名单"]

    pool_id = _save_pool(store)
    profile.core_state["company_pool_id"] = pool_id
    profile.core_state["evidence_run_id"] = _save_evidence(store, pool_id)
    profile.core_state["requirement_profile_id"] = _save_requirement(
        store, profile.core_state["evidence_run_id"]
    )

    alignment = build_guide(profile)
    assert alignment.status == "alignment"
    alignment_text = render_guide(alignment)
    assert "跳过" not in alignment_text and "按基线" not in alignment_text
    assert alignment.options == ["开始校准"]


def test_save_roadmap_points_to_company_adaptation_without_skip(temp_profile):
    """save_roadmap 的 message 与 next_steps 都指向 select_target_companies。"""
    from src.server import save_roadmap

    profile = _confirmed_profile()
    profile.want = {"target_role": "AI Agent", "city": "上海"}
    store = ArtifactStore()
    profile.core_state["profile_id"] = _save_profile_artifact(store)
    profile.core_state["target_spec_id"] = _save_target(store)
    profile.core_state["market_baseline_id"] = _save_market(store)
    profile.core_state["gap_report_id"] = _save_gap(store)
    profile_module.save_profile(profile, PROFILE_NAME)

    roadmap = {
        "roadmap": {
            "strategy_summary": "测试",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "project",
                    "name": "做项目",
                    "resume_value": "项目经历",
                    "kpi": {"metric": "完成", "target": "1个"},
                }
            ],
        }
    }
    out = json.loads(save_roadmap(json.dumps(roadmap, ensure_ascii=False)))

    assert out["next_steps"] == ["select_target_companies"]
    assert "select_target_companies" in out["message"]
    assert "跳过" not in out["message"] and "按基线" not in out["message"]


def test_start_session_empty_profile_does_not_route_to_finalize(temp_profile):
    """空档案的新用户下一步是采集卡，不写死工具名或 finalize_profile。"""
    from src.server import start_session

    out = start_session()
    next_line = next(line for line in out.splitlines() if line.startswith("下一步："))
    assert "finalize_profile" not in next_line
    assert "parse_resume" not in next_line and "intake(" not in next_line
    assert "按 [GUIDE] 采集卡" in next_line


def test_workflow_status_empty_profile_matches_start_session(temp_profile):
    """空档案的 progress、GUIDE 采集卡与状态报告下一步保持一致。"""
    from src.server import get_workflow_status, start_session

    progress = resolve_progress(profile_module.load_profile())
    assert progress["next_tool"] == "intake(section='bundle')"

    guide = build_guide(CareerProfile())
    assert guide.kind == "intake"
    assert "4 项" in guide.ask

    status = get_workflow_status()
    assert "**下一步**：finalize_profile" not in status
    assert "该阶段下一步：finalize_profile" not in status
    assert "intake(section='bundle')" in status

    session = start_session()
    assert "下一步：按 [GUIDE] 采集卡" in session


def test_progress_stays_on_target_before_goal_confirmation(temp_profile):
    """who/have 已写但目标未确认时，progress 按目标阶段处理，不返回 finalize_profile。"""
    profile = CareerProfile()
    mark_brief_shown(profile)
    profile.who = {"name": "张三"}
    profile.have = {"skills": []}

    progress = resolve_progress(profile)
    assert progress["stage"] == "target"
    assert progress["next_tool"] == "explore_goals"
    assert progress["next_tool"] != "finalize_profile"

    guide = build_guide(profile)
    assert guide.status == "goal"
    assert "explore_goals" in guide.next_action

    profile.want = {"target_role": "AI Agent"}
    progress = resolve_progress(profile)
    assert progress["stage"] == "target"
    assert progress["next_tool"] == "intake(want)"


def test_tool_layer_has_no_empty_profile_next_step_override():
    """空档案下一步只由 progress 推导，工具层不再二次维护特例。"""
    tools_dir = Path(__file__).parent.parent / "src" / "tools"
    for name in ("task_tools.py", "session_tools.py"):
        text = (tools_dir / name).read_text(encoding="utf-8")
        assert "parse_resume / intake(section='bundle')" not in text


def test_intake_wait_user_section_has_no_tool_names():
    """intake_wait 的 [GUIDE] 转述区不出现工具名；工具名只在 GUIDE_MODEL 之后。"""
    from src.guidance import _STATUS_META

    profile = CareerProfile()
    mark_brief_shown(profile)
    guide = build_guide(profile)
    assert guide.status == "intake_wait"

    text = render_guide(guide)
    user_part = text.split("[GUIDE_MODEL]", 1)[0]

    banned = ("parse_resume", "intake(", "finalize_profile")
    for name in banned:
        assert name not in user_part
    assert "intake(section='bundle'" in guide.next_action

    for status, (_what, method, _how) in _STATUS_META.items():
        for name in banned:
            assert name not in method, f"{status} method 泄露工具名：{method}"


def test_intake_bundle_return_does_not_self_manage_next_step(temp_profile):
    """bundle 已写全时，intake 返回不再硬编码「继续补齐」。"""
    from src.server import intake

    out = intake(
        "bundle",
        json.dumps(
            {
                "who": {"name": "张三"},
                "have": {"skills": ["Python"]},
                "want": {"target_role": "AI Agent"},
            },
            ensure_ascii=False,
        ),
        user_confirmed=True,
    )
    assert "已记录到" in out
    assert "继续补齐" not in out
    assert "[GUIDE]" in out
