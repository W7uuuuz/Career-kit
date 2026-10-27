"""BOSS 直聘登录交互关卡回归（实测反馈：登录缺失被 LLM 静默当失败）。

流程预期：
- 调研/抓取范围含 BOSS 时，抓取前必须问用户是否抓取（boss_confirmed 硬门槛）；
- 未登录时返回 LOGIN_REQUIRED（问题 + 登录命令），先问用户是否现在登录；
- 只有用户明确同意且登录就绪才真正抓取；非 BOSS 源不受影响。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.tools.profile as profile_module


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _job(company="字节跳动"):
    return {
        "company": company,
        "title": "AI Agent 工程师",
        "location": "北京",
        "salary": "30-50K",
        "summary": "负责 Agent 后端",
        "source": "boss",
        "url": "https://example.com/job/1",
    }


def _no_scrape(slug, **kwargs):  # pragma: no cover - 被调用即失败
    raise AssertionError(f"未确认/未登录时不应抓取 {slug}")


# ============ research_market 话术 ============


def test_research_market_instructs_asking_boss_first(temp_profile):
    from src.server import research_market

    out = json.loads(research_market())
    scope_step = out["step_template"][0]
    assert "BOSS" in scope_step["action"] and "问" in scope_step["action"]
    assert "boss_confirmed" in scope_step["action"]
    assert "boss_confirmed" in out["instructions"]
    assert "LOGIN_REQUIRED" in out["instructions"]


# ============ gather_research_data 确认 / 登录关卡 ============


def test_gather_requires_boss_confirmation(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.setattr(rt, "search_company_jobs", _no_scrape)
    result = json.loads(asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "boss", "limit": 6}]),
        json.dumps({"role": "AI Agent 开发"}),
    )))
    assert result["isError"] is True
    assert result["code"] == "CONFIRMATION_REQUIRED"
    assert "BOSS" in result["message"] and "问用户" in result["message"]
    assert result["details"]["question"]
    assert any("boss_confirmed=true" in opt for opt in result["details"]["options"])
    # 不落盘
    assert not (temp_profile / "CareerKit").exists()


def test_gather_login_required_when_boss_not_logged_in(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.setattr(rt, "search_company_jobs", _no_scrape)
    monkeypatch.setattr(rt, "boss_has_valid_cookies", lambda: False)
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })
    result = json.loads(asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "boss"}]),
        json.dumps({"role": "AI Agent 开发"}),
        boss_confirmed=True,
    )))
    assert result["isError"] is True
    assert result["code"] == "LOGIN_REQUIRED"
    assert "是否现在扫码登录" in result["details"]["question"]
    assert "src.scrapers.boss.login" in result["details"]["login_command"]
    assert "boss_confirmed=true" in result["details"]["after_login"]
    assert not (temp_profile / "CareerKit").exists()


def test_gather_boss_unlogged_continues_other_sources(temp_profile, monkeypatch):
    """BOSS 未登录不阻断其他源：其他源数据照常落盘，BOSS 记为来源失败。"""
    import src.tools.research_tools as rt

    calls: list[str] = []

    def fake_loader(slug, **kwargs):
        calls.append(slug)
        if slug == "boss":
            raise AssertionError("未登录时不应请求 BOSS")
        return {"company": "百度", "count": 1, "results": [{
            "title": "AI 工程师", "url": "https://x/1", "company": "百度",
            "location": "上海", "description": "完整描述", "requirements": "完整要求",
        }]}

    monkeypatch.setattr(rt, "search_company_jobs", fake_loader)
    monkeypatch.setattr(rt, "boss_has_valid_cookies", lambda: False)
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "完整描述", "requirements": "完整要求",
    })

    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "boss"}, {"company": "baidu"}], ensure_ascii=False),
        json.dumps({"role": "AI Agent 开发"}, ensure_ascii=False),
        boss_confirmed=True,
    ))
    assert calls == ["baidu"]
    assert "1 条真实岗位样本" in message
    assert "BOSS 直聘：未登录，已跳过" in message
    profile = profile_module.load_profile()
    assert profile.research["counts"]["jd_samples"] == 1


def test_gather_proceeds_when_boss_confirmed_and_logged_in(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    calls: list[str] = []

    def fake_loader(slug, **kwargs):
        calls.append(slug)
        return {"company": "BOSS直聘", "results": [_job()], "count": 1}

    monkeypatch.setattr(rt, "search_company_jobs", fake_loader)
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })
    monkeypatch.setattr(rt, "boss_has_valid_cookies", lambda: True)
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "负责 Agent 后端与 RAG 链路。",
        "requirements": "熟悉 Python / LangGraph。",
    })

    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "boss", "limit": 6}]),
        json.dumps({"role": "AI Agent 开发"}),
        direction="AI Agent 开发",
        boss_confirmed=True,
    ))
    assert calls == ["boss"], "确认 + 登录就绪后应真正抓取"
    assert "市场调研完成" in message
    assert (temp_profile / "CareerKit").exists()


def test_gather_without_boss_needs_no_confirmation(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.setattr(
        rt, "search_company_jobs",
        lambda slug, **kwargs: {"company": "字节跳动", "results": [_job()], "count": 1},
    )
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "负责 Agent 后端与 RAG 链路。",
        "requirements": "熟悉 Python / LangGraph。",
    })
    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "字节", "limit": 6}]),
        json.dumps({"role": "AI Agent 开发"}),
    ))
    assert "市场调研完成" in message


# ============ fetch_company_jobs BOSS 登录关卡 ============


def test_fetch_company_jobs_boss_login_surfaces_question(temp_profile, monkeypatch):
    import src.scrapers.boss.auth as boss_auth
    import src.tools.data_tools as data_tools

    monkeypatch.setattr(boss_auth, "has_valid_cookies", lambda: False)
    monkeypatch.setattr(data_tools, "search_company_jobs", _no_scrape)

    result = json.loads(asyncio.run(data_tools.fetch_company_jobs(company="boss")))
    assert result["isError"] is True
    assert result["code"] == "LOGIN_REQUIRED"
    assert "是否现在扫码登录" in result["details"]["question"]
    assert "src.scrapers.boss.login" in result["details"]["login_command"]
    assert "import_jd" in result["details"]["recovery"]
    assert "失败宣布" in result["details"]["rule"]


def test_fetch_company_jobs_non_boss_unaffected(temp_profile, monkeypatch):
    import src.tools.data_tools as data_tools

    monkeypatch.setattr(
        data_tools, "search_company_jobs",
        lambda slug, **kwargs: {"company": "字节跳动", "results": [_job()], "count": 1},
    )
    out = asyncio.run(data_tools.fetch_company_jobs(
        company="bytedance", params=json.dumps({"keyword": "Agent"}),
    ))
    assert "找到 1 个岗位" in out
