"""Round 10：BUG.md 修复回归（角色归一 / 字体标题 / 统计口径 / 抓取降级）。"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.artifacts.models import (  # noqa: E402
    ArtifactMeta,
    HardRequirement,
    JDEvidence,
    RequirementProfile,
    TargetSpec,
)
from src.core.stages import (
    evidence as evidence_stage,  # noqa: E402
    requirements,  # noqa: E402
)
from src.core.stages.target_companies import _target_conflicts  # noqa: E402
from src.models import CareerProfile  # noqa: E402
from src.scrapers.github.scraper import Scraper as GithubScraper  # noqa: E402
from src.scrapers.shixiseng import (
    font_loader,  # noqa: E402
    scraper as shixiseng,  # noqa: E402
)
from src.tools.research_tools import (  # noqa: E402
    _filter_relevant_rows_traced,
    _summarize_case_contents,
)
from src.tools.roadmap_tools import _compact_profile  # noqa: E402


def test_role_alias_is_not_a_conflict() -> None:
    artifact = TargetSpec(role="Agent 开发工程师", city="上海市")
    assert _target_conflicts({"role": "Agent 开发", "city": "上海"}, artifact) == []
    assert _target_conflicts({"role": "AI Agent 开发"}, TargetSpec(role="Agent 开发")) == []
    assert _target_conflicts({"role": "后端开发"}, TargetSpec(role="Agent 开发"))


def _meta(artifact_id: str, stage: str) -> ArtifactMeta:
    return ArtifactMeta(
        id=artifact_id,
        stage=stage,
        profile_name="default",
        created_at=datetime.now().isoformat(),
    )


def test_hard_requirement_prompt_count_matches_data() -> None:
    artifact = RequirementProfile(
        meta=_meta("rp_test", "requirement"),
        evidence_run_id="ev_test",
        sample_size_jd=20,
        hard_requirements=[
            HardRequirement(evidence_id=f"JD{index:03d}", education="本科")
            for index in range(1, 10)
        ],
    )
    prompt = requirements.build_analysis_prompt(artifact)
    assert "共 9 条" in prompt
    assert "完整清单见 hard_requirements" in prompt


def _sfnt_bytes(tables: dict[str, bytes]) -> bytes:
    header = struct.pack(">IHHHH", 0x00010000, len(tables), 0, 0, 0)
    offset = 12 + 16 * len(tables)
    records = b""
    body = b""
    for tag, data in sorted(tables.items()):
        records += struct.pack(">4sIII", tag.encode(), 0, offset + len(body), len(data))
        body += data
    return header + records + body


def _synthetic_font() -> bytes:
    segment = struct.pack(">HHHHHHH", 4, 24, 0, 2, 2, 0, 0)
    segment += struct.pack(">H", 0xE002) + struct.pack(">H", 0)
    segment += struct.pack(">H", 0xE000)
    segment += struct.pack(">h", (1 - 0xE000) & 0x7FFF)
    segment += struct.pack(">H", 0)
    cmap = struct.pack(">HH", 0, 1) + struct.pack(">HHI", 3, 1, 12) + segment
    post = struct.pack(">I", 0x00020000) + b"\0" * 28
    post += struct.pack(">H", 4) + struct.pack(">HHHH", 0, 258, 259, 260)
    for name in ("uni4E2D", "uni6587", "uni41"):
        post += bytes([len(name)]) + name.encode("latin1")
    return _sfnt_bytes({"cmap": cmap, "post": post})


def test_font_map_parser_restores_private_use_chars() -> None:
    mapping = font_loader.parse_font_map(_synthetic_font())
    assert mapping == {"\ue000": "中", "\ue001": "文", "\ue002": "A"}


def test_clean_title_marks_unknown_font_as_low(monkeypatch) -> None:
    monkeypatch.setattr(shixiseng, "_FONT_MAP", {"\ue000": "中", "\ue001": "文"})
    title, quality = shixiseng._clean_title("&#xe000;&#xe001;开发")
    assert title == "中文开发"
    assert quality == "ok"

    title, quality = shixiseng._clean_title("&#xe000;&#xe001;开发&#xe999")
    assert title == "中文开发"
    assert quality == "low"


def test_research_keyword_splits_agent_and_development() -> None:
    rows = [{
        "title": "算法实习生（AI Agent 开发方向）",
        "summary": "负责智能体应用",
        "url": "https://example.com/1",
    }]
    kept, dropped = _filter_relevant_rows_traced(rows, "Agent开发")
    assert len(kept) == 1
    assert dropped == []


def test_research_drops_low_quality_titles() -> None:
    rows = [{
        "title": "开发",
        "title_quality": "low",
        "url": "https://example.com/2",
    }]
    kept, dropped = _filter_relevant_rows_traced(rows, "Agent开发")
    assert kept == []
    assert dropped and "标题解析质量低" in dropped[0]["reason"]


class _MemoryCache:
    def get(self, key):
        return None

    def set(self, key, value):
        return None


def test_github_search_retries_with_relaxed_query(monkeypatch) -> None:
    scraper = GithubScraper()
    calls: list[str] = []

    def fake_api(q, order, page):
        calls.append(q)
        if "面经 OR 面试" in q:
            return {"items": [{
                "title": "Agent 开发面经与复盘",
                "body": "秋招面试经验",
                "html_url": "https://github.com/x/y/issues/1",
                "created_at": "2026-01-01T00:00:00Z",
                "reactions": {"total_count": 1},
                "repository_url": "https://api.github.com/repos/x/y",
            }]}
        return {"items": []}

    monkeypatch.setattr(scraper, "_search_api", fake_api)
    monkeypatch.setattr(scraper, "_make_cache", lambda namespace: _MemoryCache())

    rows = scraper.search(keyword="Agent")
    assert rows and rows[0]["title"] == "Agent 开发面经与复盘"
    assert any("面经 OR 面试" in call for call in calls)


def test_evidence_search_retries_once_on_timeout(monkeypatch) -> None:
    attempts = {"count": 0}

    def flaky_search(slug, **params):
        attempts["count"] += 1
        if attempts["count"] == 1:
            time.sleep(0.2)
            return {"results": []}
        return {"results": [{"title": "Agent 开发", "url": "https://example.com/jd"}]}

    monkeypatch.setattr(evidence_stage, "search_company_jobs", flaky_search)
    monkeypatch.setattr(evidence_stage, "SOURCE_TIMEOUT", 0.05)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            evidence_stage._search_company_jobs(
                None, "unknown", "Agent", "上海", 5,
                loop.time() + 5, asyncio.Semaphore(1),
            )
        )
    finally:
        loop.close()

    assert result["status"] == "ok"
    assert attempts["count"] == 2


def _jd(jd_id: str, requirements_text: str) -> JDEvidence:
    return JDEvidence(
        id=jd_id,
        company_id="c1",
        company="测试公司",
        tier="中厂",
        title="Agent 开发",
        requirements=requirements_text,
        description="Agent",
        detail_status="ok",
    )


def test_missing_requirements_excluded_from_keyword_denominator() -> None:
    run = requirements.EvidenceRun(
        meta=_meta("ev_test", "evidence"),
        target_spec=TargetSpec(role="Agent 开发"),
        company_pool_id="cp_test",
        jd_items=[
            _jd("JD001", "熟悉 Agent"),
            _jd("JD002", "Agent 平台"),
            _jd("JD003", ""),
        ],
    )
    stats = requirements.compute_statistics(run)
    assert stats["sample_size_jd"] == 3
    assert stats["missing_requirements_jd"] == ["JD003"]
    items = [*stats["high_frequency"], *stats["nice_to_have"]]
    agent_item = next(item for item in items if item.term == "Agent")
    assert agent_item.jd_frequency == 1.0
    assert any("已排除出关键词分母" in gap for gap in stats["gaps"])


def test_case_content_summary_reports_unavailable() -> None:
    result = {
        "cases": [
            {"title": "有全文", "content_status": "ok"},
            {"title": "缺全文", "content_status": "unavailable"},
        ],
        "warnings": [],
    }
    summarized = _summarize_case_contents(result)
    assert summarized["case_content_status"] == {"ok": 1, "unavailable": 1, "total": 2}
    assert summarized["warnings"]
    assert "fetch_jd_detail" in summarized["warnings"][0]


def test_compact_profile_drops_large_raw_payload() -> None:
    profile = CareerProfile(
        who={"name": "张三"},
        have={
            "skills": [{"name": f"技能{i}", "evidence": "x" * 2000} for i in range(20)],
            "raw": "y" * 20000,
        },
        want={"target_role": "Agent 开发"},
        gap={
            "match_score": 60,
            "resume_optimization": {"resume_tips": ["z" * 2000] * 10},
            "skill_gaps": [{"skill": f"G{i}", "source": "JD"} for i in range(30)],
        },
    )
    compact = _compact_profile(profile)
    payload = json.dumps(compact, ensure_ascii=False)
    assert len(payload) < 4000
    assert "raw" not in compact["have"]
    assert len(compact["have"]["skills"]) == 6
    assert compact["gap"]["skill_gap_count"] == 30
