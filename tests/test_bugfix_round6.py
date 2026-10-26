"""BUG 修复第五轮（dev/test/BUG.md 2026-10-27 复测清单）。

- BUG-1 调研报告截断叠加 → 详情必抓、报告/json 保原文、md 完整区、HTML 可展开
- BUG-2 本地 JSON 被当正文渲染 + 本地 JD 与 JD 表重复
- BUG-3 explore_goals 技能名 None（改用多键名回退）
- BUG-4 成功经验/面试要求分类偏移
- BUG-5 字节城市过滤失效（接口参数不生效 → 后置过滤）
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


def _long_text(length: int = 300) -> str:
    return "负责 Agent 产品后端与 RAG 链路，" * (length // 16 + 1)


# ============ BUG-5 字节城市后置过滤 ============


def test_bytedance_city_post_filter():
    from src.scrapers.bytedance.scraper import Scraper

    rows = [
        {"title": "上海岗", "location": "上海", "url": "u1"},
        {"title": "北京岗", "location": "北京", "url": "u2"},
        {"title": "多城市岗", "location": "北京、上海、杭州", "url": "u3"},
        {"title": "未知地点", "location": "", "url": "u4"},
    ]
    kept = Scraper._city_post_filter("上海", rows)
    assert [r["url"] for r in kept] == ["u1", "u3"], "多城市命中保留，地点缺失无法核实则剔除"
    assert Scraper._city_post_filter("", rows) == rows
    assert Scraper._city_post_filter("广州", rows) == []


def test_bytedance_search_url_uses_supported_params():
    """实测：社招页只识别 keywords / location；旧参数 keyword 被忽略导致搜什么都一样。"""
    from src.scrapers.bytedance.scraper import Scraper

    experienced = Scraper._build_search_url("AI Agent", "上海", "", "experienced")
    assert "keywords=AI%20Agent" in experienced
    assert "location=CT_125" in experienced
    assert "location_code_list" not in experienced
    assert "&keyword=" not in experienced

    campus = Scraper._build_search_url("Agent", "上海", "", "campus")
    assert "keywords=Agent" in campus and "location=CT_125" in campus


# ============ BUG-3 explore_goals 技能名 ============


def test_explore_goals_summary_uses_skill_names(temp_profile):
    from src.server import explore_goals, intake

    intake("who", '{"name": "张三", "status": "应届生"}')
    intake("have", json.dumps({
        "skills": [
            {"name": "Python", "evidence": "课程项目"},
            {"title": "LangGraph", "evidence": "个人项目"},
            "React",
        ],
    }, ensure_ascii=False))

    out = json.loads(explore_goals())
    summary = out["user_summary"]
    assert "None" not in summary, summary
    assert "Python" in summary and "LangGraph" in summary and "React" in summary


# ============ BUG-2 本地 JSON 可读摘要 + 去重 ============


def test_local_json_row_extracts_readable_fields(tmp_path, monkeypatch):
    import src.case_search as cs

    knowledge = tmp_path / "knowledge"
    jd_dir = knowledge / "jds" / "bytedance"
    jd_dir.mkdir(parents=True)
    payload = {
        "title": "AI Agent 开发工程师",
        "url": "https://jobs.bytedance.com/campus/position/1/detail",
        "company": "字节跳动",
        "location": "上海",
        "summary": "负责 Agent 平台与评测体系",
        "salary": "",
    }
    (jd_dir / "agent.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )
    monkeypatch.setattr(cs, "KNOWLEDGE_DIR", knowledge)

    item = cs._local_row_to_item({
        "source": "jds/bytedance/agent.json",
        "content": json.dumps(payload, ensure_ascii=False),
    })
    assert not item["snippet"].lstrip().startswith("{"), "不能把原始 JSON 当正文"
    assert "字节跳动" in item["snippet"] and "上海" in item["snippet"]
    assert "Agent 平台" in item["snippet"]
    assert item["company"] == "字节跳动"
    assert item["location"] == "上海"
    assert item["origin"] == "local_jd"


def test_report_dedupes_local_jd_against_jd_samples(temp_profile):
    from src.research_report import build_report

    profile = profile_module.load_profile()
    url = "https://jobs.bytedance.com/campus/position/1/detail"
    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "city": "上海",
        "education_tag": "双非本",
        "jd_families": [{
            "slug": "bytedance", "label": "字节跳动", "status": "ok", "error": "",
            "elapsed": 0.3, "dropped_no_detail": 0,
            "rows": [{
                "title": "AI Agent 开发工程师", "company": "字节跳动",
                "location": "上海", "url": url,
                "description": "负责 Agent 平台与评测体系", "requirements": "熟悉 Python",
            }],
        }],
        "cases_result": {
            "cases": [
                {"kind": "interview_requirements", "title": "AI Agent 开发工程师",
                 "origin": "local_jd", "url": url, "source": "local",
                 "background": {"company": "字节跳动"}, "highlights": ["负责 Agent 平台"]},
                {"kind": "success_experience", "title": "双非本 秋招上岸复盘",
                 "origin": "local", "url": "https://example.com/p/2", "source": "nowcoder",
                 "background": {"education_tag": "双非本"}, "highlights": ["投了 40 家"]},
            ],
            "warnings": [], "sources": {"nowcoder": 1},
        },
    })
    assert [c["title"] for c in report["cases"]] == ["双非本 秋招上岸复盘"]


# ============ BUG-4 分类规则 ============


def test_case_kind_classification():
    from src.case_search import _classify_kind

    assert _classify_kind(
        "双非学院本第一次面试拿到 offer", "一面二面都聊了项目"
    ) == "success_experience"
    assert _classify_kind("字节 AI Agent 一面面经", "问了 RAG 与工具调用") == "interview_requirements"
    assert _classify_kind("岗位描述", "岗位职责：负责 Agent 平台；任职要求：Python") == "interview_requirements"
    assert _classify_kind("我的 27 届秋招上岸记录", "投了 60 家，最终入职") == "success_experience"


# ============ BUG-1 详情必抓 + 不二次截断 ============


def test_enrich_with_detail_drops_rows_without_detail(monkeypatch):
    import src.tools.research_tools as rt

    def fake_detail(url, company=None):
        if url.endswith("/ok"):
            return {"description": "完整岗位描述", "requirements": "完整任职要求"}
        return {"error": "详情接口不可用"}

    monkeypatch.setattr(rt, "get_job_detail", fake_detail)
    rows = [
        {"title": "有详情", "url": "https://x/ok"},
        {"title": "没详情", "url": "https://x/bad"},
    ]
    kept, dropped = rt._enrich_with_detail("boss", rows)
    assert [r["title"] for r in kept] == ["有详情"]
    assert kept[0]["description"] == "完整岗位描述"
    assert kept[0]["detail_status"] == "ok"
    assert dropped == ["没详情"]


def test_report_keeps_full_text_and_renders_expandable(temp_profile):
    from src.research_report import build_report, render_html, render_markdown

    profile = profile_module.load_profile()
    description = _long_text(300)
    requirements = "熟悉 Python / LangGraph / RAG；" * 12
    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "city": "上海",
        "education_tag": "双非本",
        "jd_families": [{
            "slug": "baidu", "label": "百度", "status": "ok",
            "error": "", "elapsed": 0.2, "dropped_no_detail": 0,
            "rows": [{
                "title": "AI Agent 工程师", "company": "百度", "location": "上海",
                "url": "https://example.com/j/1",
                "summary": description[:120],
                "description": description,
                "requirements": requirements,
            }],
        }],
        "cases_result": {"cases": [], "warnings": [], "sources": {}},
    })
    sample = report["jd_samples"][0]
    assert sample["description"] == description, "json/报告结构不得二次截断"
    assert sample["requirements"] == requirements

    md = render_markdown(report)
    assert "岗位详情（完整 JD" in md
    assert description[:80] in md
    assert "**任职要求**" in md

    html = render_html(report)
    assert "<details" in html and "岗位描述" in html
    assert description in html


def test_gather_surfaces_dropped_no_detail(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    monkeypatch.setattr(rt, "search_company_jobs", lambda slug, **kwargs: {
        "company": slug, "count": 2,
        "results": [
            {"title": "有详情岗位", "url": "https://x/ok", "company": "百度"},
            {"title": "无详情岗位", "url": "https://x/bad", "company": "百度"},
        ],
    })
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [], "warnings": [], "sources": {},
    })
    monkeypatch.setattr(
        rt, "get_job_detail",
        lambda url, company=None: (
            {"description": "完整描述", "requirements": "完整要求"}
            if url.endswith("/ok") else {"error": "详情接口不可用"}
        ),
    )

    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "百度"}]),
        json.dumps({"role": "AI Agent 开发"}),
    ))
    assert "1 条真实岗位样本" in message
    assert "1 条岗位因未获取到详情被剔除" in message
    profile = profile_module.load_profile()
    assert profile.research["counts"]["dropped_no_detail"] == 1
    assert any("未获取到详情" in g["missing"] for g in profile.research["gaps"])


# ============ 花名册 / 按需读取（控制上下文体积） ============


def _gather_two_jobs(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    long_description = _long_text(240)
    monkeypatch.setattr(rt, "search_company_jobs", lambda slug, **kwargs: {
        "company": slug, "count": 2,
        "results": [
            {"title": "岗位甲", "url": "https://x/1", "company": "百度",
             "location": "上海", "salary": "20-30K"},
            {"title": "岗位乙", "url": "https://x/2", "company": "百度",
             "location": "北京", "salary": "25-40K"},
        ],
    })
    monkeypatch.setattr(rt, "collect_cases", lambda **kwargs: {
        "cases": [{
            "kind": "success_experience", "title": "双非本秋招上岸复盘",
            "source": "nowcoder", "url": "https://nc/1",
            "background": {"education_tag": "双非本", "year": "2025"},
            "highlights": ["投递 40 家，拿到 3 个 offer"],
            "hit_terms": ["秋招", "offer"],
        }],
        "warnings": [], "sources": {"nowcoder": 1},
    })
    monkeypatch.setattr(rt, "get_job_detail", lambda url, company=None: {
        "description": long_description,
        "requirements": "熟悉 Python / LangGraph / RAG。",
    })
    message = asyncio.run(rt.gather_research_data(
        json.dumps([{"company": "百度"}]),
        json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
    ))
    return message, long_description


def test_gather_returns_roster_not_full_text(temp_profile, monkeypatch):
    message, long_description = _gather_two_jobs(temp_profile, monkeypatch)
    assert "#JD01" in message and "#JD02" in message
    assert "#CS01" in message
    assert "全文按需读取" in message
    assert "聚合洞察" in message
    assert long_description not in message, "岗位全文不得进入上下文"
    assert "read_research_details" in message
    assert "子 Agent" in message
    assert "research-analyst" in message
    assert "harness" in message


def test_delegate_plan_batches_and_output_schema():
    from src.tools.research_tools import _delegate_plan

    plan = _delegate_plan("jd", [f"JD{i:02d}" for i in range(1, 13)])
    assert plan["subagent"] == "research-analyst"
    assert plan["id_batches"] == [
        [f"JD{i:02d}" for i in range(1, 11)],
        ["JD11", "JD12"],
    ]
    assert "read_research_details" in plan["prompt"]
    assert "evidence_ids" in plan["prompt"]
    assert set(plan["output_schema"]) == {"conclusions", "shortlist", "gaps"}
    assert "harness" in plan["mechanism"]
    assert 'subagent_type="research-analyst"' in plan["invoke_example"]


def test_research_analyst_agent_definitions_exist():
    """两份 harness 定义必须同步存在，否则委派指令无法真正执行。"""
    repo = Path(__file__).parent.parent
    opencode = repo / ".opencode" / "agent" / "research-analyst.md"
    claude = repo / ".claude" / "agents" / "research-analyst.md"
    for path in (opencode, claude):
        assert path.exists(), f"缺少子 Agent 定义：{path}"
        text = path.read_text(encoding="utf-8")
        assert "read_research_details" in text
        assert "conclusions" in text and "shortlist" in text and "gaps" in text
        assert "3-5" in text


def test_read_research_details_roster_and_selection(temp_profile, monkeypatch):
    from src.server import read_research_details

    _gather_two_jobs(temp_profile, monkeypatch)

    roster = json.loads(read_research_details())
    assert roster["kind"] == "jd" and roster["count"] == 2
    assert [item["id"] for item in roster["items"]] == ["JD01", "JD02"]
    assert all(item["brief"] for item in roster["items"])
    assert roster["digest"]["jd_count"] == 2
    delegate = roster["delegate"]
    assert delegate["subagent"] == "research-analyst"
    assert "read_research_details" in delegate["prompt"]
    assert delegate["id_batches"] == [["JD01", "JD02"]]

    detail = json.loads(read_research_details(ids="JD01"))
    item = detail["items"][0]
    assert item["id"] == "JD01"
    assert item["description"] and item["requirements"]
    assert detail["count"] == 1

    case_detail = json.loads(read_research_details(ids=["CS01"], kind="case"))
    case_item = case_detail["items"][0]
    assert case_item["title"] == "双非本秋招上岸复盘"
    assert case_item["hit_terms"]


def test_read_research_details_validation(temp_profile, monkeypatch):
    from src.server import read_research_details

    missing = json.loads(read_research_details())
    assert missing["code"] == "MISSING_DATA"

    _gather_two_jobs(temp_profile, monkeypatch)
    bad = json.loads(read_research_details(ids="JD99"))
    assert bad["code"] == "INVALID_PARAM"
    assert "JD01" in bad["message"]

    bad_kind = json.loads(read_research_details(kind="unknown"))
    assert bad_kind["code"] == "INVALID_PARAM"
