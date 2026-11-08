"""Core v2 阶段 8 回归：确定性统计、硬门槛与 LLM 数字防篡改。

所有用例使用 tmp_path 隔离数据目录，不联网、不读写真实 ~/.career-kit。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths
from src.core.artifacts.models import (
    ArtifactMeta,
    EvidenceRun,
    InterviewEvidence,
    JDEvidence,
    RequirementProfile,
    TargetSpec,
)
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import requirements
from src.core.stages.base import StageContext
from src.models import CareerProfile
from src.tools import profile as profile_store, requirement_tools


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    profile_store.save_profile(CareerProfile(), "alice")
    profile_store.set_active_profile_name("alice")
    return root


@pytest.fixture()
def store(isolated: Path) -> ArtifactStore:
    return ArtifactStore()


def _jd(
    jd_id: str,
    company_id: str,
    company: str,
    tier: str,
    title: str,
    requirements_text: str,
    description: str = "",
    source: str | None = None,
) -> JDEvidence:
    return JDEvidence(
        id=jd_id,
        company_id=company_id,
        company=company,
        tier=tier,
        title=title,
        description=description,
        requirements=requirements_text,
        source=source if source is not None else f"https://example.com/{jd_id}",
        detail_status="ok",
    )


def _default_jd_items() -> list[JDEvidence]:
    return [
        _jd(
            "JD001", "bytedance", "字节跳动", "大厂", "AI Agent 工程师",
            "本科及以上，3年以上经验；熟悉 Python、LangGraph、RAG、Agent、LLM、Docker",
        ),
        _jd(
            "JD002", "bytedance", "字节跳动", "大厂", "大模型应用工程师",
            "本科及以上，2年经验；Python、RAG、Agent、LLM、Prompt、微调",
        ),
        _jd(
            "JD003", "meituan", "美团", "中厂", "后端开发工程师",
            "硕士及以上，1-3年经验；Java、Go、MySQL、Redis、微服务、高并发",
        ),
        _jd(
            "JD004", "meituan", "美团", "中厂", "搜索算法工程师",
            "硕士及以上，应届毕业生；Python、搜索、推荐、NLP、Transformer",
        ),
        _jd(
            "JD005", "kuaishou", "快手", "中厂", "Agent 平台工程师",
            "本科及以上，3年经验；Python、Agent、LangChain、Kubernetes、高并发",
        ),
    ]


def _default_interview_items() -> list[InterviewEvidence]:
    return [
        InterviewEvidence(
            id="IV001",
            company_id="bytedance",
            company="字节跳动",
            title="字节 Agent 一面",
            source="nowcoder",
            url="https://example.com/iv1",
            content="手撕 Transformer；聊了 Python、RAG、LangGraph 项目",
            highlights=["Python", "RAG"],
        ),
        InterviewEvidence(
            id="IV002",
            company_id="meituan",
            company="美团",
            title="美团后端面经",
            source="nowcoder",
            url="https://example.com/iv2",
            content="重点问 Java、MySQL、Redis、高并发、微服务",
            highlights=["Java", "高并发"],
        ),
        InterviewEvidence(
            id="IV003",
            title="通用 Agent 面经",
            source="nowcoder",
            url="https://example.com/iv3",
            content="Agent 项目深挖，Python 与 RAG 落地",
            highlights=["Agent"],
        ),
    ]


def _run_in_memory(
    jd_items: list[JDEvidence] | None = None,
    interview_items: list[InterviewEvidence] | None = None,
) -> EvidenceRun:
    return EvidenceRun(
        meta=ArtifactMeta(
            id="ev_test",
            stage=state_machine.STAGE_EVIDENCE,
            profile_name="alice",
            created_at=datetime.now().isoformat(),
        ),
        target_spec=TargetSpec(role="AI Agent 开发", city="北京"),
        company_pool_id="cp_test",
        jd_items=_default_jd_items() if jd_items is None else jd_items,
        interview_items=(
            _default_interview_items() if interview_items is None else interview_items
        ),
    )


def _save_run(
    store: ArtifactStore,
    jd_items: list[JDEvidence] | None = None,
    interview_items: list[InterviewEvidence] | None = None,
) -> EvidenceRun:
    run = _run_in_memory(jd_items, interview_items)
    run.meta.id = store.new_id("ev")
    store.save(run)
    return run


def _find(items: list[requirements.RequirementItem], term: str) -> requirements.RequirementItem:
    for item in items:
        if item.term == term:
            return item
    raise AssertionError(f"未找到条目：{term}；现有：{[i.term for i in items]}")


def _find_none(
    items: list[requirements.RequirementItem], term: str
) -> requirements.RequirementItem | None:
    for item in items:
        if item.term == term:
            return item
    return None


def _parse(raw: str) -> dict:
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert not data.get("isError"), f"工具返回错误：{data}"
    return data


def test_statistics_counts_coverage_and_wilson() -> None:
    stats = requirements.compute_statistics(_run_in_memory())

    assert stats["sample_size_jd"] == 5
    assert stats["sample_size_interview"] == 3
    assert stats["confidence_jd"] == "low"
    assert stats["confidence_interview"] == "low"

    python_item = _find(stats["high_frequency"], "Python")
    assert python_item.jd_count == 4
    assert python_item.jd_frequency == 0.8
    assert python_item.company_count == 3
    assert python_item.company_frequency == 1.0
    assert python_item.companies == ["字节跳动", "美团", "快手"]
    assert python_item.evidence_ids == ["JD001", "JD002", "JD004", "JD005"]
    assert python_item.tier_breakdown == {"大厂": 2, "中厂": 2}
    assert python_item.ci_low is not None and python_item.ci_high is not None
    assert 0.0 < python_item.ci_low < 0.8 < python_item.ci_high <= 1.0

    agent_item = _find(stats["high_frequency"], "Agent")
    assert agent_item.jd_count == 3
    assert agent_item.jd_frequency == 0.6
    assert agent_item.company_count == 2

    rag_item = _find(stats["nice_to_have"], "RAG")
    assert rag_item.jd_count == 2
    assert rag_item.jd_frequency == 0.4
    assert rag_item.company_count == 1
    assert rag_item.company_frequency == round(1 / 3, 4)
    assert _find_none(stats["high_frequency"], "RAG") is None

    concurrency_item = _find(stats["nice_to_have"], "高并发")
    assert concurrency_item.jd_count == 2
    assert concurrency_item.company_count == 2

    specific_rag = _find(stats["company_specific"], "RAG（字节跳动）")
    assert specific_rag.jd_count == 2
    assert specific_rag.company_count == 1
    assert specific_rag.companies == ["字节跳动"]
    assert specific_rag.evidence_ids == ["JD001", "JD002"]
    assert specific_rag.company_frequency == round(1 / 3, 4)

    assert _find(stats["company_specific"], "LLM（字节跳动）")
    assert _find(stats["company_specific"], "Agent（字节跳动）")


def test_interview_topics_are_separate_and_use_interview_sample() -> None:
    stats = requirements.compute_statistics(_run_in_memory())
    topics = stats["interview_topics"]

    python_topic = _find(topics, "Python")
    assert python_topic.jd_count == 2
    assert python_topic.jd_frequency == round(2 / 3, 4)
    assert python_topic.company_count == 2
    assert python_topic.companies == ["字节跳动", "未知公司"]
    assert python_topic.evidence_ids == ["IV001", "IV003"]
    assert python_topic.ci_low is not None and python_topic.ci_high is not None

    rag_topic = _find(topics, "RAG")
    assert rag_topic.jd_count == 2
    assert rag_topic.evidence_ids == ["IV001", "IV003"]

    assert _find_none(topics, "LLM") is None


def test_hard_requirements_are_per_jd_not_aggregated() -> None:
    stats = requirements.compute_statistics(_run_in_memory())
    hard = {item.evidence_id: item for item in stats["hard_requirements"]}

    assert len(hard) == 5
    assert "本科" in hard["JD001"].education
    assert "3年" in hard["JD001"].experience
    assert "硕士" in hard["JD003"].education
    assert "1-3年" in hard["JD003"].experience
    assert "应届" in hard["JD004"].experience
    assert hard["JD001"].company == "字节跳动"
    assert hard["JD001"].title == "AI Agent 工程师"


def test_wilson_interval_formula_bounds() -> None:
    low, high = requirements.wilson_interval(4, 5)
    assert low is not None and high is not None
    assert 0.0 < low < 0.8 < high <= 1.0

    low_full, high_full = requirements.wilson_interval(5, 5)
    assert low_full is not None and low_full > 0.0
    assert high_full == 1.0

    assert requirements.wilson_interval(0, 0) == (None, None)
    assert requirements.wilson_interval(-1, 5) == (None, None)


def test_analyze_tool_saves_draft_and_updates_core_state(store: ArtifactStore) -> None:
    run = _save_run(store)
    result = _parse(requirement_tools.analyze_company_requirements(run.meta.id))

    profile_id = result["requirement_profile_id"]
    assert profile_id.startswith("rp_")
    assert result["evidence_run_id"] == run.meta.id
    assert result["sample_size"] == {"jd": 5, "interview": 3}
    assert result["confidence"] == {"jd": "low", "interview": "low"}
    assert "interpretation" in result["analysis_prompt"]
    assert "必备项" not in result["analysis_prompt"] or "不要使用「必备项」" in result[
        "analysis_prompt"
    ]

    draft = store.load(profile_id)
    assert draft is not None
    assert draft["meta"]["stage"] == requirements.STAGE_ID
    assert draft["interpretation"] == {}
    assert draft["sample_size_jd"] == 5

    profile = profile_store.load_profile("alice")
    assert profile.core_state["requirement_profile_id"] == profile_id
    assert profile.core_state["stage"] == "requirement"
    assert profile.core_state["updated_at"]


def test_analyze_tool_uses_latest_evidence_when_id_empty(store: ArtifactStore) -> None:
    run = _save_run(store)
    result = _parse(requirement_tools.analyze_company_requirements())
    assert result["evidence_run_id"] == run.meta.id


def test_analyze_tool_rejects_missing_evidence(store: ArtifactStore) -> None:
    result = json.loads(requirement_tools.analyze_company_requirements("ev_missing"))
    assert result["isError"] is True
    assert result["code"] == "EVIDENCE_RUN_NOT_FOUND"


def test_stage_rejects_evidence_from_other_profile(store: ArtifactStore) -> None:
    run = _run_in_memory()
    run.meta.profile_name = "bob"
    run.meta.id = store.new_id("ev")
    store.save(run)

    ctx = StageContext(profile_name="alice", store=store)
    result = requirements.run(ctx, {"evidence_run_id": run.meta.id})

    assert result.status == "failed"
    assert "不属于当前档案" in result.message
    assert store.latest("alice", state_machine.STAGE_REQUIREMENT) is None


def test_save_requirement_profile_accepts_interpretation_and_keeps_numbers(
    store: ArtifactStore,
) -> None:
    run = _save_run(store)
    analyzed = _parse(requirement_tools.analyze_company_requirements(run.meta.id))
    profile_id = analyzed["requirement_profile_id"]

    interpretation = {
        "summary": "Python 与 Agent 是高频共性要求",
        "priorities": ["优先补齐 RAG 项目证据"],
        "company_notes": ["字节跳动对 RAG 的要求更集中"],
        "risks": ["JD 样本仅 5 条，置信度低"],
        "notes": ["引用 JD001/JD002"],
    }
    saved = _parse(
        requirement_tools.save_requirement_profile(
            json.dumps(
                {"requirement_profile_id": profile_id, "interpretation": interpretation},
                ensure_ascii=False,
            )
        )
    )

    assert saved["version"] == 2
    assert saved["revalidated"] is True
    assert saved["interpretation"]["summary"] == interpretation["summary"]

    stored = store.load(profile_id)
    assert stored is not None
    assert stored["interpretation"] == interpretation
    assert stored["meta"]["version"] == 2
    assert stored["sample_size_jd"] == analyzed["sample_size"]["jd"]
    assert stored["sample_size_interview"] == analyzed["sample_size"]["interview"]
    assert stored["confidence_jd"] == analyzed["confidence"]["jd"]
    assert stored["confidence_interview"] == analyzed["confidence"]["interview"]
    assert stored["high_frequency"] == analyzed["high_frequency"]
    assert stored["nice_to_have"] == analyzed["nice_to_have"]
    assert stored["company_specific"] == analyzed["company_specific"]
    assert stored["interview_topics"] == analyzed["interview_topics"]
    assert stored["hard_requirements"] == analyzed["hard_requirements"]

    profile = profile_store.load_profile("alice")
    assert profile.core_state["requirement_profile_id"] == profile_id


def test_save_requirement_profile_rejects_numeric_or_unknown_fields(
    store: ArtifactStore,
) -> None:
    run = _save_run(store)
    analyzed = _parse(requirement_tools.analyze_company_requirements(run.meta.id))
    profile_id = analyzed["requirement_profile_id"]

    cases = [
        (
            {"requirement_profile_id": profile_id, "interpretation": {"high_frequency": []}},
            "INVALID_INTERPRETATION",
        ),
        (
            {"requirement_profile_id": profile_id, "interpretation": {"gaps": ["x"]}},
            "INVALID_INTERPRETATION",
        ),
        (
            {
                "requirement_profile_id": profile_id,
                "interpretation": {"summary": "合法"},
                "high_frequency": [],
            },
            "INVALID_PARAM",
        ),
        (
            {"requirement_profile_id": profile_id, "interpretation": []},
            "INVALID_PARAM",
        ),
        (
            {"interpretation": {"summary": "缺少 id"}},
            "INVALID_PARAM",
        ),
        (
            {"requirement_profile_id": "rp_missing", "interpretation": {"summary": "x"}},
            "REQUIREMENT_PROFILE_NOT_FOUND",
        ),
    ]
    for payload, expected_code in cases:
        result = json.loads(
            requirement_tools.save_requirement_profile(
                json.dumps(payload, ensure_ascii=False)
            )
        )
        assert result["isError"] is True, payload
        assert result["code"] == expected_code, payload

    invalid_json = json.loads(requirement_tools.save_requirement_profile("{oops"))
    assert invalid_json["isError"] is True
    assert invalid_json["code"] == "INVALID_JSON"

    draft = store.load(profile_id)
    assert draft is not None
    assert draft["interpretation"] == {}
    assert draft["meta"]["version"] == 1


def test_low_sample_confidence_and_gaps(store: ArtifactStore) -> None:
    jd_items = [
        _jd(
            "JD001", "acme", "甲公司", "小厂", "后端开发",
            "", description="Python", source="",
        )
    ]
    run = _save_run(store, jd_items=jd_items, interview_items=[])
    result = _parse(requirement_tools.analyze_company_requirements(run.meta.id))

    assert result["confidence"] == {"jd": "low", "interview": "low"}
    assert result["interview_topics"] == []
    assert result["hard_requirements"] == []
    gaps = result["gaps"]
    assert any("JD 样本仅 1 条" in gap for gap in gaps)
    assert any("没有面经样本" in gap for gap in gaps)
    assert any("缺少 requirements" in gap for gap in gaps)
    assert any("缺少来源链接" in gap for gap in gaps)


def test_stage_run_resolves_latest_and_validate_rejects_tampering(
    store: ArtifactStore,
) -> None:
    _save_run(store)
    ctx = StageContext(profile_name="alice", store=store)
    result = requirements.run(ctx, {"evidence_run_id": ""})
    assert result.status == "ok"
    assert result.artifact_id.startswith("rp_")
    assert result.warnings

    draft = store.load(result.artifact_id)
    assert draft is not None
    draft["high_frequency"][0]["jd_count"] += 1
    tampered = RequirementProfile.model_validate(draft)
    issues = requirements.validate(tampered)
    assert issues
    assert any("数字必须由代码计算" in issue or "jd_count" in issue for issue in issues)

    draft = store.load(result.artifact_id)
    assert draft is not None
    tampered = RequirementProfile.model_validate(draft)
    tampered.interpretation = {"high_frequency": []}
    issues = requirements.validate(tampered)
    assert any("interpretation 只允许" in issue for issue in issues)
