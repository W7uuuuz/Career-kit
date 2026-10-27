"""行业快照与扫盲入口回归。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.industry_snapshot as snapshot_module
import src.tools.profile as profile_module


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    return tmp_path


def _call(**kwargs) -> dict:
    from src.server import get_industry_snapshot

    return json.loads(asyncio.run(get_industry_snapshot(**kwargs)))


def test_industry_loader_accepts_name_alias_and_related_major():
    from src.industries.loader import get_industry, match_major

    pack = get_industry("计算机")
    assert pack["id"] == "internet"
    assert "软件工程" in pack["related_majors"]["core"]
    info = match_major(pack, "软件工程")
    assert info["match"] == "core"
    assert info["label"] == "核心相关"


def test_industry_snapshot_with_market_samples(temp_profile, monkeypatch):
    jobs = [
        {
            "title": "后端开发工程师",
            "company": "A 公司",
            "location": "杭州",
            "salary": "20-30K",
            "url": "https://example.com/job/1",
            "_role_id": "backend",
            "_role_name": "后端开发",
        },
        {
            "title": "Java 后端",
            "company": "B 公司",
            "location": "上海",
            "salary": "25-35K",
            "url": "https://example.com/job/2",
            "_role_id": "backend",
            "_role_name": "后端开发",
        },
    ]
    monkeypatch.setattr(snapshot_module, "_collect_market", lambda *args, **kwargs: (jobs, []))

    data = _call(industry="互联网", major="计算机科学与技术", city="杭州")

    assert data["industry"]["id"] == "internet"
    assert data["major_match"]["label"] == "核心相关"
    assert data["market"]["job_count"] == 2
    assert data["market"]["salary"]["count"] == 2
    assert data["market"]["salary"]["median_k"] == 27.5
    backend = next(r for r in data["roles"] if r["id"] == "backend")
    assert backend["market"]["sample_count"] == 2
    assert backend["market"]["sample_urls"]

    profile = profile_module.load_profile()
    assert profile.want["industry_id"] == "internet"
    assert profile.want["scan_consent"] is True
    assert profile.want["scan_completed_at"]
    assert profile.want["scan_summary"]
    assert "industry" not in profile.want, "扫盲不能提前把行业当成目标"
    assert profile.who["major"] == "计算机科学与技术"


def test_industry_snapshot_without_market_is_honest(temp_profile, monkeypatch):
    monkeypatch.setattr(
        snapshot_module,
        "_collect_market",
        lambda *args, **kwargs: ([], ["BOSS 直聘未登录：本次未获取实时招聘薪资；登录后可重试。"]),
    )
    data = _call(industry="internet")
    assert data["market"]["job_count"] == 0
    assert data["market"]["salary"]["count"] == 0
    assert any("未获取" in gap for gap in data["gaps"])
    assert any("未获取" in line for line in data["summary"])


def test_industry_snapshot_rejects_unsupported_industry():
    data = _call(industry="医疗")
    assert data["isError"] is True
    assert data["code"] == "INDUSTRY_NOT_SUPPORTED"
    assert data["details"]["available"]


def test_scan_continue_does_not_repeat_scan(temp_profile):
    from src.server import start_session
    from src.tools.profile import save_profile

    profile = profile_module.load_profile()
    profile.want = {
        "industry_id": "internet",
        "scan_consent": True,
        "scan_completed_at": "2026-10-27T00:00:00",
        "scan_summary": ["互联网/软件行业：常见方向包括后端开发。"],
    }
    save_profile(profile)

    out = start_session()
    assert "扫盲继续模式" in out
    assert "当前档案" in out
    assert "get_industry_snapshot" not in out

def test_industry_change_marks_old_analysis_stale(temp_profile):
    from src.server import intake
    from src.tools.profile import save_profile

    profile = profile_module.load_profile()
    profile.want = {"industry_id": "internet", "target_role": "后端开发"}
    profile.gap = {"match_score": 60}
    save_profile(profile)

    result = intake(section="want", data='{"industry_id": "finance"}')
    assert "行业已变更" in result
    updated = profile_module.load_profile()
    assert updated.gap_stale_at

def test_onboarding_prompts_registered():
    from src.server import mcp

    names = {p.name for p in mcp._prompt_manager.list_prompts()}
    assert {"career-onboarding", "career-quick-scan", "career-grounding"} <= names

def test_energy_industry_loader_and_major_alias():
    from src.industries.loader import get_industry, match_major

    pack = get_industry("能动")
    assert pack["id"] == "energy"
    assert "能源与动力工程" in pack["related_majors"]["core"]
    info = match_major(pack, "能动")
    assert info["match"] == "core"
    assert info["canonical"] == "能源与动力工程"


def test_energy_snapshot_uses_energy_pack(temp_profile, monkeypatch):
    jobs = [
        {
            "title": "电厂集控运行",
            "company": "某发电集团",
            "location": "宁波",
            "salary": "10-15K",
            "url": "https://example.com/energy/1",
            "_role_id": "power_plant",
            "_role_name": "电厂运行/运维",
        }
    ]
    monkeypatch.setattr(snapshot_module, "_collect_market", lambda *args, **kwargs: (jobs, []))

    data = _call(industry="能源动力", major="能源与动力工程", city="宁波")
    assert data["industry"]["id"] == "energy"
    assert any(r["id"] == "power_plant" for r in data["roles"])
    assert data["market"]["job_count"] == 1
    assert any(b["value"] == 7199 for b in data["benchmarks"])
