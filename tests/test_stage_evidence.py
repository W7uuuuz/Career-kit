"""Core v2 阶段 7：岗位与面经采集回归。

所有抓取函数均 monkeypatch，不联网；档案与 artifact 使用 tmp_path 隔离，
不读写真实 ~/.career-kit 或 ~/CareerKit。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths
from src.core.artifacts.models import (
    ArtifactMeta,
    CompanyEntry,
    CompanyPool,
    EvidenceRun,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import evidence
from src.core.stages.base import StageContext
from src.models import CareerProfile
from src.tools import evidence_tools, profile as profile_store

PROFILE = "tester"


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", data_dir)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", data_dir)
    return data_dir


@pytest.fixture()
def store(sandbox: Path) -> ArtifactStore:
    return ArtifactStore()


def _company(
    company_id: str,
    name: str,
    *,
    scrapable: bool = True,
    status: str = "confirmed",
    scrapers: list[str] | None = None,
) -> CompanyEntry:
    return CompanyEntry(
        id=company_id,
        name=name,
        tier="大厂",
        industry="互联网",
        scrapable=scrapable,
        scrapers=scrapers if scrapers is not None else [company_id],
        status=status,
    )


def _pool(
    store: ArtifactStore,
    *,
    companies: list[CompanyEntry] | None = None,
    confirmed: bool = True,
    profile_name: str = PROFILE,
    city: str = "北京",
) -> CompanyPool:
    entries = companies or [_company("bytedance", "字节跳动")]
    if not confirmed:
        for entry in entries:
            entry.status = "recommended"
    return CompanyPool(
        meta=ArtifactMeta(
            id=store.new_id("cp_"),
            stage=state_machine.STAGE_COMPANY_POOL,
            profile_name=profile_name,
            created_at=datetime.now().isoformat(),
            validation={"confirmed": confirmed},
        ),
        target_spec=TargetSpec(direction="AI 应用", role="AI Agent 开发", city=city),
        companies=entries,
    )


def _seed(
    store: ArtifactStore,
    pool: CompanyPool,
    *,
    profile_name: str = PROFILE,
    research: dict[str, Any] | None = None,
    who: dict[str, Any] | None = None,
) -> str:
    pool_id = store.save(pool)
    profile = CareerProfile(
        who=who or {"education": "本科"},
        research=research or {},
    )
    profile_store.save_profile(profile, profile_name)
    return pool_id


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    jobs: dict[str, Any],
    *,
    cases: Any = None,
    detail: Any = None,
) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {"search": [], "cases": [], "detail": []}

    def fake_search(company: str, **params: Any) -> dict[str, Any]:
        captured["search"].append((company, params))
        value = jobs.get(company, {"results": []})
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(company, **params)
        return value

    def fake_detail(url: str, company: str | None = None) -> dict[str, Any]:
        captured["detail"].append((url, company))
        if callable(detail):
            return detail(url, company)
        if isinstance(detail, dict):
            return detail.get(url, {"description": "详情正文"})
        return {"description": "详情正文"}

    def fake_cases(**kwargs: Any) -> dict[str, Any]:
        captured["cases"].append(kwargs)
        if callable(cases):
            return cases(**kwargs)
        return cases or {"cases": [], "warnings": [], "sources": {}}

    monkeypatch.setattr(evidence, "search_company_jobs", fake_search)
    monkeypatch.setattr(evidence, "get_job_detail", fake_detail)
    monkeypatch.setattr(evidence, "collect_cases", fake_cases)
    return captured


def _run(store: ArtifactStore, inputs: dict[str, Any] | None = None) -> Any:
    ctx = StageContext(profile_name=PROFILE, store=store)
    return evidence.run(ctx, inputs or {})


def _load(store: ArtifactStore, artifact_id: str) -> EvidenceRun:
    data = store.load(artifact_id)
    assert data is not None
    return EvidenceRun.model_validate(data)


def test_city_filter_url_dedupe_and_unknown_city(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store))
    jobs = {
        "bytedance": {
            "results": [
                {
                    "title": "AI Agent 工程师",
                    "location": "北京·海淀",
                    "url": "https://jobs/1",
                    "description": "负责 Agent 开发",
                },
                {
                    "title": "AI Agent 工程师（重复）",
                    "location": "北京",
                    "url": "https://jobs/1",
                    "description": "重复 URL",
                },
                {
                    "title": "后端工程师",
                    "location": "上海",
                    "url": "https://jobs/2",
                    "description": "上海岗位",
                },
                {
                    "title": "远程 Agent 工程师",
                    "location": "远程",
                    "url": "https://jobs/3",
                    "description": "远程岗位",
                },
                {
                    "title": "未写地点岗位",
                    "location": "",
                    "url": "https://jobs/4",
                    "description": "地点未知",
                },
            ]
        }
    }
    _patch_sources(monkeypatch, jobs)

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert {item.title for item in run.jd_items} == {
        "AI Agent 工程师",
        "远程 Agent 工程师",
    }
    assert run.counts["raw_jobs"] == 5
    assert run.counts["kept_jobs"] == 2
    assert run.counts["dropped_city"] == 2
    assert run.counts["unknown_city"] == 1
    assert run.counts["dropped_no_detail"] == 0
    assert all(item.detail_status == "ok" for item in run.jd_items)
    assert run.meta.source_status[0]["status"] == "ok"
    assert any("未知城市" in gap for gap in run.gaps)


def test_empty_location_kept_when_target_city_is_empty(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store, city=""))
    jobs = {
        "bytedance": {
            "results": [
                {"title": "未写地点岗位", "location": "", "url": "https://jobs/1",
                 "description": "地点未知"},
            ]
        }
    }
    _patch_sources(monkeypatch, jobs)

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert [item.title for item in run.jd_items] == ["未写地点岗位"]
    assert run.counts["dropped_city"] == 0
    assert run.counts["unknown_city"] == 0


def test_detail_fetch_success_and_drop_without_detail(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store))
    jobs = {
        "bytedance": {
            "results": [
                {"title": "有详情岗位", "location": "北京", "url": "https://jobs/ok"},
                {"title": "详情失败岗位", "location": "北京", "url": "https://jobs/fail"},
                {"title": "没有链接岗位", "location": "北京", "url": ""},
            ]
        }
    }
    _patch_sources(
        monkeypatch,
        jobs,
        detail={
            "https://jobs/ok": {"description": "完整 JD 正文"},
            "https://jobs/fail": {"error": "详情接口失败"},
        },
    )

    result = _run(store)

    run = _load(store, result.artifact_id)
    assert [item.title for item in run.jd_items] == ["有详情岗位"]
    assert run.jd_items[0].description == "完整 JD 正文"
    assert run.jd_items[0].detail_status == "ok"
    assert run.counts["dropped_no_detail"] == 2


def test_partial_source_failure_keeps_batch(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    companies = [
        _company("bytedance", "字节跳动"),
        _company("tencent", "腾讯"),
    ]
    _seed(store, _pool(store, companies=companies))
    jobs = {
        "bytedance": {
            "results": [
                {
                    "title": "Agent 工程师",
                    "location": "北京",
                    "url": "https://jobs/bd",
                    "description": "字节 JD",
                }
            ]
        },
        "tencent": RuntimeError("腾讯接口爆炸"),
    }
    _patch_sources(monkeypatch, jobs)

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert run.counts["companies_requested"] == 2
    assert run.counts["companies_fetched"] == 1
    statuses = {item["source"]: item for item in run.meta.source_status if item["scope"] == "jd"}
    assert statuses["tencent"]["status"] == "failed"
    assert "腾讯接口爆炸" in statuses["tencent"]["error"]
    assert any("tencent" in gap and "失败" in gap for gap in run.gaps)


def test_company_with_multiple_scrapers_merges_results(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    companies = [
        _company("alibaba", "阿里巴巴", scrapers=["alibaba", "alibaba_social"]),
    ]
    _seed(store, _pool(store, companies=companies))
    jobs = {
        "alibaba": {
            "results": [
                {
                    "title": "校招 Agent 工程师",
                    "location": "北京",
                    "url": "https://jobs/campus",
                }
            ]
        },
        "alibaba_social": {
            "results": [
                {
                    "title": "社招 Agent 工程师",
                    "location": "北京",
                    "url": "https://jobs/social",
                }
            ]
        },
    }
    captured = _patch_sources(monkeypatch, jobs)

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert sorted(slug for slug, _params in captured["search"]) == ["alibaba", "alibaba_social"]
    assert {item.title for item in run.jd_items} == {"校招 Agent 工程师", "社招 Agent 工程师"}
    assert {item.source for item in run.jd_items} == {"alibaba", "alibaba_social"}
    assert all(item.company_id == "alibaba" for item in run.jd_items)
    statuses = [item for item in run.meta.source_status if item["scope"] == "jd"]
    assert len(statuses) == 2
    assert {item["source"] for item in statuses} == {"alibaba", "alibaba_social"}
    assert all(item["status"] == "ok" for item in statuses)
    assert run.counts["companies_requested"] == 1
    assert run.counts["companies_fetched"] == 1
    assert {company for _url, company in captured["detail"]} == {"alibaba", "alibaba_social"}


def test_reuses_recent_research_by_url_and_title(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    research = {
        "generated_at": generated_at,
        "jd_samples": [
            {
                "company": "字节跳动",
                "title": "复用 JD",
                "location": "北京",
                "url": "https://research/jd/1",
                "description": "研究阶段已抓正文",
                "requirements": "Python",
                "source": "bytedance",
            }
        ],
        "cases": [
            {
                "company": "字节跳动",
                "title": "复用面经",
                "source": "nowcoder",
                "url": "https://research/case/1",
                "education_tag": "本科",
                "year": "2026",
                "highlights": ["一面考 Agent"],
            }
        ],
    }
    _seed(store, _pool(store), research=research)
    jobs = {
        "bytedance": {
            "results": [
                {
                    "title": "新抓 JD",
                    "location": "北京",
                    "url": "https://jobs/fresh",
                    "description": "新正文",
                }
            ]
        }
    }
    cases = {
        "cases": [
            {
                "title": "新面经",
                "source": "nowcoder",
                "url": "https://fresh/case/2",
                "highlights": ["二面考 RAG"],
                "background": {"company": "", "education_tag": "硕士", "year": "2027"},
            }
        ],
        "warnings": [],
        "sources": {"nowcoder": 1},
    }
    captured = _patch_sources(monkeypatch, jobs, cases=cases)

    result = _run(store)

    run = _load(store, result.artifact_id)
    assert run.counts["kept_jobs"] == 2
    assert run.counts["reused_jd"] == 1
    assert run.counts["fresh_jobs"] == 1
    assert "新抓" in result.message and "复用" in result.message
    assert run.counts["interviews"] == 2
    assert run.counts["reused_interviews"] == 1
    reused_jd = next(item for item in run.jd_items if item.reused)
    assert reused_jd.title == "复用 JD"
    assert reused_jd.company_id == "bytedance"
    reused_case = next(item for item in run.interview_items if item.reused)
    assert reused_case.title == "复用面经"
    assert reused_case.company_id == "bytedance"
    assert captured["search"][0][1] == {"limit": 5, "keyword": "AI Agent 开发", "city": "北京"}
    assert captured["cases"][0]["role"] == "AI Agent 开发"
    assert captured["cases"][0]["city"] == "北京"
    assert captured["cases"][0]["education"] == "本科"


def test_stale_or_invalid_research_is_not_reused(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    research = {
        "generated_at": stale,
        "jd_samples": [
            {
                "company": "字节跳动",
                "title": "过期 JD",
                "location": "北京",
                "url": "https://research/old",
                "description": "旧正文",
            }
        ],
        "cases": [],
    }
    _seed(store, _pool(store), research=research)
    _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "新 JD",
                        "location": "北京",
                        "url": "https://jobs/new",
                        "description": "正文",
                    }
                ]
            }
        },
    )

    result = _run(store)

    run = _load(store, result.artifact_id)
    assert run.counts["reused_jd"] == 0
    assert [item.title for item in run.jd_items] == ["新 JD"]


def test_interview_company_mapping_and_generic_fallback(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store))
    cases = {
        "cases": [
            {
                "title": "字节面经",
                "source": "nowcoder",
                "url": "https://cases/1",
                "highlights": ["考点 A"],
                "background": {"company": "字节跳动", "education_tag": "本科", "year": "2026"},
            },
            {
                "title": "小作坊面经",
                "source": "github",
                "url": "https://cases/2",
                "highlights": ["考点 B"],
                "background": {"company": "不存在的小作坊", "education_tag": "", "year": ""},
            },
        ],
        "warnings": [],
        "sources": {"nowcoder": 1, "github": 1},
    }
    _patch_sources(monkeypatch, {"bytedance": {"results": []}}, cases=cases)

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert run.jd_items == []
    assert run.counts["interviews"] == 2
    assert run.counts["kept_jobs"] == 0
    mapped = next(item for item in run.interview_items if item.title == "字节面经")
    assert mapped.company_id == "bytedance"
    assert mapped.company == "字节跳动"
    generic = next(item for item in run.interview_items if item.title == "小作坊面经")
    assert generic.company_id == ""
    assert generic.company == ""
    assert run.confidence == {"jd": "low", "interview": "low"}
    assert any("未采集到任何 JD" in gap for gap in run.gaps)


def test_artifact_core_state_and_report_files(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed(store, _pool(store))
    _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "Agent 工程师",
                        "location": "北京",
                        "url": "https://jobs/1",
                        "description": "岗位正文",
                    }
                ]
            }
        },
        cases={
            "cases": [
                {
                    "title": "面经 A",
                    "source": "nowcoder",
                    "url": "https://cases/1",
                    "highlights": ["考点"],
                    "background": {"company": "字节跳动", "education_tag": "本科", "year": "2026"},
                }
            ],
            "warnings": [],
            "sources": {"nowcoder": 1},
        },
    )

    result = _run(store)

    assert result.status == "ok"
    assert result.artifact_id.startswith("ev_")
    run = _load(store, result.artifact_id)
    assert run.meta.stage == state_machine.STAGE_EVIDENCE
    assert run.company_pool_id == store.latest(PROFILE, state_machine.STAGE_COMPANY_POOL)["meta"]["id"]

    latest = store.latest(PROFILE, state_machine.STAGE_EVIDENCE)
    assert latest is not None and latest["meta"]["id"] == result.artifact_id

    profile = profile_store.load_profile(PROFILE)
    assert profile.core_state["evidence_run_id"] == result.artifact_id
    assert profile.core_state["stage"] == state_machine.STAGE_EVIDENCE
    assert profile.core_state["updated_at"]

    paths_by_kind = run.report_paths
    assert set(paths_by_kind) == {"md", "html", "json"}
    for key, suffix in (("md", ".md"), ("html", ".html"), ("json", ".json")):
        report_path = Path(paths_by_kind[key])
        assert report_path.suffix == suffix
        assert report_path.exists()

    assert Path(paths_by_kind["md"]).parent.name == "证据池"
    assert "Agent 工程师" in Path(paths_by_kind["md"]).read_text(encoding="utf-8-sig")
    html_text = Path(paths_by_kind["html"]).read_text(encoding="utf-8")
    assert "Agent 工程师" in html_text
    assert 'name="career-kit-summary"' in html_text
    payload = json.loads(Path(paths_by_kind["json"]).read_text(encoding="utf-8"))
    assert payload["direction"] == "AI 应用"
    assert payload["counts"]["jd_samples"] == 1

    assets_root = tmp_path / "CareerKit"
    assert (assets_root / "index.html").exists()


def test_insufficient_data_does_not_save_artifact(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed(store, _pool(store))
    _patch_sources(monkeypatch, {"bytedance": {"results": []}})

    result = _run(store)

    assert result.status == "insufficient_data"
    assert result.artifact_id == ""
    assert store.latest(PROFILE, state_machine.STAGE_EVIDENCE) is None
    assert not (tmp_path / "CareerKit" / "tester" / "证据池").exists()


def test_unconfirmed_pool_is_rejected(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store, confirmed=False))
    _patch_sources(monkeypatch, {})

    result = _run(store)

    assert result.status == "failed"
    assert "尚未确认" in result.message
    assert store.latest(PROFILE, state_machine.STAGE_EVIDENCE) is None


def test_empty_pool_id_prefers_core_state(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_pool_id = _seed(store, _pool(store))
    store.save(_pool(store))
    profile = profile_store.load_profile(PROFILE)
    profile.core_state = {"company_pool_id": old_pool_id}
    profile_store.save_profile(profile, PROFILE)
    _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "Agent 工程师",
                        "location": "北京",
                        "url": "https://jobs/1",
                        "description": "正文",
                    }
                ]
            }
        },
    )

    result = _run(store)

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert run.company_pool_id == old_pool_id
    assert run.company_pool_id != store.latest(
        PROFILE, state_machine.STAGE_COMPANY_POOL
    )["meta"]["id"]


def test_explicit_pool_from_other_profile_is_rejected(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    bob_pool_id = store.save(_pool(store, profile_name="bob"))
    _seed(store, _pool(store))
    _patch_sources(monkeypatch, {})

    result = _run(store, {"company_pool_id": bob_pool_id})

    assert result.status == "failed"
    assert "不属于当前档案" in result.message
    assert store.latest(PROFILE, state_machine.STAGE_EVIDENCE) is None


async def test_mcp_tool_returns_summary(store: ArtifactStore, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(store, _pool(store, profile_name="default"), profile_name="default")
    _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "Agent 工程师",
                        "location": "北京",
                        "url": "https://jobs/1",
                        "description": "正文",
                    }
                ]
            }
        },
    )

    raw = await evidence_tools.collect_company_evidence()

    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["artifact_id"].startswith("ev_")
    assert payload["counts"]["kept_jobs"] == 1
    assert payload["next_tool"] == "analyze_company_requirements"
    assert set(payload["report_paths"]) == {"md", "html", "json"}
    assert "boss" not in payload


def test_include_boss_false_skips_boss(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store))
    captured = _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "官方 Agent 工程师",
                        "location": "北京",
                        "url": "https://jobs/official",
                        "description": "官方正文",
                    }
                ]
            },
            "boss": {
                "results": [
                    {
                        "title": "BOSS Agent 工程师",
                        "company": "字节跳动",
                        "location": "北京",
                        "url": "https://zhipin/job/1",
                        "description": "BOSS 正文",
                    }
                ]
            },
        },
    )

    result = _run(store)

    assert result.status == "ok"
    assert [slug for slug, _params in captured["search"]] == ["bytedance"]
    run = _load(store, result.artifact_id)
    assert all(item["source"] != "boss" for item in run.meta.source_status)
    assert all(item.source != "boss" for item in run.jd_items)


async def test_mcp_tool_boss_requires_confirmation(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store, profile_name="default"), profile_name="default")

    raw = await evidence_tools.collect_company_evidence(include_boss=True)

    payload = json.loads(raw)
    assert payload["isError"] is True
    assert payload["code"] == "CONFIRMATION_REQUIRED"
    assert "BOSS 直聘" in payload["details"]["question"]
    assert payload["details"]["login_tool"] == "boss_login"
    assert "src.scrapers.boss.login" in payload["details"]["login_command"]
    assert "user_instruction" in payload["details"]


async def test_mcp_tool_boss_requires_login(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store, profile_name="default"), profile_name="default")
    monkeypatch.setattr(evidence_tools, "boss_has_valid_cookies", lambda: False)

    raw = await evidence_tools.collect_company_evidence(
        include_boss=True, boss_confirmed=True
    )

    payload = json.loads(raw)
    assert payload["isError"] is True
    assert payload["code"] == "LOGIN_REQUIRED"
    assert payload["details"]["next_tool"] == "boss_login"
    assert payload["details"]["action"] == "boss_login"
    assert "question" not in payload["details"]
    assert "src.scrapers.boss.login" in payload["details"]["login_command"]


async def test_mcp_tool_boss_merges_jobs_with_mapping_and_dedupe(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store, profile_name="default"), profile_name="default")
    captured = _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "官方 Agent 工程师",
                        "company": "字节跳动",
                        "location": "北京",
                        "url": "https://jobs/official",
                        "description": "官方正文",
                    }
                ]
            },
            "boss": {
                "results": [
                    {
                        "title": "BOSS Agent 工程师",
                        "company": "字节跳动",
                        "location": "北京",
                        "url": "https://zhipin/job/1",
                        "salary": "25-45K",
                        "description": "BOSS 正文",
                        "detail_status": "list_only",
                    },
                    {
                        "title": "BOSS 小厂 Agent",
                        "company": "某未收录小厂",
                        "location": "北京",
                        "url": "https://zhipin/job/2",
                        "salary": "10-20K",
                        "detail_status": "list_only",
                    },
                    {
                        "title": "重复 URL",
                        "company": "字节跳动",
                        "location": "北京",
                        "url": "https://jobs/official",
                        "description": "重复岗位",
                    },
                ]
            },
        },
    )
    monkeypatch.setattr(evidence_tools, "boss_has_valid_cookies", lambda: True)

    raw = await evidence_tools.collect_company_evidence(
        include_boss=True, boss_confirmed=True
    )

    payload = json.loads(raw)
    assert payload["status"] == "ok"
    assert payload["counts"]["kept_jobs"] == 3
    assert payload["counts"]["boss_jobs"] == 2
    assert payload["boss"]["jd_count"] == 2
    assert payload["boss"]["returned"] == 3
    assert payload["boss"]["status"] == "ok"

    boss_status = [
        item
        for item in payload["source_status"]
        if item["source"] == "boss" and item["scope"] == "jd"
    ]
    assert len(boss_status) == 1
    assert boss_status[0]["status"] == "ok"

    run = _load(store, payload["artifact_id"])
    boss_items = [item for item in run.jd_items if item.source == "boss"]
    assert {item.title for item in boss_items} == {"BOSS Agent 工程师", "BOSS 小厂 Agent"}

    mapped = next(item for item in boss_items if item.title == "BOSS Agent 工程师")
    assert mapped.company_id == "bytedance"
    assert mapped.tier == "大厂"
    assert mapped.salary == "25-45K"

    unmapped = next(item for item in boss_items if item.title == "BOSS 小厂 Agent")
    assert unmapped.company_id == ""
    assert unmapped.tier == "未收录"
    assert unmapped.salary == "10-20K"

    # BOSS list-only：不补详情、不剔除，保留列表字段并计入缺口。
    assert all(item.detail_status == "list_only" for item in boss_items)
    assert run.counts["list_only"] == 2
    assert run.counts["dropped_no_detail"] == 0
    assert all("zhipin" not in url for url, _company in captured["detail"])
    assert any("list-only" in gap for gap in run.gaps)


def test_list_only_empty_location_is_still_city_filtered(
    store: ArtifactStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store, _pool(store))
    _patch_sources(
        monkeypatch,
        {
            "bytedance": {
                "results": [
                    {
                        "title": "官方 Agent 工程师",
                        "location": "北京",
                        "url": "https://jobs/official",
                        "description": "官方正文",
                    }
                ]
            },
            "boss": {
                "results": [
                    {
                        "title": "BOSS 地点未知 Agent",
                        "company": "字节跳动",
                        "location": "",
                        "url": "https://zhipin/job/1",
                        "salary": "25-45K",
                        "detail_status": "list_only",
                    }
                ]
            },
        },
    )

    result = _run(store, {"include_boss": True, "boss_confirmed": True})

    assert result.status == "ok"
    run = _load(store, result.artifact_id)
    assert [item.title for item in run.jd_items] == ["官方 Agent 工程师"]
    assert run.counts["dropped_city"] == 1
    assert run.counts["unknown_city"] == 1
    assert run.counts["list_only_dropped_city"] == 1
    assert run.counts["list_only_kept"] == 0
    assert any(
        "list-only" in gap and "城市硬筛" in gap for gap in run.gaps
    )

