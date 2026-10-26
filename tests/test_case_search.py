"""search_cases 案例搜寻聚合回归——聚合/去重/学历打分/kind 拆分/失败容忍。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class FakeCache:
    def __init__(self):
        self._d = {}

    def get(self, key):
        return self._d.get(key)

    def set(self, key, value):
        self._d[key] = value


def _noop_patch_caches(monkeypatch):
    """GitHub scraper 的文件缓存指向真实 CACHE_DIR——单元测试替成内存缓存。"""
    from src.scrapers import github as gh_pkg  # noqa: F401
    from src.scrapers.github import scraper as gh

    for mod in (gh,):
        monkeypatch.setattr(mod.Scraper, "_make_cache", lambda self, ns: FakeCache())


def _loader_resp(rows: list[dict], count: int | None = None) -> dict:
    return {"company": "c", "results": rows, "count": count if count is not None else len(rows)}


def _patch_online_sources(monkeypatch, *, nowcoder, github, official=None):
    import src.case_search as cs
    import src.scrapers.loader as loader

    def fake_loader_search(company, **kwargs):
        if company == "nowcoder":
            return nowcoder
        if company == "github":
            return github
        if company == "boss":
            return official or _loader_resp([])
        return _loader_resp([])

    def fake_local_search(query):
        return {"results": [], "count": 0, "knowledge_dir": "x"}

    monkeypatch.setattr(loader, "search_company_jobs", fake_loader_search)
    monkeypatch.setattr(cs, "_search_local", fake_local_search)


# ============ GitHub scraper ============

def test_github_scraper_query_and_parse(monkeypatch):
    from src.scrapers.github.scraper import Scraper

    _noop_patch_caches(monkeypatch)
    s = Scraper()
    captured = {}

    def fake_request(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {
            "items": [
                {
                    "title": "27届双非本 字节后端 offer 复盘",
                    "html_url": "https://github.com/a/b/issues/1",
                    "body": "路径：先小厂再大厂……面经：HTTP 缓存，进程线程。",
                    "created_at": "2026-03-01T00:00:00Z",
                    "reactions": {"total_count": 12},
                    "repository_url": "https://api.github.com/repos/a/b",
                },
                {"title": "", "html_url": "https://github.com/a/b/issues/2", "body": "x"},
            ]
        }

    monkeypatch.setattr(s, "_request", fake_request)
    rows = s.search(keyword="后端", education="双非", page=1)

    q = captured["params"]["q"]
    assert "后端" in q and "面经" in q and "秋招" in q and "双非" in q
    assert captured["params"]["type"] == "issue"

    assert len(rows) == 1
    row = rows[0]
    assert row["education_tag"] == "双非本"
    assert row["year_tag"] == "27届"
    assert row["reactions"] == 12
    assert row["source"] == "github"
    assert row["date"] == "2026-03-01"


def test_github_scraper_detail_and_errors(monkeypatch):
    from src.scrapers.github.scraper import Scraper

    _noop_patch_caches(monkeypatch)
    s = Scraper()

    monkeypatch.setattr(s, "_request", lambda url, params=None: {
        "title": "二本学生dives 字节一面",
        "body": "考了 TCP, Redis 持久化",
        "created_at": "2026-02-01T00:00:00Z",
    })
    detail = s.get_detail("https://github.com/a/b/issues/5")
    assert detail["content"].startswith("考了")
    assert detail["education_tag"] == "双非本"
    assert detail["source"] == "github"

    assert "error" in s.get_detail("https://example.com/x")
    blank = s.search(keyword="")
    assert blank and blank[0].get("error"), "空 keyword 应返回可读错误条目"
    monkeypatch.setattr(s, "_request", lambda url, params=None: {"items": []})
    empty = s.search(keyword="冷门关键词")
    assert empty[0].get("error")


# ============ 聚合器 collect_cases ============

def _sample_rows():
    nowcoder = _loader_resp([
        {"title": "双非本 字节 Agent 实习 面经（一二三面全）", "url": "nc://1", "snippet": "手撕：二叉树反序列化；项目 Agent 工具调用。",
         "date": "2026-05-01", "company": "字节", "position": "Agent", "source": "nowcoder"},
        {"title": "普本 秋招失败复盘", "url": "nc://1", "snippet": "重复 url 应被去重", "date": "2025-01-01", "source": "nowcoder"},
    ], count=1)
    github = _loader_resp([
        {"title": "27届双非本 字节 offer retrospective", "url": "gh://1", "snippet": "先小厂后大厂",
         "date": "2026-06-01", "stock_tag": "", "education_tag": "双非本", "year_tag": "27届", "source": "github"},
    ])
    boss = _loader_resp([
        {"title": "AI Agent 开发工程师", "url": "boss://1", "salary": "20-35K", "location": "深圳",
         "summary": "熟悉 LangGraph/RAG；本科；有工具调用经验优先。", "company": "BOSS直聘", "source": "boss"},
    ])
    return nowcoder, github, boss


def test_collect_cases_grouping_ranking_dedupe(monkeypatch):
    import src.case_search as cs

    nowcoder, github, boss = _sample_rows()

    def fake_loader_search(company, **kwargs):
        return {"nowcoder": nowcoder, "github": github, "boss": boss}.get(company, _loader_resp([]))

    monkeypatch.setattr(cs, "_search_local", lambda q: {"results": [], "count": 0, "knowledge_dir": "x"})

    # 直接 patch loader 层
    import src.scrapers.loader as loader
    monkeypatch.setattr(loader, "search_company_jobs", fake_loader_search)

    result = cs.collect_cases("AI Agent 开发", company="boss", education="双非本")

    cases = result["cases"]
    kinds = [c["kind"] for c in cases]
    assert kinds.count("success_experience") >= 1 and kinds.count("interview_requirements") >= 2
    # 双非本命中卡片排前（match_score 存在且为前两张里 educ 相关的最高）
    assert cases[0].get("match_score", 0) >= 4.0
    # 同 url 去重：nc://1 只出现一次
    assert len([c for c in cases if c["url"].startswith("nc://")]) == 1
    # JD 卡带薪资
    req = [c for c in cases if c["kind"] == "interview_requirements" and c.get("salary")]
    assert req and req[0]["salary"] == "20-35K"
    assert "warnings" in result and result["sources"]["local"] == 0


def test_collect_cases_kind_filter_and_failures(monkeypatch):
    import src.case_search as cs

    nowcoder, github, _ = _sample_rows()
    failures = {"nowcoder": {"error": "Playwright 执行失败", "results": []},
                "github": _loader_resp([])}

    def fake_loader_search(company, **kwargs):
        return failures[company]

    import src.scrapers.loader as loader
    monkeypatch.setattr(loader, "search_company_jobs", fake_loader_search)
    monkeypatch.setattr(cs, "_search_local", lambda q: {"results": [], "count": 0, "knowledge_dir": "x"})

    result = cs.collect_cases("后端", education="", kind="success")
    assert all(c["kind"] == "success_experience" for c in result["cases"])
    assert result["cases"] == []  # nowcoder 失败、github 空结果 → 空
    warns = " ".join(result["warnings"])
    assert "nowcoder" in warns
    assert not result["sources"].get("local")


def test_collect_cases_rejects_bad_education(monkeypatch):
    import src.case_search as cs

    monkeypatch.setattr(cs, "_search_local", lambda q: {"results": [], "count": 0, "knowledge_dir": "x"})
    result = cs.collect_cases("后端", education="海邦毕业")
    assert result["cases"] == []
    assert any("无法归一" in w for w in result["warnings"])


def test_render_cases_layout_and_texts(monkeypatch):
    import src.case_search as cs

    nowcoder, github, boss = _sample_rows()

    def fake_loader_search(company, **kwargs):
        return {"nowcoder": nowcoder, "github": github, "boss": boss}.get(
            company, _loader_resp([])
        )

    import src.scrapers.loader as loader
    monkeypatch.setattr(loader, "search_company_jobs", fake_loader_search)
    monkeypatch.setattr(cs, "_search_local", lambda q: {"results": [], "count": 0, "knowledge_dir": "x"})

    result = cs.collect_cases("AI Agent 开发", company="字节", education="双非本")
    text = cs.render_cases(result, "AI Agent 开发", "双非本", "字节")
    assert "同背景成功经验" in text and "面试要求" in text
    assert "来源：" in text and "gh://1" in text
    # 纪律提示：案例必须标来源
    assert "不标注来源不诚实" in text

    # 空结果引导
    empty = {"cases": [], "warnings": ["nowcoder: 无结果"], "sources": {"local": 0}}
    t2 = cs.render_cases(empty, "后端", "", "")
    assert "全部失败" in t2 and "放宽条件" in t2
