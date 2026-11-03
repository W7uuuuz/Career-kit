"""文档一致性回归：工具数量、工具名与引导文案不得漂移。

背景：record_application/get_weekly_review 上线后，README 与 docs/README
仍写「32 个工具」（实际 34）——用本测试锁定，防止下次再漂。

引导文案已收敛到 src/guidance.py：命令剧本只负责路由，不再复制 6 步模板。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

REPO_ROOT = Path(__file__).parent.parent


def _registered_tool_names() -> list[str]:
    from src.server import mcp

    tools = mcp._tool_manager.list_tools()
    return sorted(t.name for t in tools)


def _read(*rel: str) -> str:
    return (REPO_ROOT.joinpath(*rel)).read_text(encoding="utf-8")


def test_registered_tools_match_doctor_count():
    """doctor.EXPECTED_TOOL_COUNT 与真实注册工具数一致（含核心工具命名）。"""
    from src.doctor import CORE_TOOLS, EXPECTED_TOOL_COUNT

    assert len(CORE_TOOLS) <= EXPECTED_TOOL_COUNT
    assert CORE_TOOLS[0] == "start_session"
    # doctor 本身是工具模块之外的命令，不参与注册——注册数即权威
    assert len(_registered_tool_names()) == EXPECTED_TOOL_COUNT


def test_tools_md_covers_every_registered_tool():
    """docs/tools.md 必须覆盖全部注册工具名（唯一事实源不许漏）。"""
    text = _read("docs", "tools.md")
    missing = [n for n in _registered_tool_names() if n not in text]
    assert not missing, f"docs/tools.md 缺少工具：{missing}"


def test_tool_count_copies_are_fresh():
    """README / docs/README / docs/llms.txt / docs/tools.md 的工具数文案一致。"""
    from src.doctor import EXPECTED_TOOL_COUNT

    anchor = f"{EXPECTED_TOOL_COUNT} 个"
    stale = f"{EXPECTED_TOOL_COUNT - 2} 个"  # 曾经的 32 vs 34 漂移
    for rel in [
        ("README.md",),
        ("docs", "README.md"),
        ("docs", "llms.txt"),
        ("docs", "tools.md"),
    ]:
        text = _read(*rel)
        assert anchor in text, f"{rel} 未提及最新工具数 {anchor}"
        assert stale not in text, f"{rel} 仍写着旧工具数 {stale}"


def test_secondary_tool_count_copies_are_fresh():
    """次级文档也不能保留旧的 30/32/34 工具数。"""
    from src.doctor import EXPECTED_TOOL_COUNT

    for rel in [("src", "tools", "README.md"), ("tests", "e2e", "README.md")]:
        text = _read(*rel)
        assert str(EXPECTED_TOOL_COUNT) in text, f"{rel} 未写最新工具数"
        for stale in ("32 个", "34 个", "30/32"):
            assert stale not in text, f"{rel} 仍写着旧工具数 {stale}"


def test_root_llms_txt_includes_funnel_tools():
    """根目录 llms.txt 快速开始必须包含漏斗与周检视两步。"""
    text = _read("llms.txt")
    assert "record_application" in text
    assert "get_weekly_review" in text


def test_scraper_config_matches_public_docs():
    """docs/scrapers.md 收录企业与 src/scrapers/config.yaml 注册源一致。"""
    config = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "config.yaml").read_text(encoding="utf-8")
    )
    ids = set(config["scrapers"])
    assert ids, "src/scrapers/config.yaml 为空？"
    docs = _read("docs", "scrapers.md")
    missing = [i for i in ids if i not in docs]
    assert not missing, f"docs/scrapers.md 缺少企业：{missing}"


# ---------------------------------------------------------------------------
# 引导系统一致性
# ---------------------------------------------------------------------------

BUG021_ANCHORS = ("authorship", "control_level", "self_assessment")

GUIDANCE_ANCHORS = ("[USER_BRIEF]", "[GUIDE]", "start_session")


def _probe_text() -> str:
    from src.tools.probing import SELF_ASSESSMENT_INSTRUCTIONS

    return SELF_ASSESSMENT_INSTRUCTIONS


def test_bug021_instructions_reach_execution_surfaces():
    """自评三问的详细话术只留在执行侧，命令剧本不再复制。"""
    probe = _probe_text()
    for anchor in BUG021_ANCHORS:
        assert anchor in probe, f"话术常量缺锚点 {anchor}"

    surfaces = [
        ("src", "tools", "session_tools.py"),
        ("src", "tools", "session.py"),
        ("sop", "resume_screening.yaml"),
        ("sop", "goal_selection.yaml"),
        ("docs", "llms.txt"),
        ("docs", "workflow.md"),
        ("docs", "tools.md"),
    ]
    for rel in surfaces:
        text = _read(*rel)
        missing = [a for a in BUG021_ANCHORS if a not in text]
        assert not missing, f"{rel} 未同步 BUG-021 自评话术，缺：{missing}"


def test_command_scripts_are_thin_and_guidance_driven():
    """命令剧本只负责路由：引用 [USER_BRIEF]/[GUIDE]，禁止复制阶段模板。"""
    for rel in [
        (".opencode", "commands", "career-kit.md"),
        (".claude", "commands", "career-kit.md"),
    ]:
        text = _read(*rel)
        missing = [a for a in GUIDANCE_ANCHORS if a not in text]
        assert not missing, f"{rel} 缺少引导锚点：{missing}"
        assert "从起步到上岸全流程 6 步" not in text, f"{rel} 不应复制首屏模板"
        assert "1. 建档摸底" not in text, f"{rel} 不应复制阶段清单"
        assert "第一条动作必须是调用" in text, f"{rel} 缺少先调 start_session 的硬规则"
        assert "detail_current_phase" in text, f"{rel} 执行阶段应先细化再生成任务"


def test_user_brief_is_single_source_of_truth():
    """6 步简介只由 guidance 定义；session.py 与命令剧本只引用。"""
    from src.guidance import JOURNEY_STEPS, user_brief

    brief = user_brief()
    assert "Career Kit 是你的 AI 职业陪练" in brief
    assert "从起步到上岸全流程 6 步" in brief
    assert "现在从第 1 步开始" in brief
    for step in JOURNEY_STEPS:
        assert step.name in brief, f"首屏简介缺阶段 {step.name}"

    session_text = _read("src", "tools", "session.py")
    assert "[USER_BRIEF]" in session_text
    assert "从起步到上岸全流程 6 步" not in session_text, "session.py 不应复制首屏模板"


def test_entry_tools_emit_guidance_blocks():
    """入口工具必须直接返回引导块，而不是让模型自己拼。"""
    session_tools = _read("src", "tools", "session_tools.py")
    assert "opening_blocks(profile)" in session_tools
    assert "guide_for(load_profile())" in session_tools

    task_tools = _read("src", "tools", "task_tools.py")
    assert "guide_for(profile)" in task_tools
