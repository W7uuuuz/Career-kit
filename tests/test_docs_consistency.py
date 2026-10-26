"""文档一致性回归：工具数量与工具名在 docs 与注册表之间不得漂移。

背景：record_application/get_weekly_review 上线后，README 与 docs/README
仍写「32 个工具」（实际 34）——用本测试锁定，防止下次再漂。
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


BUG021_ANCHORS = ("authorship", "control_level", "self_assessment")


def _probe_text() -> str:
    from src.tools.probing import SELF_ASSESSMENT_INSTRUCTIONS

    return SELF_ASSESSMENT_INSTRUCTIONS


def test_bug021_instructions_reach_all_delivery_channels():
    """BUG-021 防漂移：自评三问话术必须同步到全部交付面，缺一处即失败。

    覆盖面：
    - 话术常量本身带三个锚点词（authorship/control_level/self_assessment）
    - parse_resume 指令正文
    - session.py 手册（WELCOME_PROMPT Phase 1）
    - 两份命令剧本（.opencode/commands 与 .claude/commands，探针②文本一致）
    - 两份 sop 方法论（resume_screening / goal_selection）
    - 三份公开文档（docs/llms.txt / docs/workflow.md / docs/tools.md）
    """
    probe = _probe_text()
    for anchor in BUG021_ANCHORS:
        assert anchor in probe, f"话术常量缺锚点 {anchor}"

    surfaces = [
        ("src", "tools", "session_tools.py"),
        ("src", "tools", "session.py"),
        (".opencode", "commands", "career-kit.md"),
        (".claude", "commands", "career-kit.md"),
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


def test_bug021_command_scripts_have_identical_probe_text():
    """BUG-021：两份命令剧本的「自评三问」块必须逐字一致（历史漂移过）。"""
    oc = _read(".opencode", "commands", "career-kit.md")
    cc = _read(".claude", "commands", "career-kit.md")

    start_oc = oc.find("并同轮完成自评三问")
    start_cc = cc.find("并同轮完成自评三问")
    assert start_oc != -1 and start_cc != -1, "剧本缺少自评三问探针"
    end_oc = oc.find("skip_probing=True)", start_oc) + len("skip_probing=True)")
    end_cc = cc.find("skip_probing=True)", start_cc) + len("skip_probing=True)")
    assert oc[start_oc:end_oc] == cc[start_cc:end_cc], "两份剧本的探针文本漂移了"


WELCOME_OVERVIEW_ANCHORS = [
    "Career Kit 是你的 AI 职业陪练",
    "从起步到上岸全流程 6 步",
    "建档摸底",
    "市场调研",
    "差距分析",
    "路线图规划",
    "阶段顺序定、节奏自己掌握",
    "执行打卡",
    "持续陪跑",
    "拿到了什么、下一步做什么",
    "双击 index.html",
    "回复信息密度",
]


def test_first_reply_overview_reaches_all_surfaces():
    """第一轮流程概览模板必须下发到全部四份入口文本（用户实测反馈的修复）。

    用户实测：/career-kit 发起后直接问个人情况，用户仍不知道全流程——
    概览模板漂移到只剩部分载体时该体验会回归，用锚点锁定四处载体。
    """
    surfaces = [
        ("src", "tools", "session.py"),
        (".opencode", "commands", "career-kit.md"),
        (".claude", "commands", "career-kit.md"),
        ("docs", "llms.txt"),
    ]
    for rel in surfaces:
        text = _read(*rel)
        missing = [a for a in WELCOME_OVERVIEW_ANCHORS if a not in text]
        # llms.txt 是给 LLM 的概览型描述，不逐字含模板句子，只查阶段名链
        if rel == ("docs", "llms.txt"):
            missing = [a for a in missing if a not in (
                "Career Kit 是你的 AI 职业陪练",
                "从起步到上岸全流程 6 步",
                "路线图规划",
                "阶段顺序定、节奏自己掌握",
                "拿到了什么、下一步做什么",
                "双击 index.html",
                "回复信息密度",
            )]
        assert not missing, f"{rel} 未同步第一轮流程概览模板，缺：{missing}"


def test_welcome_overview_scripts_identical():
    """两份命令剧本的「第一轮流程概览」块必须逐字一致（不让模板漂移）。"""
    oc = _read(".opencode", "commands", "career-kit.md")
    cc = _read(".claude", "commands", "career-kit.md")

    probe = "Career Kit 是你的 AI 职业陪练"
    start_oc = oc.find(probe)
    start_cc = cc.find(probe)
    assert start_oc != -1 and start_cc != -1, "剧本缺少流程概览探针"
    tail = "不复述手册其余部分。"
    end_oc = oc.find(tail, start_oc) + len(tail)
    end_cc = cc.find(tail, start_cc) + len(tail)
    assert end_oc != len(tail) - 1 and end_cc != len(tail) - 1, "概览块结尾对不上"
    assert oc[start_oc:end_oc] == cc[start_cc:end_cc], "两份剧本的概览模板漂移了"
