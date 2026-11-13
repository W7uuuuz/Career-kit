"""调研统计口径回归：源/条目分离、过滤留痕、重试、单一来源风险、全文落盘。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.tools.profile as profile_module
from src.research_digest import build_digest, render_digest_lines
from src.research_report import build_report


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _job(title="AI Agent 工程师", source="shixiseng"):
    return {
        "company": "某公司",
        "title": title,
        "location": "上海",
        "salary": "200-400/天",
        "summary": "负责 Agent 产品",
        "source": source,
        "url": f"https://example.com/job/{abs(hash(title))}",
        "description": "负责 Agent 产品与 RAG 链路",
        "requirements": "熟悉 Python",
    }


def _family(slug="tencent", label="腾讯", rows=None, status="ok", error=""):
    return {
        "slug": slug,
        "label": label,
        "rows": rows or [],
        "status": status,
        "error": error,
        "elapsed": 0.2,
        "dropped_no_detail": 0,
        "dropped_titles": [],
    }


def test_source_final_state_not_counted_twice(temp_profile):
    from src.tools.research_tools import _render_report_message

    profile = profile_module.load_profile()
    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "jd_families": [
            _family(rows=[], status="failed", error="单源超时"),
        ],
        "cases_result": {
            "cases": [],
            "warnings": [],
            "sources": {"tencent": 0},
        },
    })

    assert report["counts"]["source_fail"] == 1
    assert report["counts"]["source_empty"] == 0
    assert len(report["source_states"]) == 1
    assert report["source_states"][0]["status"] == "failed"

    message = _render_report_message(
        report, {"md": "m", "html": "h", "json": "j", "index": "i"}
    )
    assert "失败 1" in message
    assert "个源无结果" not in message, "同一来源不能同时被计为失败与无结果"


def test_filtered_samples_keep_title_and_reason(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    rows = [
        {"title": "AI-HR 培训生", "summary": "人力资源方向",
         "url": "https://example.com/hr"},
        {"title": "AI Agent 工程师", "summary": "负责 Agent 产品",
         "url": "https://example.com/agent"},
    ]
    monkeypatch.setattr(rt, "search_company_jobs", lambda slug, **kwargs: {
        "company": slug, "results": rows, "count": 2,
    })
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": "负责 Agent 产品", "requirements": "Python",
    })
    monkeypatch.setattr(rt, "_write_partial_cache", lambda *args, **kwargs: None)

    family = rt._fetch_family_sync(
        "tencent", "腾讯", {"keyword": "AI Agent"}, "cache-key", "fp"
    )
    assert family["filtered_irrelevant"] == 1
    assert family["filtered_samples"][0]["title"] == "AI-HR 培训生"
    assert "AI Agent" in family["filtered_samples"][0]["reason"]

    report = build_report(profile_module.load_profile(), {
        "direction": "AI Agent 开发",
        "jd_families": [family],
        "cases_result": {"cases": [], "warnings": [], "sources": {}},
    })
    gap = next(g for g in report["gaps"] if "方向不匹配" in g["missing"])
    assert "AI-HR 培训生" in gap["suggestion"]
    assert "AI-HR 培训生" in gap["reason"]


def test_single_source_failure_retries_once(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    calls = []

    def fake_fetch(slug, label, raw_spec, cache_key, fingerprint, policy=None):
        calls.append(slug)
        if len(calls) == 1:
            return {**_family(slug, label, [], "failed", "模拟失败"), "attempts": 1}
        return {**_family(slug, label, [_job(source=slug)], "ok"), "attempts": 1}

    monkeypatch.setattr(rt, "_fetch_family_sync", fake_fetch)
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })

    profile = profile_module.load_profile()
    gathered = asyncio.run(
        rt._run_research(
            profile, [{"company": "腾讯"}], {}, "", "", "", "fp-retry", {}
        )
    )
    family = gathered["jd_families"][0]
    assert calls == ["tencent", "tencent"]
    assert family["status"] == "ok"
    assert family["attempts"] == 2 and family["retried"] is True


def test_source_timeout_is_configurable(monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.delenv(rt._SOURCE_TIMEOUT_ENV, raising=False)
    assert rt._resolve_source_timeout() == rt._SOURCE_TIMEOUT
    monkeypatch.setenv(rt._SOURCE_TIMEOUT_ENV, "8")
    assert rt._resolve_source_timeout() == 8.0
    assert rt._resolve_source_timeout(3) == 3.0


def test_single_source_concentration_risk_and_real_alternatives(temp_profile):
    profile = profile_module.load_profile()
    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "jd_families": [
            _family("bytedance", "字节跳动", [], "failed", "单源超时"),
            _family("shixiseng", "实习僧", [_job() for _ in range(8)], "ok"),
        ],
        "cases_result": {"cases": [], "warnings": [], "sources": {}},
    })

    concentration = report["source_concentration"]
    assert concentration["risk"] == "high"
    assert concentration["top_source"] == "shixiseng"
    assert concentration["top_share"] == 1.0

    gap = next(g for g in report["gaps"] if "集中度" in g["missing"])
    assert "8/8" in gap["missing"]
    assert "重试失败源" in gap["suggestion"] and "字节跳动" in gap["suggestion"]
    assert "编造" not in gap["suggestion"]


def test_case_full_text_persisted_and_read_offline(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    case = {
        "kind": "success_experience",
        "title": "双非本上岸 AI 应用",
        "source": "nowcoder",
        "url": "https://www.nowcoder.com/discuss/1",
        "background": {"education_tag": "双非本"},
        "highlights": ["三轮面试"],
        "hit_terms": ["面经", "offer"],
    }
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [case], "warnings": [], "sources": {"nowcoder": 1},
    })
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "title": case["title"], "content": "完整面经正文：一面算法，二面项目。",
    })

    asyncio.run(rt.gather_research_data(
        "", json.dumps({"role": "AI Agent", "education": "双非本"})
    ))

    research = profile_module.load_profile().research
    stored = research["cases"][0]
    assert stored["content"] == "完整面经正文：一面算法，二面项目。"
    assert stored["content_status"] == "ok"

    def _no_network(*args, **kwargs):
        raise AssertionError("读取详情不应发起网络请求")

    monkeypatch.setattr(rt, "get_job_detail", _no_network)
    detail = json.loads(rt.read_research_details(ids=stored["id"], kind="case"))
    assert detail["items"][0]["content"] == stored["content"]
    assert detail["items"][0]["content_status"] == "ok"


def test_case_missing_full_text_is_marked(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    case = {
        "kind": "success_experience",
        "title": "暂无全文的面经",
        "source": "nowcoder",
        "url": "https://www.nowcoder.com/discuss/2",
        "background": {},
        "highlights": ["要点"],
        "hit_terms": ["面经"],
    }
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [case], "warnings": [], "sources": {"nowcoder": 1},
    })
    monkeypatch.setattr(
        rt, "get_job_detail", lambda url, company=None: {"error": "需要登录"}
    )

    asyncio.run(rt.gather_research_data(
        "", json.dumps({"role": "AI Agent", "education": "双非本"})
    ))

    stored = profile_module.load_profile().research["cases"][0]
    assert stored["content"] == ""
    assert stored["content_status"] == "unavailable"
    assert "登录" in stored["content_error"]


def test_hard_requirement_fields_extracted(temp_profile):
    profile = profile_module.load_profile()
    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "jd_families": [
            _family("shixiseng", "实习僧", [
                {
                    **_job("AI Agent 实习生（2026/2027届）"),
                    "degree": "硕士",
                    "weekly_days": 4,
                    "duration_months": 3,
                    "chance": "有转正机会",
                },
                {
                    **_job("2026届 AI 实习生"),
                    "degree": "",
                    "description": "2026届毕业生，硕士及以上学历",
                    "requirements": "每周到岗5天，实习期6个月",
                },
            ], "ok"),
        ],
        "cases_result": {"cases": [], "warnings": [], "sources": {}},
    })

    first, second = report["jd_samples"]
    assert first["degree"] == "硕士"
    assert first["graduation_years"] == [2026, 2027]
    assert first["weekly_days"] == 4
    assert first["duration_months"] == 3
    assert first["chance"] == "有转正机会"

    assert second["education_min"] == "硕士"
    assert second["weekly_days"] == 5
    assert second["duration_months"] == 6
    assert second["graduation_years"] == [2026]


def test_salary_digest_supports_daily_and_does_not_claim_missing():
    digest = build_digest([
        {"title": "实习 A", "salary": "200-400/天"},
        {"title": "实习 B", "salary": "250-400/天"},
        {"title": "正式 C", "salary": "20-30K"},
        {"title": "正式 D", "salary": "30-40万/年"},
    ], [])
    salary = digest["salary"]
    assert salary["daily_count"] == 2
    assert salary["monthly_count"] == 1
    assert salary["annual_count"] == 1
    assert salary["count"] == 4
    assert salary["with_salary"] == 4

    text = "\n".join(render_digest_lines(digest))
    assert "日薪" in text and "年薪" in text
    assert "均未公开薪资" not in text


