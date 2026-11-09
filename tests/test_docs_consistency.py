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


def test_llms_docs_list_twelve_steps_in_order():
    """根 llms.txt 与 docs/llms.txt 必须按 guidance 顺序列出全部 12 步名称。"""
    from src.guidance import JOURNEY_STEPS

    for rel in [("llms.txt",), ("docs", "llms.txt")]:
        text = _read(*rel)
        assert "12 步" in text, f"{rel} 未写「12 步」"
        positions = []
        for step in JOURNEY_STEPS:
            pos = text.find(step.name)
            assert pos >= 0, f"{rel} 缺少阶段名：{step.name}"
            positions.append(pos)
        assert positions == sorted(positions), f"{rel} 的 12 步顺序与 guidance 不一致"


def test_root_llms_txt_covers_company_alignment_and_plan_fit():
    """根 llms.txt 必须覆盖阶段 6-9、sync 层与计划失配检测。"""
    text = _read("llms.txt")
    for tool in (
        "select_target_companies",
        "collect_company_evidence",
        "analyze_company_requirements",
        "save_requirement_profile",
        "plan_execution_alignment",
        "save_execution_alignment",
    ):
        assert tool in text, f"根 llms.txt 缺少企业适配工具：{tool}"
    assert "sync" in text.lower(), "根 llms.txt 未说明 sync 层"
    assert "check_plan_fit" in text, "根 llms.txt 未说明计划失配检测"


def test_onboarding_prompt_uses_twelve_step_brief():
    """开场提示必须描述 12 步简介，不能残留 6 步口径。"""
    text = _read("docs", "prompts", "onboarding.md")
    assert "12 步简介" in text
    assert "6 步" not in text


STALE_STEP_TOOL_PATTERNS = ("47 个", "6 步", "7 步")


def test_public_docs_have_no_stale_step_or_tool_counts():
    """根 llms.txt / docs/llms.txt / onboarding 不得残留旧步数或旧工具数。"""
    for rel in [
        ("llms.txt",),
        ("docs", "llms.txt"),
        ("docs", "prompts", "onboarding.md"),
    ]:
        text = _read(*rel)
        found = [p for p in STALE_STEP_TOOL_PATTERNS if p in text]
        assert not found, f"{rel} 仍含陈旧数字：{found}"


def _changelog_section(version: str) -> str:
    text = _read("CHANGELOG.md")
    marker = f"## {version}"
    start = text.find(marker)
    assert start >= 0, f"CHANGELOG.md 缺少 {marker} 段"
    rest = text[start + len(marker):]
    next_section = rest.find("\n## ")
    return rest if next_section < 0 else rest[:next_section]


def test_changelog_v030_has_single_12_step_49_tool_caliber():
    """v0.3.0 只能保留 12 步 / 49 工具口径，不能出现 7 步 / 48 工具矛盾。"""
    section = _changelog_section("v0.3.0")
    assert "12 步" in section, "CHANGELOG v0.3.0 未写 12 步"
    assert "49" in section, "CHANGELOG v0.3.0 未写 49 工具"
    found = [p for p in STALE_STEP_TOOL_PATTERNS if p in section]
    assert not found, f"CHANGELOG v0.3.0 仍含陈旧数字：{found}"


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


def _source_caliber() -> tuple[int, int, int, int]:
    config = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "config.yaml").read_text(encoding="utf-8")
    )
    companies = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "companies.yaml").read_text(encoding="utf-8")
    )["companies"]
    total = len(config["scrapers"])
    company_sources = total - 3
    registered = set(config["scrapers"])
    scrapable = sum(
        1
        for item in companies
        if any(str(scraper) in registered for scraper in item.get("scrapers", []))
    )
    return total, company_sources, len(companies), scrapable


def test_source_counts_match_registered_sources():
    """README / README.en / docs/index / scrapers README 的数据源数量与配置一致。"""
    total, company_sources, companies, scrapable = _source_caliber()

    checks = [
        (
            ("README.md",),
            [
                f"{total} 个已收录数据源",
                f"企业招聘源（{company_sources} 个）",
                f"企业目录收录 {companies} 家",
                f"{scrapable} 家可自动抓取",
            ],
        ),
        (
            ("README.en.md",),
            [
                f"{total} collected sources",
                f"Company career sources ({company_sources})",
                f"lists {companies} companies",
                f"{scrapable} of which are auto-scrapable",
            ],
        ),
        (
            ("docs", "index.html"),
            [
                f"{total} 个已收录数据源",
                f"{company_sources} 个企业招聘源",
                f"企业目录 {companies} 家",
                f"{scrapable} 家可自动抓取",
            ],
        ),
        (
            ("src", "scrapers", "README.md"),
            [
                f"已注册企业（{total}）",
                f"企业目录收录 {companies} 家",
                f"{scrapable} 家可自动抓取",
            ],
        ),
    ]
    for rel, anchors in checks:
        text = _read(*rel)
        missing = [anchor for anchor in anchors if anchor not in text]
        assert not missing, f"{rel} 缺少最新数据源口径：{missing}"


def _scrapers_doc_table_ids(text: str) -> list[str]:
    """解析 docs/scrapers.md 的「已收录企业」表，返回 ID 列。"""
    section = text.split("## 已收录企业", 1)[1].split("\n> ", 1)[0]
    ids: list[str] = []
    for line in section.splitlines():
        if line.startswith("| `"):
            parts = line.split("`")
            if len(parts) >= 2 and parts[1].strip():
                ids.append(parts[1].strip())
    return ids


def test_scrapers_docs_and_llms_source_counts_match_registry():
    """docs/scrapers.md 与 docs/llms.txt 的数据源计数、表格行数与注册表一致。"""
    total, company_sources, companies, scrapable = _source_caliber()
    config = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "config.yaml").read_text(encoding="utf-8")
    )

    docs = _read("docs", "scrapers.md")
    assert f"{total} 个数据源" in docs
    assert f"{company_sources} 个企业招聘源" in docs
    assert f"{companies} 家" in docs
    assert f"{scrapable} 家可自动抓取" in docs

    table_ids = _scrapers_doc_table_ids(docs)
    assert len(table_ids) == total, f"docs/scrapers.md 表格行数 {len(table_ids)} != 注册数 {total}"
    assert set(table_ids) == set(config["scrapers"]), "docs/scrapers.md 表格与注册表不一致"

    llms = _read("docs", "llms.txt")
    assert f"{total} 个已收录源" in llms
    assert f"企业目录收录 {companies} 家" in llms
    assert f"{scrapable} 家可自动抓取" in llms


def test_companies_yaml_covers_registered_scrapers():
    """每个非平台 scraper 都必须在 companies.yaml 有企业映射。"""
    config = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "config.yaml").read_text(encoding="utf-8")
    )
    companies = yaml.safe_load(
        (REPO_ROOT / "src" / "scrapers" / "companies.yaml").read_text(encoding="utf-8")
    )["companies"]
    mapped = {
        str(scraper)
        for item in companies
        for scraper in item.get("scrapers", [])
    }
    platforms = {"boss", "nowcoder", "github"}
    missing = sorted(set(config["scrapers"]) - platforms - mapped)
    assert not missing, f"companies.yaml 缺少 scraper 映射：{missing}"


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
        assert "全流程共 12 步" not in text, f"{rel} 不应复制首屏模板"
        assert "1. 职业档案构建" not in text, f"{rel} 不应复制阶段清单"
        assert "第一条动作必须是调用" in text, f"{rel} 缺少先调 start_session 的硬规则"
        assert "detail_current_phase" in text, f"{rel} 执行阶段应先细化再生成任务"
        assert "build_application_list" in text, f"{rel} 缺少投递清单工具"
        assert "执行前必做" not in text, f"{rel} 企业适配应为推荐 + 可审计跳过"
        assert "按基线执行" in text and "跳过" in text, f"{rel} 缺少基线执行/跳过说明"


def test_user_brief_is_single_source_of_truth():
    """首屏简介只由 guidance 定义；session.py 与命令剧本只引用。"""
    from src.guidance import user_brief

    brief = user_brief()
    assert "Career Kit 是你的 AI 职业陪练" in brief
    assert "全流程共 12 步" in brief
    assert "归为三段" in brief
    for phase_name in ("定位", "规划", "执行"):
        assert phase_name in brief
    assert "现在从第 1 步开始" in brief
    assert "职业档案构建" not in brief, "首屏简介不应再逐条罗列 12 步"

    session_text = _read("src", "tools", "session.py")
    assert "[USER_BRIEF]" in session_text
    assert "全流程共 12 步" not in session_text, "session.py 不应复制首屏模板"


def test_entry_tools_emit_guidance_blocks():
    """入口工具必须直接返回引导块，而不是让模型自己拼。"""
    session_tools = _read("src", "tools", "session_tools.py")
    assert "opening_blocks(profile)" in session_tools
    assert "guide_for(load_profile())" in session_tools

    task_tools = _read("src", "tools", "task_tools.py")
    assert "guide_for(profile)" in task_tools


# ---------------------------------------------------------------------------
# BOSS 模型可见文案
# ---------------------------------------------------------------------------

import re  # noqa: E402

STALE_BOSS_COPY = (
    (r"(?<!不)会自动关闭", "声称浏览器会自动关闭"),
    (r"稍等，浏览器", "扫码后自动关闭的旧话术"),
    (r"先问是否登录", "未登录时二次询问登录"),
    (r"先问用户是否登录", "未登录时二次询问登录"),
    (r"要现在登录吗", "二次询问是否现在登录"),
    (r"先问「是否现在登录", "二次询问是否现在登录"),
    (r"先问用户是否抓取/登录", "把抓取与登录拆成两次询问"),
    (r"未登录先问是否扫码", "未登录时二次询问扫码"),
)

BOSS_VISIBLE_COPY_FILES = (
    ("llms.txt",),
    ("docs", "llms.txt"),
    ("docs", "workflow.md"),
    ("src", "tools", "session.py"),
    ("src", "tools", "data_tools.py"),
    ("src", "tools", "research_tools.py"),
    ("src", "tools", "evidence_tools.py"),
)


def test_boss_visible_copy_has_no_stale_login_or_autoclose_wording():
    """根 llms.txt / workflow / session.py 等不得保留「自动关闭」「先问是否登录」。"""
    offenders = []
    for rel in BOSS_VISIBLE_COPY_FILES:
        text = _read(*rel)
        for pattern, reason in STALE_BOSS_COPY:
            if re.search(pattern, text):
                offenders.append(f"{'/'.join(rel)}: {reason}")
    assert not offenders, f"BOSS 旧话术未清理：{offenders}"


def test_evidence_guide_boss_next_action_calls_login_directly():
    """_evidence_guide 的 BOSS 分支：先 login 再 collect，且不二次询问。"""
    from src.guidance import _evidence_guide

    action = _evidence_guide(None).next_action
    assert "boss_login(action='login')" in action
    assert "collect_company_evidence" in action
    assert action.index("boss_login") < action.index("collect_company_evidence")
    assert "不要二次询问是否登录" in action
