"""市场调研工具（research_market / gather_research_data）契约测试。

锁定调研阶段的核心纪律：
- 报告三件套（md/html/json）落盘到用户资产目录并刷新 index
- profile.research 写入供差距分析引用
- 失败源如实记录（绝不静默吞掉），全部失败时中止且不编造
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from datetime import datetime
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


def _source_job(slug):
    return {
        "company": slug,
        "title": f"{slug} Agent 工程师",
        "location": "北京",
        "salary": "20-40K",
        "summary": "负责 AI Agent 产品后端",
        "source": slug,
        "url": f"https://example.com/job/{slug}",
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
            _job(company="某对照公司", title="AI Agent 平台后端", salary="25-45K")
        ], "count": 1},
    })

    import src.tools.research_tools as rt

    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    original_detail = rt.get_job_detail
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [_case()], "warnings": [], "sources": {}}
    rt.get_job_detail = lambda url, company=None: {
        "title": "AI Agent 工程师",
        "description": "负责 Agent 产品后端与 RAG 链路，构建评测集，"
                       "与算法团队协作上线（完整 JD 正文，不截断）。",
        "requirements": "熟悉 Python / LangGraph / RAG；有线上项目经验；"
                        "能独立定位性能瓶颈并给出优化方案。",
    }
    original_boss_auth = rt.boss_has_valid_cookies
    rt.boss_has_valid_cookies = lambda: True
    try:
        message = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节", "limit": 6}, {"company": "boss", "limit": 6}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            direction="AI Agent 开发",
            boss_confirmed=True,
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.get_job_detail = original_detail
        rt.boss_has_valid_cookies = original_boss_auth

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
    assert research["jd_samples"][0]["description"], "详情必须落进报告与 json"
    assert research["jd_samples"][0]["requirements"]
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
    original_detail = rt.get_job_detail
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [_case()], "warnings": [], "sources": {}}
    rt.get_job_detail = lambda url, company=None: {
        "description": "负责 Agent 产品后端与 RAG 链路。",
        "requirements": "熟悉 Python / LangGraph。",
    }
    try:
        message = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节", "limit": 6}, {"company": "腾讯", "limit": 6}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.get_job_detail = original_detail

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
    original_boss_auth = rt.boss_has_valid_cookies
    rt.boss_has_valid_cookies = lambda: True
    try:
        result = json.loads(asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节"}, {"company": "boss"}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            boss_confirmed=True,
        )))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.boss_has_valid_cookies = original_boss_auth

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
    assert re.search(r"\d{4}-\d{2}-\d{2}_\d{4}_AI Agent 工程师", paths["md"]), "日期_时分_方向留档"

    profile2 = profile_module.load_profile()
    assert profile2.research["counts"]["jd_samples"] == 1
    assert "调研报告" in profile2.research["report_md"]

    # 二次生成是新文件，旧的不丢
    report["generated_at"] = "2026-10-26 20:05"
    paths2 = save_report(profile2, report)
    assert paths2["md"] != paths["md"]


def _gather_message(specs, query=None):
    import src.tools.research_tools as rt

    slugs = [rt.resolve_company(str(spec["company"])) for spec in specs]
    loader = _FakeLoader(
        {slug: {"company": slug, "results": [_source_job(slug)], "count": 1} for slug in slugs}
    )
    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    original_detail = rt.get_job_detail
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [], "warnings": [], "sources": {}}
    rt.get_job_detail = lambda url, company=None: {
        "description": "岗位正文",
        "requirements": "Python",
    }
    try:
        return asyncio.run(
            rt.gather_research_data(json.dumps(specs), json.dumps(query or {}))
        )
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.get_job_detail = original_detail


def test_research_budget_constants():
    import src.tools.research_tools as rt

    assert rt._SOURCE_TIMEOUT == 25.0
    assert rt._CASE_TIMEOUT == 30.0
    assert rt._TOTAL_BUDGET == 50.0
    assert rt._MAX_SOURCE_CONCURRENCY == 4


def test_one_or_two_sources_do_not_suggest_batching(temp_profile):
    one = _gather_message([{"company": "字节", "limit": 3}])
    two = _gather_message(
        [{"company": "字节", "limit": 3}, {"company": "腾讯", "limit": 3}]
    )
    assert "拆批" not in one
    assert "拆批" not in two


def test_three_sources_or_two_sources_with_case_suggest_batching(temp_profile):
    three = _gather_message(
        [
            {"company": "字节", "limit": 3},
            {"company": "腾讯", "limit": 3},
            {"company": "百度", "limit": 3},
        ]
    )
    assert "拆批" in three and "3 个" in three

    mixed = _gather_message(
        [{"company": "字节", "limit": 3}, {"company": "腾讯", "limit": 3}],
        {"role": "AI Agent 开发"},
    )
    assert "拆批" in mixed and "3 个" in mixed


def test_four_sources_report_count_and_batching(temp_profile):
    four = _gather_message(
        [
            {"company": "字节", "limit": 3},
            {"company": "腾讯", "limit": 3},
            {"company": "百度", "limit": 3},
            {"company": "阿里", "limit": 3},
        ]
    )
    assert "4 个" in four
    assert "拆批" in four


def test_filter_relevant_rows_drops_off_topic_titles():
    import src.tools.research_tools as rt

    rows = [
        {"title": "AI-HR 培训生", "summary": "人力资源方向", "url": "https://example.com/hr"},
        {"title": "AI Agent 工程师", "summary": "负责 Agent 产品", "url": "https://example.com/agent"},
    ]
    kept = rt._filter_relevant_rows(rows, "AI Agent")
    titles = [row["title"] for row in kept]
    assert "AI Agent 工程师" in titles
    assert "AI-HR 培训生" not in titles


def test_build_digest_normalizes_city_suffix():
    from src.research_digest import build_digest

    digest = build_digest(
        [
            {
                "title": "AI Agent 工程师",
                "location": "深圳总部 上海",
                "description": "负责 Agent 产品",
                "requirements": "Python",
                "salary": "",
            }
        ],
        [],
    )
    assert digest["cities"][0]["city"] == "深圳"
    assert digest["multi_city_jd_count"] == 1


def test_build_report_salary_gap_mentions_failed_boss(temp_profile):
    from src.research_report import build_report

    profile = profile_module.load_profile()
    gathered = {
        "direction": "AI Agent 开发",
        "city": "北京",
        "education_tag": "双非本",
        "jd_families": [
            {
                "slug": "boss",
                "label": "BOSS直聘",
                "rows": [
                    {
                        "company": "某公司",
                        "title": "AI Agent 工程师",
                        "location": "北京",
                        "salary": "",
                        "summary": "负责 Agent 产品",
                        "source": "BOSS直聘",
                        "url": "https://example.com/boss/1",
                        "description": "负责 Agent 产品",
                        "requirements": "Python",
                    }
                ],
                "status": "failed",
                "error": "登录态失效",
                "elapsed": 0.2,
                "dropped_no_detail": 0,
                "dropped_titles": [],
            }
        ],
        "cases_result": {"cases": [], "warnings": [], "sources": {}},
    }
    report = build_report(profile, gathered)
    reasons = [g["reason"] for g in report["gaps"]]
    assert any("BOSS" in reason or "未成功" in reason for reason in reasons)


def test_save_report_reuses_same_fingerprint_and_merges(temp_profile):
    profile = profile_module.load_profile()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _report(url):
        return {
            "type": "research_report",
            "direction": "AI Agent 工程师",
            "city": "北京",
            "education_tag": "双非本",
            "fingerprint": "fp-same-round",
            "generated_at": now,
            "context": {
                "goal": "AI Agent 工程师",
                "city": "北京",
                "education": "双非本",
                "resume_trust": "medium",
            },
            "jd_samples": [{**_job(), "url": url, "fetched_at": now}],
            "cases": [],
            "source_status": [
                {"source": "BOSS", "scope": "jd", "status": "ok",
                 "count": 1, "elapsed": 0.2, "error": ""}
            ],
            "case_warnings": [],
            "gaps": [],
            "counts": {
                "jd_samples": 1, "cases": 0, "cases_raw": 0,
                "cases_filtered": 0, "dropped_no_detail": 0,
                "source_ok": 1, "source_fail": 0, "source_empty": 0,
            },
        }

    paths1 = save_report(profile, _report("https://example.com/job/1"))
    profile2 = profile_module.load_profile()
    paths2 = save_report(profile2, _report("https://example.com/job/2"))

    assert paths2["md"] == paths1["md"]
    assert paths2["html"] == paths1["html"]
    assert paths2["json"] == paths1["json"]

    profile3 = profile_module.load_profile()
    assert profile3.research["counts"]["jd_samples"] == 2
    urls = {item["url"] for item in profile3.research["jd_samples"]}
    assert urls == {"https://example.com/job/1", "https://example.com/job/2"}


def test_cases_parallel_with_jd_sources(temp_profile, monkeypatch):
    import src.tools.research_tools as rt

    def fake_fetch(slug, label, raw_spec, cache_key, fingerprint):
        time.sleep(0.05)
        return {
            "slug": slug,
            "label": label or slug,
            "rows": [],
            "status": "empty",
            "error": "",
            "elapsed": 0.05,
            "dropped_no_detail": 0,
            "dropped_titles": [],
        }

    monkeypatch.setattr(rt, "_fetch_family_sync", fake_fetch)
    monkeypatch.setattr(
        rt,
        "collect_cases",
        lambda **kwargs: {"cases": [_case()], "warnings": [], "sources": {}},
    )

    profile = profile_module.load_profile()
    specs = [{"company": "字节"}, {"company": "腾讯"}]
    gathered = asyncio.run(
        rt._run_research(
            profile, specs, {}, "", "", "AI Agent 开发", "fp-parallel", {}
        )
    )
    assert len(gathered["cases_result"]["cases"]) >= 1


def test_batched_specs_with_same_round_key_merge_single_report(temp_profile):
    """不同 specs 分批抓取：同方向/城市/教育档/档案 → 合并到同一份报告。"""
    import src.tools.research_tools as rt

    loader = _FakeLoader({
        "bytedance": {
            "company": "bytedance",
            "results": [{
                **_job(company="字节跳动"),
                "url": "https://example.com/job/bytedance",
                "source": "bytedance",
            }],
            "count": 1,
        },
        "tencent": {
            "company": "tencent",
            "results": [{
                **_job(company="腾讯"),
                "url": "https://example.com/job/tencent",
                "source": "tencent",
            }],
            "count": 1,
        },
    })
    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    original_detail = rt.get_job_detail
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [], "warnings": [], "sources": {}}
    rt.get_job_detail = lambda url, company=None: {
        "description": "负责 Agent 产品后端与 RAG 链路。",
        "requirements": "熟悉 Python / LangGraph。",
    }
    try:
        first = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "字节", "limit": 3}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            direction="AI Agent 开发",
        ))
        second = asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "腾讯", "limit": 3}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            direction="AI Agent 开发",
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.get_job_detail = original_detail

    assert "index.html" in first and "index.html" in second
    report_dir = assets.get_assets_root() / "默认档案" / "调研报告"
    html_files = [p for p in report_dir.iterdir() if p.suffix == ".html"]
    assert len(html_files) == 1, "同轮分批调用只能保留一份报告"

    research = profile_module.load_profile().research
    assert research["round_key"]
    assert research["counts"]["jd_samples"] == 2
    urls = {item["url"] for item in research["jd_samples"]}
    assert urls == {
        "https://example.com/job/bytedance",
        "https://example.com/job/tencent",
    }


def test_role_keyword_filters_irrelevant_jobs_and_reports_gap(temp_profile):
    """jd_specs 只有 company 时，用 case_query.role 过滤跑偏岗位并留下缺口。"""
    import src.tools.research_tools as rt

    rows = [
        {
            "company": "腾讯",
            "title": "AI-HR 培训生",
            "location": "深圳",
            "salary": "",
            "summary": "人力资源方向",
            "source": "tencent",
            "url": "https://example.com/job/hr",
        },
        {
            "company": "腾讯",
            "title": "AI Agent 工程师",
            "location": "深圳",
            "salary": "",
            "summary": "负责 Agent 产品后端",
            "source": "tencent",
            "url": "https://example.com/job/agent",
        },
    ]
    loader = _FakeLoader({
        "tencent": {"company": "tencent", "results": rows, "count": 2},
    })
    original_loader = rt.search_company_jobs
    original_cases = rt.collect_cases
    original_detail = rt.get_job_detail
    rt.search_company_jobs = loader
    rt.collect_cases = lambda **kwargs: {"cases": [], "warnings": [], "sources": {}}
    rt.get_job_detail = lambda url, company=None: {
        "description": "负责 Agent 产品后端与 RAG 链路。",
        "requirements": "熟悉 Python / LangGraph。",
    }
    try:
        asyncio.run(rt.gather_research_data(
            json.dumps([{"company": "腾讯"}]),
            json.dumps({"role": "AI Agent 开发", "education": "双非本"}),
            direction="AI Agent 开发",
        ))
    finally:
        rt.search_company_jobs = original_loader
        rt.collect_cases = original_cases
        rt.get_job_detail = original_detail

    research = profile_module.load_profile().research
    assert research["counts"]["jd_samples"] == 1
    assert research["counts"]["filtered_irrelevant"] == 1
    titles = [item["title"] for item in research["jd_samples"]]
    assert "AI-HR 培训生" not in titles

    tencent_status = [
        s for s in research["source_status"] if s.get("slug") == "tencent"
    ]
    assert tencent_status and tencent_status[0]["filtered_irrelevant"] == 1
    assert any("因方向不匹配被过滤" in gap["missing"] for gap in research["gaps"])


def test_merge_reports_dedupes_source_counts():
    """同源两批合并：count/dropped 按合并后的 source_status 取 max 重算，不直接相加。"""
    from src.research_report import merge_reports

    def _report(url, count, dropped):
        return {
            "type": "research_report",
            "direction": "AI Agent 开发",
            "city": "北京",
            "education_tag": "双非本",
            "fingerprint": f"fp-{url}",
            "round_key": "round-same",
            "generated_at": "2026-10-26 20:00",
            "context": {"goal": "AI Agent 开发", "city": "北京", "education": "双非本"},
            "jd_samples": [{**_job(), "url": url, "fetched_at": "2026-10-26 20:00"}],
            "cases": [],
            "source_status": [{
                "source": "腾讯",
                "slug": "tencent",
                "scope": "jd",
                "status": "ok",
                "count": count,
                "elapsed": 0.2,
                "error": "",
                "dropped_no_detail": dropped,
                "filtered_irrelevant": 1,
            }],
            "case_warnings": [],
            "gaps": [],
            "counts": {
                "jd_samples": 1, "cases": 0, "cases_raw": 0,
                "cases_filtered": 0, "dropped_no_detail": dropped,
                "filtered_irrelevant": 1,
                "source_ok": 1, "source_fail": 0, "source_empty": 0,
            },
        }

    merged = merge_reports(
        _report("https://example.com/job/1", 3, 2),
        _report("https://example.com/job/2", 1, 1),
    )
    tencent = [s for s in merged["source_status"] if s.get("slug") == "tencent"]
    assert len(tencent) == 1
    assert tencent[0]["count"] == 3
    assert merged["counts"]["dropped_no_detail"] == 2
    assert merged["counts"]["filtered_irrelevant"] == 1
    assert merged["round_key"] == "round-same"


def test_boss_list_only_rows_kept_and_reported(temp_profile):
    import src.tools.research_tools as rt
    from src.research_report import build_report

    rows = [
        {
            "company": "某科技公司",
            "title": "AI Agent 工程师",
            "location": "北京",
            "salary": "25-45K·16薪",
            "summary": "Python | RAG | 五险一金",
            "source": "boss",
            "url": "https://www.zhipin.com/job_detail/JOB1.html",
            "description": "",
            "requirements": "",
            "detail_status": "list_only",
        }
    ]

    called = {"detail": False}
    original_detail = rt.get_job_detail
    rt.get_job_detail = lambda *a, **k: called.__setitem__("detail", True) or {}
    try:
        kept, dropped = rt._enrich_with_detail("boss", rows)
    finally:
        rt.get_job_detail = original_detail

    assert called["detail"] is False, "list_only 行不应补抓详情"
    assert dropped == []
    assert kept[0]["detail_status"] == "list_only"
    assert kept[0]["salary"] == "25-45K·16薪"

    original_search = rt.search_company_jobs
    original_cache = rt._write_partial_cache
    rt.search_company_jobs = lambda slug, **kwargs: {
        "company": "BOSS直聘", "results": rows, "count": 1,
    }
    rt._write_partial_cache = lambda *a, **k: None
    try:
        family = rt._fetch_family_sync(
            "boss", "BOSS直聘", {"keyword": "AI Agent"}, "cache-key", "fingerprint"
        )
    finally:
        rt.search_company_jobs = original_search
        rt._write_partial_cache = original_cache

    assert family["list_only"] == 1

    report = build_report(
        profile_module.load_profile(),
        {
            "direction": "AI Agent 开发",
            "city": "北京",
            "education_tag": "双非本",
            "jd_families": [family],
            "cases_result": {"cases": [], "warnings": [], "sources": {}},
        },
    )

    assert report["counts"]["list_only"] == 1
    assert report["source_status"][0]["list_only"] == 1
    assert any("仅列表数据" in gap["missing"] for gap in report["gaps"])
    assert report["jd_samples"][0]["detail_status"] == "list_only"
