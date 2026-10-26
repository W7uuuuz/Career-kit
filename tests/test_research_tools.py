"""市场调研工具（research_market / gather_research_data）契约测试。

锁定调研阶段的核心纪律：
- 报告三件套（md/html/json）落盘到用户资产目录并刷新 index
- profile.research 写入供差距分析引用
- 失败源如实记录（绝不静默吞掉），全部失败时中止且不编造
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import pytest
import src.assets as assets
import src.tools.profile as profile_module
from src.research_report import save_report


@pytest.fixture()
def temp_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_module, "PROFILE_DIR", tmp_path)
    monkeypatch.setenv("CAREER_KIT_ASSETS_DIR", str(tmp_path / "CareerKit"))
    return tmp_path


def _job(company="字节跳动", title="AI Agent 工程师", salary="30-50K·16薪"):
    return {
        "company": company,
        "title": title,
        "location": "北京",
        "salary": salary,
        "summary": "负责 Agent 产品后端与 RAG 链路",
        "source": "BOSS直聘",
        "url": "https://example.com/job/1",
    }


def _case():
    return {
        "kind": "experience",
        "title": "双非本上岸字节 AI 应用",
        "background": {
            "education_tag": "双非本",
            "year": "2025",
            "company": "字节跳动",
            "position": "AI 应用工程师",
        },
        "highlights": ["三个月项目迭代", "投 40 家过 3 家"],
        "salary": "",
        "location": "北京",
        "source": "牛客",
        "url": "https://example.com/post/1",
        "date": "2025-09",
        "match_score": 85,
    }


class _FakeLoader:
    """按 slug 返回预设响应的假 search_company_jobs。"""

    def __init__(self, mapping):
        self.calls: list[tuple[str, dict]] = []
        self.mapping = mapping

    def __call__(self, slug, **kwargs):
        self.calls.append((slug, kwargs))
        result = self.mapping.get(slug)
        if isinstance(result, Exception):
            raise result
        return result


def test_research_market_returns_methodology_and_prior(temp_profile):
    from src.server import research_market

    out = json.loads(research_market())
    assert not out.get("isError")
    assert out["methodology"]["name"] == "市场调研"
    steps = out["step_template"]
    assert [s["name"] for s in steps] == ["范围宣告", "批量抓取", "报告落地", "衔接分析"]
    assert [s["checkpoint"] for s in steps] == [False, False, False, True]
    assert out["prior_research"] is None  # 全新档案无调研
    assert "vendor" not in json.dumps(out)  # 无编造占位


def test_gather_research_data_writes_report_trio(temp_profile):

    loader = _FakeLoader({
        "bytedance": {"company": "bytedance", "results": [_job()], "count": 1},
        "boss": {"company": "boss", "results": [
            _job(company="某对照公司", title="Agent 平台后端", salary="25-45K")
        ], "count": 1},
    })

    import src.tools.research_tools as rt

    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [_case()], "warnings": [], "sources": {}}
    try:
        message = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节", "limit": 6}, {"company": "boss", "limit": 6}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            direction="AI Agent 开发",
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases

    # 播报三要素齐备：数字样本 → 路径 → 下一步
    assert "2 条真实岗位样本" in message and "1 条同学历经历" in message
    assert "失败来源" not in message  # 两个源都成功
    assert "index.html" in message
    assert "现状盘点" in message and "读取调研" in message

    root = assets.get_assets_root()
    index_html = (root / "index.html").read_text(encoding="utf-8")
    assert "AI Agent 开发" in index_html  # 卡片进入资产中心

    report_dir = root / "默认档案" / "调研报告"
    files = sorted(p.name for p in report_dir.iterdir()) if report_dir.is_dir() else []
    assert any(n.endswith(".html") for n in files)
    assert any(n.endswith(".md") for n in files)
    assert any(n.endswith(".json") for n in files)

    # 档案 research 契约：供差距分析直接引用
    profile = profile_module.load_profile()
    research = profile.research
    assert research and research["counts"]["jd_samples"] == 2
    assert research["counts"]["cases"] == 1
    assert research["jd_samples"][0]["salary"] == "30-50K·16薪"
    assert research["source_status"], "来源状态必须记录"
    assert Path(research["report_md"]).exists()

    # HTML 阅读版包含来源与数据缺口节
    html = Path(research["report_html"]).read_text(encoding="utf-8")
    assert "来源状态" in html and "数据缺口" in html
    assert "example.com/job/1" in html  # 每条带可验证链接


def test_gather_research_data_tolerates_failed_source(temp_profile):

    loader = _FakeLoader({
        "bytedance": {"company": "bytedance", "results": [_job()], "count": 1},
        "tencent": {"error": "登录已过期", "results": [], "available": False},
    })

    import src.tools.research_tools as rt

    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [_case()], "warnings": [], "sources": {}}
    try:
        message = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节", "limit": 6}, {"company": "腾讯", "limit": 6}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases

    assert "1 个源失败" in message
    assert "登录已过期" in message  # 失败原因原样展示
    assert "未获取到" not in message or "失败" in message  # 语义来自真实状态不吃掉

    profile = profile_module.load_profile()
    statuses = {s["source"]: s["status"] for s in profile.research["source_status"]}
    assert any(v == "failed" for v in statuses.values())
    # 缺口自动生成且如实陈述
    assert profile.research["gaps"], "失败源会产生数据缺口条目"


def test_gather_research_data_rejects_when_all_failed(temp_profile):

    loader = _FakeLoader({
        "bytedance": {"error": "网络不可达", "results": []},
        "boss": RuntimeError("连不上"),
    })

    import src.tools.research_tools as rt

    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [], "warnings": ["全部失败"], "sources": {}}
    try:
        result = json.loads(asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节"}, {"company": "boss"}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
        )))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases

    assert result["isError"] is True
    assert result["code"] == "MISSING_DATA"
    assert "未编造" in result["message"] or "如实" in result["message"]
    # 不落盘、不占档案
    root = assets.get_assets_root()
    assert not (root / "默认档案" / "调研报告").exists()
    profile = profile_module.load_profile()
    assert not (profile.research or {}).get("report_md")


def test_gather_research_data_requires_scope(temp_profile):
    from src.server import gather_research_data

    result = json.loads(asyncio.run(gather_research_data("", "")))
    assert result["isError"] is True
    assert result["code"] == "MISSING_DATA"
    assert "example" in result["details"]


def test_save_report_dated_files_and_research_contract(temp_profile):
    """save_report：日期_方向留档 + profile.research 契约（多次生成各自留档）。"""
    profile = profile_module.load_profile()
    profile.want = {"target_role": "AI Agent 工程师"}
    profile_module.save_profile(profile)

    report = {
        "type": "research_report",
        "direction": "AI Agent 工程师",
        "city": "北京",
        "education_tag": "双非本",
        "generated_at": "2026-10-26 20:00",
        "context": {"goal": "AI Agent 工程师", "city": "北京",
                    "education": "双非本", "resume_trust": "medium"},
        "jd_samples": [{**_job(), "fetched_at": "2026-10-26 20:00"}],
        "cases": [_case()],
        "source_status": [{"source": "BOSS", "status": "ok", "count": 1,
                           "elapsed": 0.4, "error": ""}],
        "case_warnings": [],
        "gaps": [],
        "counts": {"jd_samples": 1, "cases": 1, "source_ok": 1,
                   "source_fail": 0, "source_empty": 0},
    }
    paths = save_report(profile, report)
    assert Path(paths["md"]).exists() and Path(paths["html"]).exists()
    assert Path(paths["json"]).exists() and Path(paths["index"]).exists()
    assert "2026-10-26_AI Agent 工程师" in paths["md"]  # 日期_方向留档

    profile2 = profile_module.load_profile()
    assert profile2.research["counts"]["jd_samples"] == 1
    assert "调研报告" in profile2.research["report_md"]

    # 二次生成是新文件，旧的不丢
    report["generated_at"] = "2026-10-26 20:05"
    paths2 = save_report(profile2, report)
    assert paths2["md"] != paths["md"]
