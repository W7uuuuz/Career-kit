"""Core v2 sync 层回归——旧档案数据 → 新 artifact + core_state。

所有用例使用 tmp_path 隔离数据目录，不联网、不读写真实 ~/.career-kit。
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths  # noqa: E402
from src.core import sync  # noqa: E402
from src.core.artifacts.models import ArtifactMeta, ExecutionPlan  # noqa: E402
from src.core.artifacts.store import ArtifactStore  # noqa: E402
from src.models import Application, CareerProfile, CheckIn, Task  # noqa: E402
from src.tools import profile as profile_store  # noqa: E402

PROFILE_NAME = "alice"
ID_PATTERNS = {
    "pf": "profile",
    "ts": "target",
    "mb": "market_baseline",
    "gr": "gap",
    "bp": "baseline_plan",
    "es": "execution",
    "as": "applications",
    "rr": "review",
}


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(paths, "PROFILE_DIR", root)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", root)
    return root


def _roadmap() -> dict[str, Any]:
    return {
        "roadmap": {
            "strategy_summary": "先补基础再投递",
            "phases": [
                {
                    "id": "phase_1",
                    "name": "基础补齐",
                    "goal": "掌握 RAG",
                    "milestones": [
                        {"id": "phase_1_ms_1", "name": "RAG", "tasks": [{"name": "实现检索"}]}
                    ],
                },
                {
                    "id": "phase_2",
                    "name": "投递实习",
                    "goal": "拿到面试",
                    "milestones": [
                        {"id": "phase_2_ms_1", "name": "投递", "tasks": [{"name": "投递目标公司"}]}
                    ],
                },
            ],
        }
    }


def _full_profile() -> CareerProfile:
    return CareerProfile(
        who={"name": "张三", "city": "北京", "graduation_year": "2027"},
        have={
            "skills": ["Python", "LangChain"],
            "capability_evidence": [{"task": "实现检索", "completed_at": "2026-01-01"}],
        },
        want={
            "target_role": "AI Agent 开发",
            "direction": "AI 应用",
            "city": "北京",
            "target_tiers": ["大厂"],
            "bridge_tiers": ["中厂"],
            "graduation_year": "2027",
            "user_confirmed": True,
        },
        research={
            "report_md": "C:/reports/research.md",
            "report_html": "C:/reports/research.html",
            "report_json": "C:/reports/research.json",
            "jd_samples": [{"title": "AI Agent 工程师", "company": "字节跳动", "url": "u1"}],
            "cases": [{"title": "双非进大厂", "source": "nowcoder", "url": "u2"}],
            "digest": {"top_terms": ["RAG", "Python"]},
            "source_status": [{"source": "boss", "status": "ok"}],
            "counts": {"jd_samples": 1, "cases": 1, "source_ok": 1},
            "gaps": ["缺少面经样本"],
        },
        gap={
            "match_score": 62,
            "match_level": "partial_match",
            "start_level": "小厂",
            "strengths": [{"area": "Python", "description": "熟练"}],
            "resume_red_flags": [{"signal": "项目少", "risk": "过筛难", "evidence_fix": "补项目"}],
            "resume_optimization": {"ats_keywords": ["RAG"]},
            "interview_preparation": {"must_prepare": [{"topic": "RAG"}]},
            "skill_gaps": [{"skill": "RAG", "priority": "high", "source": "BOSS"}],
            "priority_actions": [{"action": "做 RAG 项目", "impact": "补齐证据"}],
            "market_context": "AI Agent 岗位需求增长",
        },
        plan=_roadmap(),
        tasks=[
            Task(id="task_001", name="实现检索", phase_id="phase_1", status="completed"),
            Task(id="task_002", name="补齐基础", phase_id="phase_1", status="pending"),
            Task(id="task_003", name="写简历", phase_id="phase_2", status="in_progress"),
            Task(id="task_004", name="旧任务", phase_id="phase_2", status="skipped"),
        ],
        checkins=[CheckIn(task_id="task_001", status="completed")],
        applications=[
            Application(
                id="app_001",
                company="字节跳动",
                role="AI Agent 开发",
                status="interview",
                events=[
                    {"status": "applied", "at": "2026-01-01T00:00:00"},
                    {"status": "interview", "at": "2026-01-02T00:00:00"},
                ],
            )
        ],
        summary="完整旧档案",
        core_state={"custom_key": "keep", "company_pool_id": "cp_legacy"},
    )


def _save(profile: CareerProfile) -> None:
    profile_store.save_profile(profile, PROFILE_NAME)


def _load_artifact(artifact_id: str) -> dict[str, Any]:
    data = ArtifactStore().load(artifact_id)
    assert data is not None
    return data


def _assert_id(artifact_id: str, prefix: str, stage: str) -> None:
    assert re.fullmatch(rf"{prefix}_\d{{8}}_\d{{6}}_[0-9a-f]{{6}}", artifact_id)
    data = _load_artifact(artifact_id)
    assert data["meta"]["id"] == artifact_id
    assert data["meta"]["stage"] == stage
    assert data["meta"]["profile_name"] == PROFILE_NAME


def _save_applied_execution_plan() -> str:
    """为 sync_review 准备一个已应用的执行版链路。"""
    store = ArtifactStore()
    meta = ArtifactMeta(
        id=store.new_id("ep_"),
        stage=sync.STAGE_EXECUTION_PLAN,
        profile_name=PROFILE_NAME,
        created_at=datetime.now().isoformat(),
        validation={"confirmed": True, "applied": True},
    )
    plan = ExecutionPlan(
        meta=meta,
        requirement_profile_id="rp_test",
        strategy_summary="执行版",
        roadmap=_roadmap()["roadmap"],
        applied=True,
    )
    store.save(plan)
    profile = profile_store.load_profile(PROFILE_NAME)
    state = dict(profile.core_state or {})
    state["execution_plan_id"] = meta.id
    state["stage"] = sync.STAGE_EXECUTION
    state["updated_at"] = datetime.now().isoformat()
    profile.core_state = state
    profile_store.save_profile(profile, PROFILE_NAME)
    return meta.id


def _sync_all() -> dict[str, str]:
    ids = {
        "pf": sync.sync_profile(PROFILE_NAME),
        "ts": sync.sync_target(PROFILE_NAME),
        "mb": sync.sync_market_baseline(PROFILE_NAME),
        "gr": sync.sync_gap(PROFILE_NAME),
        "bp": sync.sync_baseline_plan(PROFILE_NAME),
        "es": sync.sync_execution_state(PROFILE_NAME),
    }
    _save_applied_execution_plan()
    ids["as"] = sync.sync_application_state(PROFILE_NAME)
    ids["rr"] = sync.sync_review(
        PROFILE_NAME,
        plan_fit={
            "status": "minor_drift",
            "signals": [{"code": "coverage", "message": "有 2 项高频要求未覆盖"}],
        },
        weekly_facts={
            "days": 7,
            "start": datetime(2026, 1, 1),
            "suggestions": ["继续执行高优先级任务"],
            "completed": [Task(id="task_001", name="实现检索")],
        },
    )
    return ids


def test_sync_writes_each_artifact_and_core_state(data_dir: Path) -> None:
    _save(_full_profile())
    ids = _sync_all()

    for prefix, stage in ID_PATTERNS.items():
        assert ids[prefix], f"{stage} sync 返回空"
        _assert_id(ids[prefix], prefix, stage)

    profile = profile_store.load_profile(PROFILE_NAME)
    state = profile.core_state
    assert state[sync.KEY_PROFILE] == ids["pf"]
    assert state[sync.KEY_TARGET] == ids["ts"]
    assert state[sync.KEY_MARKET_BASELINE] == ids["mb"]
    assert state[sync.KEY_GAP] == ids["gr"]
    assert state[sync.KEY_BASELINE_PLAN] == ids["bp"]
    assert state[sync.KEY_EXECUTION] == ids["es"]
    assert state[sync.KEY_APPLICATIONS] == ids["as"]
    assert state[sync.KEY_REVIEW] == ids["rr"]
    assert state["stage"] == sync.STAGE_EXECUTION
    assert state["updated_at"]
    assert state["custom_key"] == "keep"
    assert state["company_pool_id"] == "cp_legacy"


def test_sync_artifacts_match_profile_data(data_dir: Path) -> None:
    _save(_full_profile())
    ids = _sync_all()

    profile_artifact = _load_artifact(ids["pf"])
    assert profile_artifact["name"] == "张三"
    assert profile_artifact["who"]["city"] == "北京"
    assert profile_artifact["have"]["skills"] == ["Python", "LangChain"]
    assert profile_artifact["summary"] == "完整旧档案"

    target_artifact = _load_artifact(ids["ts"])
    assert target_artifact["role"] == "AI Agent 开发"
    assert target_artifact["city"] == "北京"
    assert target_artifact["target_tiers"] == ["大厂"]

    baseline_artifact = _load_artifact(ids["mb"])
    assert baseline_artifact["target_spec"]["role"] == "AI Agent 开发"
    assert len(baseline_artifact["jd_samples"]) == 1
    assert len(baseline_artifact["case_samples"]) == 1
    assert baseline_artifact["digest"] == {"top_terms": ["RAG", "Python"]}
    assert baseline_artifact["source_status"] == [{"source": "boss", "status": "ok"}]
    assert baseline_artifact["counts"]["jd_samples"] == 1
    assert baseline_artifact["gaps"] == ["缺少面经样本"]
    assert baseline_artifact["report_paths"]["md"] == "C:/reports/research.md"
    assert baseline_artifact["report_paths"]["html"] == "C:/reports/research.html"

    gap_artifact = _load_artifact(ids["gr"])
    assert gap_artifact["match_score"] == 62
    assert gap_artifact["match_level"] == "partial_match"
    assert gap_artifact["start_level"] == "小厂"
    assert gap_artifact["strengths"][0]["area"] == "Python"
    assert gap_artifact["resume_red_flags"][0]["signal"] == "项目少"
    assert gap_artifact["skill_gaps"][0]["skill"] == "RAG"
    assert gap_artifact["priority_actions"][0]["action"] == "做 RAG 项目"
    assert gap_artifact["market_context"] == "AI Agent 岗位需求增长"

    plan_artifact = _load_artifact(ids["bp"])
    assert plan_artifact["strategy_summary"] == "先补基础再投递"
    assert [p["name"] for p in plan_artifact["roadmap"]["phases"]] == ["基础补齐", "投递实习"]

    execution_artifact = _load_artifact(ids["es"])
    assert execution_artifact["task_counts"] == {
        "pending": 1,
        "in_progress": 1,
        "completed": 1,
        "skipped": 1,
    }
    assert execution_artifact["checkin_counts"] == {"completed": 1}
    assert execution_artifact["current_phase_id"] == "phase_1"
    assert execution_artifact["capability_evidence"][0]["task"] == "实现检索"

    application_artifact = _load_artifact(ids["as"])
    assert len(application_artifact["applications"]) == 1
    assert application_artifact["applications"][0]["company"] == "字节跳动"
    assert application_artifact["funnel"]["total"] == 1
    assert application_artifact["funnel"]["interviewed"] == 1

    review_artifact = _load_artifact(ids["rr"])
    assert review_artifact["plan_fit"]["status"] == "minor_drift"
    assert review_artifact["weekly_facts"]["days"] == 7
    assert review_artifact["weekly_facts"]["start"] == "2026-01-01T00:00:00"
    assert review_artifact["recommendations"] == ["有 2 项高频要求未覆盖", "继续执行高优先级任务"]


def test_sync_links_upstream_ids_in_inputs(data_dir: Path) -> None:
    _save(_full_profile())
    ids = _sync_all()

    target_meta = _load_artifact(ids["ts"])["meta"]
    assert target_meta["inputs"]["profile_id"] == ids["pf"]

    gap_meta = _load_artifact(ids["gr"])["meta"]
    assert gap_meta["inputs"]["profile_id"] == ids["pf"]
    assert gap_meta["inputs"]["market_baseline_id"] == ids["mb"]

    plan_meta = _load_artifact(ids["bp"])["meta"]
    assert plan_meta["inputs"]["gap_report_id"] == ids["gr"]

    review_artifact = _load_artifact(ids["rr"])
    assert review_artifact["execution_state_id"] == ids["es"]


def test_sync_does_not_modify_profile_outside_core_state(data_dir: Path) -> None:
    _save(_full_profile())
    before = profile_store.load_profile(PROFILE_NAME)
    snapshot = {
        "who": before.who,
        "have": before.have,
        "want": before.want,
        "gap": before.gap,
        "plan": before.plan,
        "tasks": [task.model_dump() for task in before.tasks],
        "applications": [app.model_dump() for app in before.applications],
        "research": before.research,
        "summary": before.summary,
    }

    _sync_all()

    after = profile_store.load_profile(PROFILE_NAME)
    assert after.who == snapshot["who"]
    assert after.have == snapshot["have"]
    assert after.want == snapshot["want"]
    assert after.gap == snapshot["gap"]
    assert after.plan == snapshot["plan"]
    assert [task.model_dump() for task in after.tasks] == snapshot["tasks"]
    assert [app.model_dump() for app in after.applications] == snapshot["applications"]
    assert after.research == snapshot["research"]
    assert after.summary == snapshot["summary"]


def test_sync_returns_empty_when_prerequisites_missing(data_dir: Path) -> None:
    _save(CareerProfile())

    assert sync.sync_profile(PROFILE_NAME) == ""
    assert sync.sync_target(PROFILE_NAME) == ""
    assert sync.sync_market_baseline(PROFILE_NAME) == ""
    assert sync.sync_gap(PROFILE_NAME) == ""
    assert sync.sync_baseline_plan(PROFILE_NAME) == ""
    assert sync.sync_execution_state(PROFILE_NAME) == ""
    assert sync.sync_application_state(PROFILE_NAME) == ""
    assert sync.sync_review(PROFILE_NAME) == ""

    assert ArtifactStore().list(PROFILE_NAME) == []
    assert profile_store.load_profile(PROFILE_NAME).core_state == {}


def test_sync_profile_accepts_summary_only(data_dir: Path) -> None:
    _save(CareerProfile(summary="只有摘要"))
    artifact_id = sync.sync_profile(PROFILE_NAME)
    assert artifact_id.startswith("pf_")
    assert _load_artifact(artifact_id)["summary"] == "只有摘要"


def test_sync_skips_market_baseline_without_report_or_samples(data_dir: Path) -> None:
    profile = _full_profile()
    profile.research = {"generated_at": "2026-01-01T00:00:00"}
    _save(profile)
    assert sync.sync_market_baseline(PROFILE_NAME) == ""
    assert ArtifactStore().list(PROFILE_NAME, sync.STAGE_MARKET_BASELINE) == []


def test_sync_profile_dedupes_unchanged_content(data_dir: Path) -> None:
    _save(_full_profile())

    ids = [sync.sync_profile(PROFILE_NAME) for _ in range(5)]

    assert len(set(ids)) == 1
    assert ids[0]
    items = ArtifactStore().list(PROFILE_NAME, sync.STAGE_PROFILE)
    assert len(items) == 1
    assert items[0]["meta"]["version"] == 1
    state = profile_store.load_profile(PROFILE_NAME).core_state
    assert state[sync.KEY_PROFILE] == ids[0]


def test_sync_profile_new_version_when_content_changes(data_dir: Path) -> None:
    _save(_full_profile())
    first = sync.sync_profile(PROFILE_NAME)

    profile = profile_store.load_profile(PROFILE_NAME)
    profile.who["name"] = "李四"
    _save(profile)
    second = sync.sync_profile(PROFILE_NAME)

    assert second and second != first
    assert _load_artifact(second)["name"] == "李四"
    assert _load_artifact(second)["meta"]["version"] == 2
    items = ArtifactStore().list(PROFILE_NAME, sync.STAGE_PROFILE)
    assert [item["meta"]["id"] for item in items] == [second, first]
    state = profile_store.load_profile(PROFILE_NAME).core_state
    assert state[sync.KEY_PROFILE] == second


def test_sync_baseline_plan_rejects_malformed_roadmap(data_dir: Path) -> None:
    profile = _full_profile()

    profile.plan = {"roadmap": []}
    _save(profile)
    assert sync.sync_baseline_plan(PROFILE_NAME) == ""

    profile.plan = {"roadmap": {"phases": []}}
    _save(profile)
    assert sync.sync_baseline_plan(PROFILE_NAME) == ""

    profile.plan = {"roadmap": "not-a-dict"}
    _save(profile)
    assert sync.sync_baseline_plan(PROFILE_NAME) == ""

    assert ArtifactStore().list(PROFILE_NAME, sync.STAGE_BASELINE_PLAN) == []


def test_sync_gap_requires_resolvable_profile_snapshot(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(CareerProfile(gap={"match_score": 50}))

    def _broken_snapshot(profile: CareerProfile) -> Any:
        raise RuntimeError("snapshot unparsable")

    monkeypatch.setattr(sync, "profile_snapshot", _broken_snapshot)

    assert sync.sync_gap(PROFILE_NAME) == ""
    assert ArtifactStore().list(PROFILE_NAME, sync.STAGE_GAP) == []
    assert ArtifactStore().list(PROFILE_NAME, sync.STAGE_PROFILE) == []


def test_sync_gap_creates_profile_anchor_when_missing(data_dir: Path) -> None:
    _save(CareerProfile(who={"name": "张三"}, gap={"match_score": 50}))

    gap_id = sync.sync_gap(PROFILE_NAME)

    assert gap_id.startswith("gr_")
    gap = _load_artifact(gap_id)
    profile_id = gap["profile_snapshot_id"]
    assert profile_id.startswith("pf_")
    assert _load_artifact(profile_id)["meta"]["stage"] == sync.STAGE_PROFILE
    state = profile_store.load_profile(PROFILE_NAME).core_state
    assert state[sync.KEY_PROFILE] == profile_id
    assert state[sync.KEY_GAP] == gap_id


def test_sync_execution_state_requires_plan_or_baseline(data_dir: Path) -> None:
    profile = _full_profile()
    profile.plan = {}
    _save(profile)

    assert sync.sync_execution_state(PROFILE_NAME) == ""
    assert ArtifactStore().list(PROFILE_NAME, sync.STAGE_EXECUTION) == []


def test_sync_execution_state_omits_unapplied_execution_plan(
    data_dir: Path,
) -> None:
    _save(_full_profile())
    sync.sync_baseline_plan(PROFILE_NAME)

    execution_id = sync.sync_execution_state(PROFILE_NAME)

    assert execution_id.startswith("es_")
    execution = _load_artifact(execution_id)
    assert execution["execution_plan_id"] == ""
    assert execution["meta"]["inputs"]["baseline_plan_id"]
    assert "execution_plan_id" not in execution["meta"]["inputs"]
