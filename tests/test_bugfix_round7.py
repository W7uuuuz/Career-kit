"""BUG.md 2026-11-04 复测清单回归（P0/P1/P2 关键项）。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import src.tools.profile as profile_module  # noqa: E402
from src.models import CareerProfile  # noqa: E402


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _job(company: str = "百度", title: str = "AI 工程师") -> dict:
    return {
        "company": company,
        "title": title,
        "location": "上海",
        "salary": "20-30K",
        "url": f"https://example.com/{title}",
        "description": "完整岗位描述",
        "requirements": "完整任职要求",
    }


def _roadmap(*phases: dict) -> dict:
    return {"roadmap": {"strategy_summary": "先补基础", "start_level": "小厂", "phases": list(phases)}}


def _phase(pid: str, name: str, task_names: list[str]) -> dict:
    return {
        "id": pid,
        "name": name,
        "type": "learn",
        "goal": "可执行",
        "milestones": [{
            "id": f"{pid}_ms_1",
            "name": "基础里程碑",
            "tasks": [{"name": n} for n in task_names],
        }],
    }


# ============ P0-1 断点续抓 ============


def test_gather_partial_cache_resumes_finished_source(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    calls: list[str] = []
    fail = {"baidu": False}

    def fake_search(slug, **kwargs):
        calls.append(slug)
        if slug == "tencent" and fail["baidu"]:
            return {"error": "模拟失败", "results": []}
        return {"company": slug, "count": 1, "results": [_job(title=f"AI Agent {slug} 岗")]}

    monkeypatch.setattr(rt, "search_company_jobs", fake_search)
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "完整描述", "requirements": "完整要求",
    })
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })

    specs = json.dumps([{"company": "baidu"}, {"company": "tencent"}])
    fail["baidu"] = True
    first = asyncio.run(rt.gather_research_data(specs, json.dumps({"role": "AI Agent"})))
    assert "市场调研完成" in first
    assert calls == ["baidu", "tencent"]

    calls.clear()
    fail["baidu"] = False
    second = asyncio.run(rt.gather_research_data(specs, json.dumps({"role": "AI Agent"})))
    assert "市场调研完成" in second
    assert calls == ["tencent"], "百度应从断点缓存复用，不重复抓取"


def test_gather_source_timeout_returns_partial(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.setattr(rt, "_SOURCE_TIMEOUT", 0.2)
    monkeypatch.setattr(rt, "_TOTAL_BUDGET", 5.0)
    monkeypatch.setattr(rt, "_PARTIAL_CACHE_TTL", 0)

    def fake_search(slug, **kwargs):
        if slug == "bytedance":
            time.sleep(0.6)
        return {"company": slug, "count": 1, "results": [_job(title=f"AI Agent {slug} 岗")]}

    monkeypatch.setattr(rt, "search_company_jobs", fake_search)
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "完整描述", "requirements": "完整要求",
    })
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })

    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "bytedance"}, {"company": "baidu"}]),
        json.dumps({"role": "AI Agent"}),
    ))
    assert "市场调研完成" in message
    assert "本次有来源未完成" in message
    assert "单源超时" in message


# ============ P1-1 案例计数口径 ============


def test_case_source_counts_match_roster(temp_profile):
    from src.research_report import build_report

    profile = profile_module.load_profile()
    report = build_report(profile, {
        "direction": "AI Agent",
        "jd_families": [],
        "cases_result": {
            "cases": [
                {"kind": "success_experience", "title": f"案例{i}", "source": "nowcoder",
                 "background": {"education_tag": "双非本"}, "highlights": [], "hit_terms": []}
                for i in range(5)
            ],
            "warnings": [],
            "sources": {"nowcoder": 6, "github": 1},
        },
    })
    counts = report["counts"]
    case_rows = [s for s in report["source_status"] if s["scope"] == "cases"]
    assert counts["cases"] == 5
    assert sum(s["count"] for s in case_rows) == 5
    by_source = {s["source"]: s for s in case_rows}
    assert by_source["案例·nowcoder"]["count"] == 5
    assert by_source["案例·github"]["count"] == 0


# ============ P1-2 / P1-3 流程衔接 ============


def test_finalize_profile_routes_to_research(temp_profile):
    from src.server import finalize_profile

    profile = CareerProfile()
    profile.who = {"name": "张三"}
    profile.have = {"skills": []}
    profile.want = {"target_role": "AI Agent", "city": "上海", "user_confirmed": True}
    profile.guidance = {"goal_confirmed_at": "2026-11-09T00:00:00"}
    profile_module.save_profile(profile)

    message = finalize_profile()
    assert "gather_research_data" in message
    assert "调用 analyze_gaps 开始差距分析" not in message


def test_workflow_status_lists_research_when_gap_exists(temp_profile):
    from src.server import get_workflow_status

    profile = CareerProfile()
    profile.who = {"name": "张三"}
    profile.have = {"skills": []}
    profile.want = {"target_role": "AI Agent"}
    profile.summary = "应届生"
    profile.research = {"report_md": "r.md", "report_html": "r.html", "counts": {}}
    profile.gap = {"match_score": 60}
    profile_module.save_profile(profile)

    out = get_workflow_status()
    assert "research_market" in out
    assert "gather_research_data" in out
    assert "analyze_gaps" in out


# ============ P1-4 / P2-11 任务与路线图 HTML ============


def test_generate_tasks_only_current_phase_and_refreshes_html(temp_profile):
    from src.assets import ROADMAP_FILENAME, kind_assets_dir
    from src.server import generate_tasks

    from conftest import promote_profile

    profile = CareerProfile()
    profile.plan = _roadmap(
        _phase("phase_1", "第一阶段", ["任务 A"]),
        _phase("phase_2", "第二阶段", ["任务 B"]),
    )
    promote_profile(profile, execution=True)

    generate_tasks()
    after = profile_module.load_profile()
    assert [t.phase_id for t in after.tasks] == ["phase_1"]
    assert after.tasks[0].name == "任务 A"

    roadmap_html = kind_assets_dir("roadmap", profile_module.get_active_profile_name()) / ROADMAP_FILENAME
    assert roadmap_html.exists()
    assert "任务 A" in roadmap_html.read_text(encoding="utf-8")

    after.tasks[0].status = "completed"
    profile_module.save_profile(after)
    generate_tasks()
    final = profile_module.load_profile()
    assert {t.phase_id for t in final.tasks} == {"phase_1", "phase_2"}
    assert any(t.name == "任务 B" for t in final.tasks)


# ============ P2-2 / P2-8 质量建议 ============


def test_advisory_does_not_duplicate_milestone_name(temp_profile):
    from src.tools.roadmap import parse_roadmap
    from src.tools.roadmap_tools import _collect_roadmap_advisories

    profile = CareerProfile()
    parsed = parse_roadmap(json.dumps(_roadmap({
        "id": "phase_1", "name": "秋招冲刺", "type": "project",
        "milestones": [{"name": "场景设计专题", "tasks": []}],
    }), ensure_ascii=False))
    advisories = _collect_roadmap_advisories(parsed, profile)
    message = " ".join(a["message"] for a in advisories)
    assert "「场景设计专题」「场景设计专题」" not in message
    assert "里程碑「场景设计专题」" in message


def test_start_level_after_no_false_positive_with_gate_and_condition(temp_profile):
    from src.tools.roadmap import parse_roadmap
    from src.tools.roadmap_tools import _collect_roadmap_advisories

    profile = CareerProfile()
    parsed = parse_roadmap(json.dumps(_roadmap({
        "id": "phase_1", "name": "暑期实习", "type": "intern",
        "start_level_after": "中厂",
        "evidence_gate": ["完成 2 个项目", "通过模拟面试"],
        "condition": "冲刺大厂；保底中厂；无则转日常实习",
        "milestones": [{"name": "投递", "tasks": []}],
    }), ensure_ascii=False))
    advisories = _collect_roadmap_advisories(parsed, profile)
    assert not any(a["code"] == "start_level_after" for a in advisories)


# ============ P2-3 / P2-5 ============


def test_research_filename_always_has_time(tmp_path, monkeypatch):
    import src.assets as assets

    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    stem = assets.next_asset_stem(
        "AI Agent", kind="research", profile_name="默认档案",
        now=datetime(2026, 11, 4, 18, 7),
    )
    assert stem.startswith("2026-11-04_1807_")


def test_boss_job_missing_company_uses_placeholder():
    from src.scrapers.boss.scraper import _map_job

    row = _map_job({"jobName": "Agent 开发", "encryptJobId": "x"})
    assert row["company"] == "公司名未获取"


# ============ P2-7 审计过期提示 ============


def test_stale_audit_prompts_reaudit_not_contradictory(temp_profile):
    from src.server import save_roadmap, save_roadmap_audit

    from conftest import promote_profile

    profile = CareerProfile()
    profile.want = {"target_role": "AI Agent", "user_confirmed": True}
    profile.gap = {"start_level": "小厂", "match_score": 60}
    profile_module.save_profile(profile)
    promote_profile(profile)

    base = _roadmap(_phase("phase_1", "基础", ["任务 A"]))
    save_roadmap(json.dumps(base, ensure_ascii=False))
    save_roadmap_audit(json.dumps({
        "verdict": "PASS_WITH_NOTES",
        "issues": [],
        "notes": ["补充项目说明"],
    }, ensure_ascii=False))

    changed = _roadmap(_phase("phase_1", "基础", ["任务 A", "任务 B"]))
    result = json.loads(save_roadmap(json.dumps(changed, ensure_ascii=False)))
    assert "绑定的是修改前的旧版本" in result["message"]
    assert "重新交给 career-roadmap-auditor" in result["message"]
    assert "通过，但有建议（已过期" not in result["message"]
