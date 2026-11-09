"""投递清单回归——城市硬筛、软打分、去重、已投递排除与 artifact 落库。

所有用例使用 tmp_path 隔离档案与 artifact 数据库，不联网、不读写真实
~/.career-kit；资产目录由 tests/conftest.py 的 autouse fixture 重定向。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths  # noqa: E402
from src.core import sync  # noqa: E402
from src.core.artifacts.models import (  # noqa: E402
    ArtifactMeta,
    EvidenceRun,
    JDEvidence,
    RequirementItem,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.models import Application, CareerProfile  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402
from src.tools.application_list_tools import build_application_list  # noqa: E402

PROFILE_NAME = "default"


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    return root


def _meta(store: ArtifactStore, prefix: str, stage: str) -> ArtifactMeta:
    return ArtifactMeta(
        id=store.new_id(prefix),
        stage=stage,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
    )


def _profile() -> CareerProfile:
    return CareerProfile(
        who={"name": "张三", "education": "双非本", "city": "北京"},
        have={"skills": ["Python", "LangChain"]},
        want={
            "target_role": "AI Agent 开发",
            "city": "北京",
            "target_tiers": ["大厂"],
            "bridge_tiers": ["中厂"],
        },
        applications=[
            Application(
                id="app_001",
                company="字节跳动",
                role="AI Agent 工程师（已投）",
                status="applied",
            )
        ],
    )


def _jd(
    jd_id: str,
    company: str,
    tier: str,
    title: str,
    *,
    location: str = "",
    salary: str = "",
    url: str = "",
    summary: str = "",
    description: str = "",
    requirements: str = "",
    company_id: str = "",
) -> JDEvidence:
    return JDEvidence(
        id=jd_id,
        company_id=company_id,
        company=company,
        tier=tier,
        title=title,
        location=location,
        salary=salary,
        url=url,
        summary=summary,
        description=description,
        requirements=requirements,
        source="test",
        detail_status="ok",
    )


def _seed() -> tuple[CareerProfile, EvidenceRun, RequirementProfile]:
    profile_store.save_profile(_profile(), PROFILE_NAME)
    store = ArtifactStore()
    jd_items = [
        _jd(
            "JD001",
            "字节跳动",
            "大厂",
            "AI Agent 工程师",
            location="北京",
            salary="30-50K",
            url="https://a/1",
            summary="Python LangChain RAG",
            requirements="本科及以上",
            company_id="bytedance",
        ),
        _jd(
            "JD002",
            "美团",
            "大厂",
            "后端开发工程师",
            location="上海",
            salary="25-40K",
            url="https://b/2",
            summary="Java Spring",
            requirements="本科及以上",
            company_id="meituan",
        ),
        _jd(
            "JD003",
            "小米",
            "中厂",
            "AI Agent 开发",
            location="远程",
            salary="20-30K",
            url="https://c/3",
            summary="Python Agent",
            requirements="本科及以上",
            company_id="xiaomi",
        ),
        _jd(
            "JD004",
            "字节跳动",
            "大厂",
            "AI Agent 工程师（重复）",
            location="北京",
            salary="30-50K",
            url="https://a/1",
            summary="Python LangChain RAG",
            requirements="本科及以上",
            company_id="bytedance",
        ),
        _jd(
            "JD005",
            "字节跳动",
            "大厂",
            "AI Agent 工程师（已投）",
            location="北京",
            salary="25-40K",
            url="https://e/5",
            summary="Python Agent",
            requirements="本科及以上",
            company_id="bytedance",
        ),
        _jd(
            "JD006",
            "华为",
            "大厂",
            "AI Agent 工程师（城市未知）",
            url="https://f/6",
            summary="Python LangChain",
            company_id="huawei",
        ),
        _jd(
            "JD007",
            "创业公司",
            "小厂",
            "数据分析师",
            location="全国",
            url="https://g/7",
            description="SQL Python",
            company_id="startup",
        ),
    ]
    evidence = EvidenceRun(
        meta=_meta(store, "ev_", "evidence"),
        target_spec=TargetSpec(
            role="AI Agent 开发",
            city="北京",
            target_tiers=["大厂"],
            bridge_tiers=["中厂"],
        ),
        company_pool_id="cp_test",
        jd_items=jd_items,
    )
    evidence_id = store.save(evidence)

    requirement = RequirementProfile(
        meta=_meta(store, "rp_", "requirement"),
        evidence_run_id=evidence_id,
        sample_size_jd=len(jd_items),
        high_frequency=[
            RequirementItem(
                term="Python",
                category="语言/工程",
                jd_count=2,
                jd_frequency=0.5,
                company_count=1,
                company_frequency=0.5,
            ),
            RequirementItem(
                term="RAG",
                category="AI/算法",
                jd_count=2,
                jd_frequency=0.5,
                company_count=1,
                company_frequency=0.5,
            ),
            RequirementItem(
                term="Docker",
                category="语言/工程",
                jd_count=2,
                jd_frequency=0.5,
                company_count=1,
                company_frequency=0.5,
            ),
        ],
    )
    requirement_id = store.save(requirement)

    profile = profile_store.load_profile(PROFILE_NAME)
    state = dict(profile.core_state or {})
    state["evidence_run_id"] = evidence_id
    state["requirement_profile_id"] = requirement_id
    profile.core_state = state
    profile_store.save_profile(profile, PROFILE_NAME)
    return profile, evidence, requirement


def _build(**kwargs: Any) -> dict[str, Any]:
    payload = json.loads(build_application_list(**kwargs))
    assert not payload.get("isError"), payload
    return payload


def _by_title(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["title"]: item for item in payload["candidates"]}


def test_city_is_hard_filter_and_empty_location_is_dropped(data_dir: Path) -> None:
    _seed()

    payload = _build(city="北京", role="AI Agent 开发")

    titles = [item["title"] for item in payload["candidates"]]
    assert "后端开发工程师" not in titles, "上海岗位应被城市硬筛剔除"
    assert "AI Agent 工程师" in titles, "北京岗位应保留"
    assert "AI Agent 工程师（城市未知）" not in titles, "空 location 在硬筛时必须剔除"
    assert payload["dropped_city"] == 2, "上海与空 location 都计入城市剔除"
    assert payload["unknown_city"] == 1, "空 location 计入未知城市缺口"


def test_city_keep_keeps_empty_location_only_without_target() -> None:
    from src.core.application_list import _city_keep

    assert _city_keep("", "") == (True, False), "目标城市为空时保留所有岗位"
    assert _city_keep("", "北京") == (False, True), "目标城市非空时空 location 剔除且标记未知"
    assert _city_keep("北京", "北京") == (True, False)


def test_role_skill_education_tier_and_salary_scoring(data_dir: Path) -> None:
    _seed()

    payload = _build(top=30, min_score=0)
    by_title = _by_title(payload)

    first = by_title["AI Agent 工程师"]
    assert first["match_score"] == 92
    assert first["tier"] == "大厂"
    assert first["salary"] == "30-50K"
    assert first["url"] == "https://a/1"
    assert first["status"] == "pending"
    assert "方向命中：agent、ai" in first["reasons"]
    assert "城市命中：北京" in first["reasons"]
    assert "技能命中 2/2：Python、LangChain" in first["reasons"]
    assert "学历匹配：双非本 vs 要求 本科" in first["reasons"]
    assert "目标档位：大厂" in first["reasons"]
    assert "已标注薪资" in first["reasons"]
    assert "未覆盖高频要求：Docker" in first["gaps"]

    bridge = by_title["AI Agent 开发"]
    assert bridge["match_score"] == 93
    assert "远程/全国岗位" in bridge["reasons"]
    assert "桥接档位：中厂" in bridge["reasons"]
    assert "技能命中 1/2：Python" in bridge["reasons"]
    assert "技能缺口：LangChain" in bridge["gaps"]

    data_role = by_title["数据分析师"]
    assert data_role["match_score"] == 43
    assert "方向未命中：AI Agent 开发" in data_role["gaps"]
    assert "非目标档位：小厂" in data_role["gaps"]
    assert "未标注薪资" in data_role["gaps"]


def test_sorting_top_and_min_score(data_dir: Path) -> None:
    _seed()

    payload = _build(top=2, min_score=90)

    assert payload["candidate_count"] == 2
    assert [item["title"] for item in payload["candidates"]] == [
        "AI Agent 开发",
        "AI Agent 工程师",
    ]
    assert [item["match_score"] for item in payload["candidates"]] == [93, 92]
    assert [item["id"] for item in payload["candidates"]] == ["APP001", "APP002"]


def test_url_dedupe_keeps_single_candidate(data_dir: Path) -> None:
    _seed()

    payload = _build(top=30, min_score=0)

    urls = [item["url"] for item in payload["candidates"]]
    assert urls.count("https://a/1") == 1
    titles = [item["title"] for item in payload["candidates"]]
    assert "AI Agent 工程师（重复）" not in titles


def test_applied_candidates_excluded_by_default_and_included_on_request(data_dir: Path) -> None:
    _seed()

    default_payload = _build(top=30, min_score=0)
    assert "AI Agent 工程师（已投）" not in _by_title(default_payload)
    assert default_payload["candidate_count"] == 3

    with_applied = _build(top=30, min_score=0, include_applied=True)
    applied = _by_title(with_applied)["AI Agent 工程师（已投）"]
    assert applied["status"] == "applied"
    assert applied["match_score"] == 82
    assert with_applied["candidate_count"] == 4


def test_candidates_persist_to_application_state_and_reports(data_dir: Path) -> None:
    _seed()

    payload = _build(top=30, min_score=0)

    store = ArtifactStore()
    profile = profile_store.load_profile(PROFILE_NAME)
    artifact_id = profile.core_state[sync.KEY_APPLICATIONS]
    assert artifact_id == payload["artifact_id"]
    artifact = store.load(artifact_id)
    assert artifact is not None
    assert len(artifact["candidates"]) == payload["candidate_count"]
    assert artifact["candidates"][0]["id"] == "APP001"
    assert len(artifact["applications"]) == 1

    report_paths = payload["report_paths"]
    for path in report_paths.values():
        assert Path(path).exists(), f"报告文件未生成：{path}"
    report = json.loads(Path(report_paths["json"]).read_text(encoding="utf-8"))
    assert report["counts"]["candidates"] == payload["candidate_count"]
    assert len(report["candidates"]) == payload["candidate_count"]


def test_sync_application_state_keeps_candidates_when_applications_empty(
    data_dir: Path,
) -> None:
    _seed()
    payload = _build(top=30, min_score=0)

    profile = profile_store.load_profile(PROFILE_NAME)
    profile.applications = []
    profile_store.save_profile(profile, PROFILE_NAME)

    artifact_id = sync.sync_application_state(PROFILE_NAME)

    assert artifact_id.startswith("as_")
    artifact = ArtifactStore().load(artifact_id)
    assert artifact is not None
    assert artifact["applications"] == []
    assert len(artifact["candidates"]) == payload["candidate_count"]
    assert ArtifactStore().latest(PROFILE_NAME, sync.STAGE_APPLICATIONS)["candidates"]


def test_record_and_delete_updates_candidate_status(data_dir: Path) -> None:
    _seed()
    payload = _build()
    candidate = payload["candidates"][0]

    from src.tools.application_tools import delete_application, record_application

    recorded = json.loads(
        record_application(company=candidate["company"], role=candidate["title"])
    )
    assert not recorded.get("isError"), recorded
    app_id = recorded.get("next_app_id_hint") or recorded["application"]["id"]

    state = ArtifactStore().latest(PROFILE_NAME, sync.STAGE_APPLICATIONS)
    matched = [
        item for item in state["candidates"]
        if item["company"] == candidate["company"] and item["title"] == candidate["title"]
    ]
    assert matched and matched[0]["status"] == "applied"

    deleted = json.loads(delete_application(application_id=app_id))
    assert not deleted.get("isError"), deleted

    state = ArtifactStore().latest(PROFILE_NAME, sync.STAGE_APPLICATIONS)
    matched = [
        item for item in state["candidates"]
        if item["company"] == candidate["company"] and item["title"] == candidate["title"]
    ]
    assert matched and matched[0]["status"] == "pending"


def test_missing_evidence_returns_error(data_dir: Path) -> None:
    profile_store.save_profile(_profile(), PROFILE_NAME)

    payload = json.loads(build_application_list())

    assert payload["isError"] is True
    assert payload["code"] == "MISSING_DATA"
    assert "collect_company_evidence" in payload["message"]
