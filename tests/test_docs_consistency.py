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
