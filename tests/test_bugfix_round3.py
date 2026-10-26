"""BUG 修复第三轮回归（dev/test/BUG.md：ec77aa6 复测出的 8 项）。

- #1  save_current_detail 孤儿阶段守卫（无路线图 / 缺 phase_id / 未知 phase_id）
- #2  GitHub 检索：意图词 AND 组合 + 标题命中门槛 + filter_company 参与检索；
      案例卡意图 gate（技术讨论/CI 修复不得冒充「同背景成功经验」）
- #3  案例卡带命中原因（hit_terms），报告逐条标注
- #4  牛客 snippet 缺失 → 详情页 meta description 补水 / 显式标「摘要未获取」
- #5  调研汇报 JD 源与案例源分开统计（状态面板合并案例源）
- #6  摸排提示优先技能名（name/title 键），摘录剥「用户确认：」前缀
- #7  报告标题/上下文 direction 优先于 want.target_role
- #8  知识库废词查询被相关度阈值挡住（2-gram 降权）
"""

from __future__ import annotations

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
    return tmp_path


class _FakeCache:
    def __init__(self):
        self._d = {}

    def get(self, key):
        return self._d.get(key)

    def set(self, key, value):
        self._d[key] = value


# ============ #1 save_current_detail 守卫 ============


def test_save_current_detail_rejects_orphan_phase(temp_profile):
    from src.server import save_current_detail

    # 无路线图（修复前 phase_ids 为空会跳过守卫，直接落孤儿 detail）
    no_plan = json.loads(save_current_detail(json.dumps(
        {"phase_id": "phase_99", "tasks": [{"name": "刷题"}]}
    )))
    assert no_plan["code"] == "MISSING_DATA"
    assert "路线图" in no_plan["message"]

    p = profile_module.load_profile()
    p.plan = {"roadmap": {"phases": [{"id": "phase_1", "name": "基础学习"}]}}
    profile_module.save_profile(p)

    bad_id = json.loads(save_current_detail(json.dumps(
        {"phase_id": "phase_99", "tasks": []}
    )))
    assert bad_id["code"] == "MISSING_DATA"
    assert "phase_99" in bad_id["message"]

    missing = json.loads(save_current_detail(json.dumps({"tasks": []})))
    assert missing["code"] == "INVALID_PARAM"


# ============ #2 GitHub 意图 AND + 标题门槛 ============


def test_github_scraper_and_intent_title_gate_and_company(monkeypatch):
    from src.scrapers.github.scraper import Scraper

    monkeypatch.setattr(Scraper, "_make_cache", lambda self, ns: _FakeCache())
    s = Scraper()
    captured = {}

    def fake_request(url, params=None):
        captured["q"] = params["q"]
        return {
            "items": [
                {   # 岗位 + 意图都在标题 → 保留（排序靠前）
                    "title": "字节 Agent 开发实习 秋招面经（已拿 offer）",
                    "html_url": "https://github.com/a/b/issues/1",
                    "body": "一面问 RAG 链路",
                    "created_at": "2026-09-01T00:00:00Z",
                    "reactions": {"total_count": 3},
                },
                {   # 日文 issue：正文顺带提到 Agent，标题不沾检索词 → 丢弃
                    "title": "CI が失敗する件について",
                    "html_url": "https://github.com/a/b/issues/2",
                    "body": "Agent のログを確認した",
                    "created_at": "2026-09-01T00:00:00Z",
                },
                {   # 纯技术讨论：无求职意图词 → 丢弃
                    "title": "Fix sorting bug in Agent pipeline",
                    "html_url": "https://github.com/a/b/issues/3",
                    "body": "排序稳定性问题",
                    "created_at": "2026-09-01T00:00:00Z",
                },
            ]
        }

    monkeypatch.setattr(s, "_request", fake_request)
    rows = s.search(keyword="Agent", filter_company="字节")

    q = captured["q"]
    assert "(" in q and ")" in q and " OR " in q, "意图词应组合成括号块（AND 语义）"
    assert '"字节"' in q, "filter_company 必须作为必中条件参与检索"
    assert [r["url"] for r in rows] == ["https://github.com/a/b/issues/1"]
    assert "意图" in rows[0]["snippet"] or rows[0]["title"].startswith("字节")


def test_github_scraper_all_junk_returns_error(monkeypatch):
    from src.scrapers.github.scraper import Scraper

    monkeypatch.setattr(Scraper, "_make_cache", lambda self, ns: _FakeCache())
    s = Scraper()
    monkeypatch.setattr(s, "_request", lambda url, params=None: {"items": [
        {"title": "Refactor CI cache", "html_url": "https://github.com/a/b/issues/9"},
    ]})
    out = s.search(keyword="Agent")
    assert out and out[0].get("error")
    assert "过滤" in out[0]["error"]


def test_case_search_gates_junk_and_keeps_hit_terms(monkeypatch):
    import src.case_search as cs
    import src.scrapers.loader as loader

    def fake_loader(slug, **kwargs):
        if slug == "github":
            return {"company": "github", "count": 2, "results": [
                {"title": "Fix CI sorting bug", "url": "gh://junk",
                 "snippet": "refactor", "source": "github"},
                {"title": "27 届双非本 秋招上岸字节 Agent 实习复盘", "url": "gh://good",
                 "snippet": "投了 40 家，面试问到 RAG", "source": "github"},
            ]}
        return {"company": slug, "count": 0, "results": []}

    monkeypatch.setattr(loader, "search_company_jobs", fake_loader)
    monkeypatch.setattr(cs, "_search_local", lambda q: {"results": [], "count": 0})

    result = cs.collect_cases("AI Agent 开发")
    titles = [c["title"] for c in result["cases"]]
    assert titles == ["27 届双非本 秋招上岸字节 Agent 实习复盘"]
    assert result["cases"][0]["hit_terms"], "案例卡必须带命中原因"
    rendered = cs.render_cases(result, "AI Agent 开发", "", "")
    assert "命中：" in rendered


# ============ #4 牛客 snippet 补水 ============


def test_nowcoder_hydrates_missing_snippets(monkeypatch):
    from src.scrapers.nowcoder.scraper import Scraper

    s = Scraper()
    monkeypatch.setattr(
        s, "_fetch_meta_snippet",
        lambda url: "字节 Agent 实习面经：一面问了 RAG 与工具调用" if "ok" in url else "",
    )
    rows = [
        {"title": "条目一", "url": "u-ok", "snippet": ""},
        {"title": "条目二", "url": "u-fail", "snippet": ""},
        {"title": "条目三", "url": "u-old", "snippet": "已有摘要"},
    ]
    s._hydrate_snippets(rows)

    assert "RAG" in rows[0]["snippet"]
    assert "snippet_status" not in rows[0]
    assert rows[1]["snippet"] == ""
    assert rows[1]["snippet_status"] == "unavailable", "补不到摘要必须显式标注，不能静默为空"
    assert rows[2]["snippet"] == "已有摘要"
    assert "snippet_status" not in rows[2]


# ============ #5 调研汇报来源口径 ============


def test_report_message_splits_jd_and_case_sources():
    from src.tools.research_tools import _render_report_message

    report = {
        "direction": "AI Agent 开发",
        "context": {"goal": "AI Agent 开发", "city": "北京", "education": "双非本"},
        "counts": {"jd_samples": 2, "cases": 1, "source_ok": 2,
                   "source_fail": 0, "source_empty": 0},
        "source_status": [
            {"source": "boss", "scope": "jd", "status": "ok", "count": 2},
            {"source": "案例·nowcoder", "scope": "cases", "status": "ok", "count": 3},
            {"source": "案例·github", "scope": "cases", "status": "empty", "count": 0},
        ],
        "gaps": [],
    }
    msg = _render_report_message(
        report, {"md": "m", "html": "h", "json": "j", "index": "i"}
    )
    assert "市场调研完成（AI Agent 开发）" in msg, "标题取 direction，不被档案目标覆盖"
    assert "JD 源 1 个可用" in msg and "案例源 1 个可用" in msg
    assert "2 条真实岗位样本" in msg and "1 条同学历经历" in msg


# ============ #7 direction 优先 ============


def test_report_context_prefers_direction_and_marks_hits(temp_profile):
    from src.research_report import build_report, render_markdown

    profile = profile_module.load_profile()
    profile.want = {"target_role": "Agent 开发工程师（实习）"}
    profile_module.save_profile(profile)

    report = build_report(profile, {
        "direction": "AI Agent 开发",
        "city": "北京",
        "education_tag": "双非本",
        "jd_families": [
            {"slug": "boss", "label": "boss", "rows": [
                {"title": "AI Agent 工程师", "summary": "熟悉 RAG", "source": "boss",
                 "url": "https://example.com/j/1", "company": "某厂"},
            ], "status": "ok", "error": "", "elapsed": 0.3},
        ],
        "cases_result": {
            "cases": [{
                "kind": "success_experience", "title": "双非本上岸字节",
                "background": {"education_tag": "双非本"},
                "hit_terms": ["秋招", "offer"],
                "highlights": [], "source": "github", "url": "https://github.com/a/b/issues/1",
            }],
            "warnings": ["github: 检索词过于复杂（422）"],
            "sources": {"nowcoder": 0, "github": 0},
        },
    })

    assert report["context"]["goal"] == "AI Agent 开发", "显式 direction 优先于档案 want"
    assert report["cases"][0]["hit_terms"] == ["秋招", "offer"]

    scopes = {s["source"]: s for s in report["source_status"]}
    assert scopes["案例·nowcoder"]["scope"] == "cases"
    assert scopes["案例·nowcoder"]["status"] == "empty"
    assert scopes["案例·github"]["status"] == "failed"

    md = render_markdown(report)
    assert "命中：秋招、offer" in md


# ============ #6 技能名回退链 ============


def test_skill_display_name_prefers_real_keys():
    from src.tools.probing import ai_authored_skill_names, skill_display_name

    assert skill_display_name({"name": "React", "authorship": "ai_assisted"}, 0) == "React"
    assert skill_display_name({"title": "LangGraph"}, 1) == "LangGraph"
    fallback = skill_display_name({"evidence": "用户确认：HotMirror Studio 项目"}, 2)
    assert fallback.startswith("技能[2]（HotMirror Studio")
    assert "用户确认：" not in fallback

    names = ai_authored_skill_names({"skills": [
        {"name": "React", "authorship": "ai_assisted"},
        {"evidence": "用户确认：HotMirror Studio", "authorship": "ai_generated"},
    ]})
    assert names[0] == "React"
    assert names[1].startswith("技能[1]（HotMirror Studio")


# ============ #8 知识库废词过滤 ============


def test_knowledge_nonsense_query_returns_nothing(tmp_path, monkeypatch):
    from src.tools import knowledge_search as ks

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "字节跳动 面经.md").write_text(
        "秋招面经：字节跳动 Agent 开发一面，问了 RAG 与工具调用。\n" * 3,
        encoding="utf-8",
    )
    (knowledge / "杂项笔记.md").write_text(
        "今天修了个排序 bug，CI 挂了。", encoding="utf-8",
    )
    monkeypatch.setattr(ks, "KNOWLEDGE_DIR", knowledge)

    junk = ks.search_knowledge("完全无关的废词组合xyz123")
    assert junk["results"] == [], "无意义查询不得靠 2-gram 噪声命中"

    good = ks.search_knowledge("字节跳动 面经")
    assert good["results"], "有意义查询仍要命中有价值资料"
    assert good["results"][0]["source"] == "字节跳动 面经.md"
    assert good["results"][0]["relevance"] >= ks.MIN_RELEVANCE
