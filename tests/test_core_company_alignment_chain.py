"""Core v2 阶段 6-9 全链路集成：企业筛选 → 证据采集 → 需求分析 → 执行方案校准。

所有抓取函数均 monkeypatch，不联网；档案与 artifact 使用 tmp_path 隔离，
资产目录由 tests/conftest.py 的 autouse fixture 重定向，不读写真实用户目录。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import paths
from src.core import sync as core_sync
from src.core.artifacts.store import ArtifactStore
from src.core.orchestrator import state_machine
from src.core.stages import evidence as evidence_stage
from src.models import CareerProfile, Task
from src.tools import profile as profile_store
from src.tools.company_selection_tools import select_target_companies
from src.tools.evidence_tools import collect_company_evidence
from src.tools.execution_plan_tools import plan_execution_alignment, save_execution_alignment
from src.tools.requirement_tools import analyze_company_requirements, save_requirement_profile

PROFILE_NAME = "default"
DIFF_SUMMARY = "按企业需求新增 RAG 检索任务，移除旧 pending 任务"


def _baseline_plan() -> dict[str, Any]:
    return {
        "roadmap": {
            "strategy_summary": "基线",
            "start_level": "小厂",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "基础学习",
                    "goal": "掌握 Python 基础",
                    "milestones": [
                        {
                            "id": "phase_1_ms_1",
                            "name": "Python 基础",
                            "done_criteria": "能独立完成脚本",
                            "tasks": [{"name": "完成 Python 基础", "priority": "high"}],
                        }
                    ],
                },
                {
                    "id": "phase_2",
                    "type": "project",
                    "name": "项目实战",
                    "goal": "做出一个项目",
                    "milestones": [
                        {
                            "id": "phase_2_ms_1",
                            "name": "项目里程碑",
                            "done_criteria": "项目可运行",
                            "tasks": [{"name": "待办旧任务", "priority": "medium"}],
                        }
                    ],
                },
            ],
        }
    }


def _seed_profile() -> CareerProfile:
    profile = CareerProfile(
        who={"name": "测试用户", "education": "双非本", "city": "上海"},
        have={"skills": ["Python"]},
        want={
            "target_role": "AI Agent 开发",
            "city": "上海",
            "target_tiers": ["大厂"],
            "bridge_tiers": ["中厂"],
            "user_confirmed": True,
        },
        guidance={"goal_confirmed_at": "2026-11-09T00:00:00"},
        gap={"start_level": "小厂", "match_score": 60},
        research={"report_md": "C:/reports/baseline.md"},
        plan=_baseline_plan(),
        tasks=[
            Task(
                id="task_done",
                name="完成 Python 基础",
                phase_id="phase_1",
                milestone_id="phase_1_ms_1",
                status="completed",
                completed_at="2026-10-01T10:00:00",
                how_to=["读官方教程", "写练习"],
                done_criteria="能独立写出脚本",
            ),
            Task(
                id="task_pending",
                name="待办旧任务",
                phase_id="phase_1",
                milestone_id="phase_1_ms_1",
                status="pending",
            ),
        ],
    )
    profile_store.save_profile(profile, PROFILE_NAME)
    return profile


def _patch_sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"search": [], "detail": [], "cases": []}
    display_names = {"bytedance": "字节跳动", "jd": "京东"}

    def fake_search(company: str, **params: Any) -> dict[str, Any]:
        calls["search"].append((company, params))
        display = display_names.get(company, company)
        if company == "bytedance":
            titles = ["AI Agent 开发", "大模型应用工程师"]
        else:
            titles = ["后端开发工程师", "服务端开发工程师"]
        return {
            "results": [
                {
                    "title": title,
                    "company": display,
                    "location": "上海",
                    "url": f"https://jobs.example.com/{company}/{index}",
                    "summary": "AI Agent 应用开发",
                }
                for index, title in enumerate(titles, 1)
            ]
        }

    def fake_detail(url: str, company: str | None = None) -> dict[str, Any]:
        calls["detail"].append((url, company))
        return {
            "description": "负责 AI Agent 应用开发，参与 LLM 应用落地。",
            "requirements": "本科及以上，3年以上经验；熟悉 Python、LLM、Agent、RAG。",
        }

    def fake_cases(**kwargs: Any) -> dict[str, Any]:
        calls["cases"].append(kwargs)
        return {
            "cases": [
                {
                    "title": "字节 AI Agent 一面面经",
                    "source": "nowcoder",
                    "url": "https://cases.example.com/bytedance/1",
                    "highlights": ["RAG 检索链路", "Agent 工具调用"],
                    "background": {"company": "字节跳动", "education_tag": "本科", "year": "2026"},
                },
                {
                    "title": "京东后端面经",
                    "source": "nowcoder",
                    "url": "https://cases.example.com/jd/1",
                    "highlights": ["Python", "LLM 基础"],
                    "background": {"company": "京东", "education_tag": "本科", "year": "2026"},
                },
            ],
            "warnings": [],
            "sources": {"nowcoder": 2},
        }

    monkeypatch.setattr(evidence_stage, "search_company_jobs", fake_search)
    monkeypatch.setattr(evidence_stage, "get_job_detail", fake_detail)
    monkeypatch.setattr(evidence_stage, "collect_cases", fake_cases)
    return calls


def _payload(raw: str, step: str) -> dict[str, Any]:
    data = json.loads(raw)
    assert not data.get("isError"), f"{step} 返回错误：{data}"
    return data


def _proposed_roadmap() -> dict[str, Any]:
    return {
        "strategy_summary": "按企业需求校准",
        "phases": [
            {
                "id": "phase_1",
                "type": "project",
                "name": "RAG 与 Agent 项目",
                "goal": "补齐企业高频要求证据",
                "kpi": {"metric": "RAG 项目", "target": "可演示", "evidence": "GitHub 仓库"},
                "milestones": [
                    {
                        "id": "phase_1_ms_1",
                        "name": "RAG 检索",
                        "done_criteria": "能回答真实文档问题",
                        "tasks": [
                            {
                                "name": "实现 RAG 检索链路",
                                "description": "接入向量检索",
                                "priority": "high",
                            },
                            {
                                "name": "完成 Agent 工具调用",
                                "description": "实现工具编排",
                                "priority": "high",
                            },
                        ],
                    }
                ],
            },
            {
                "id": "phase_2",
                "type": "intern",
                "name": "投递与面试",
                "goal": "拿到目标企业面试机会",
                "milestones": [
                    {
                        "id": "phase_2_ms_1",
                        "name": "投递",
                        "done_criteria": "完成投递记录",
                        "tasks": [{"name": "投递字节跳动 AI Agent 岗位", "priority": "medium"}],
                    }
                ],
            },
        ],
    }


def test_company_alignment_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(paths, "PROFILE_DIR", data_dir)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", data_dir)
    calls = _patch_sources(monkeypatch)
    _seed_profile()
    store = ArtifactStore()

    # 阶段 1-5 上游链：CompanyPool 必须引用 BaselinePlan，progress 才能推进。
    for sync_fn in (
        core_sync.sync_profile,
        core_sync.sync_target,
        core_sync.sync_market_baseline,
        core_sync.sync_gap,
        core_sync.sync_baseline_plan,
    ):
        assert sync_fn(PROFILE_NAME)

    # 阶段 6：目标企业筛选（已确认）
    pool_payload = _payload(
        select_target_companies(
            target_tiers="大厂",
            bridge_tiers="中厂",
            city="上海",
            role="AI Agent 开发",
            industry="互联网",
            confirmed=True,
        ),
        "阶段 6 select_target_companies",
    )
    pool_id = pool_payload["artifact_id"]
    assert pool_payload["status"] == "ok"
    assert pool_payload["confirmed"] is True
    assert pool_payload["next_tool"] == "collect_company_evidence"
    assert pool_id.startswith("cp_")
    assert len(pool_payload["scrapable"]) >= 2
    pool_artifact = store.load(pool_id)
    assert pool_artifact is not None
    assert pool_artifact["meta"]["stage"] == state_machine.STAGE_COMPANY_POOL
    assert pool_artifact["meta"]["validation"]["confirmed"] is True
    assert pool_artifact["target_spec"]["role"] == "AI Agent 开发"
    assert pool_artifact["target_spec"]["city"] == "上海"
    assert pool_artifact["counts"]["confirmed"] == pool_artifact["counts"]["total"]
    profile_after_pool = profile_store.load_profile(PROFILE_NAME)
    assert profile_after_pool.core_state["company_pool_id"] == pool_id

    # 阶段 7：岗位与面经采集
    evidence_payload = _payload(
        asyncio.run(collect_company_evidence(max_companies=2, per_company_limit=2)),
        "阶段 7 collect_company_evidence",
    )
    evidence_id = evidence_payload["artifact_id"]
    assert evidence_payload["status"] == "ok"
    assert evidence_id.startswith("ev_")
    assert evidence_payload["counts"]["companies_requested"] == 2
    assert evidence_payload["counts"]["companies_fetched"] == 2
    assert evidence_payload["counts"]["kept_jobs"] == 4
    assert evidence_payload["counts"]["interviews"] == 2
    assert evidence_payload["confidence"] == {"jd": "low", "interview": "low"}
    assert set(evidence_payload["report_paths"]) == {"md", "json"}
    assert len(calls["search"]) == 2
    assert len(calls["detail"]) == 4
    assert calls["cases"] and calls["cases"][0]["education"] == "双非本"

    evidence_artifact = store.load(evidence_id)
    assert evidence_artifact is not None
    assert evidence_artifact["company_pool_id"] == pool_id
    assert evidence_artifact["target_spec"]["role"] == "AI Agent 开发"
    assert len(evidence_artifact["jd_items"]) == 4
    assert all(item["detail_status"] == "ok" for item in evidence_artifact["jd_items"])
    scrapable_ids = {item["id"] for item in pool_artifact["companies"] if item["scrapable"]}
    fetched_ids = {item["company_id"] for item in evidence_artifact["jd_items"]}
    assert len(fetched_ids) == 2
    assert fetched_ids <= scrapable_ids
    jd_statuses = [
        item for item in evidence_artifact["meta"]["source_status"] if item["scope"] == "jd"
    ]
    assert len(jd_statuses) == 2
    assert all(item["status"] == "ok" for item in jd_statuses)
    case_statuses = [
        item for item in evidence_artifact["meta"]["source_status"] if item["scope"] == "cases"
    ]
    assert len(case_statuses) == 1
    assert case_statuses[0]["source"] == "nowcoder"
    assert case_statuses[0]["status"] == "ok"
    assert case_statuses[0]["count"] == 2
    profile_after_evidence = profile_store.load_profile(PROFILE_NAME)
    assert profile_after_evidence.core_state["evidence_run_id"] == evidence_id

    # 阶段 8：确定性统计
    analysis_payload = _payload(
        analyze_company_requirements(), "阶段 8 analyze_company_requirements"
    )
    rp_id = analysis_payload["requirement_profile_id"]
    assert analysis_payload["status"] == "ok"
    assert rp_id.startswith("rp_")
    assert analysis_payload["evidence_run_id"] == evidence_id
    assert analysis_payload["sample_size"] == {"jd": 4, "interview": 2}
    high_frequency = {item["term"]: item for item in analysis_payload["high_frequency"]}
    for term in ("Python", "LLM", "Agent", "RAG"):
        item = high_frequency[term]
        assert item["jd_count"] == 4
        assert item["company_count"] == 2
        assert item["jd_frequency"] == 1.0
    hard_requirements = analysis_payload["hard_requirements"]
    assert len(hard_requirements) == 4
    assert {item["education"] for item in hard_requirements} == {"本科"}
    assert all("3年以上经验" in item["experience"] for item in hard_requirements)
    evidence_ref = high_frequency["RAG"]["evidence_ids"][0]
    assert evidence_ref == "JD001"

    # 阶段 8：保存定性解读（数字由代码复核）
    saved_requirement = _payload(
        save_requirement_profile(
            json.dumps(
                {"requirement_profile_id": rp_id, "interpretation": {"summary": "测试解读"}},
                ensure_ascii=False,
            )
        ),
        "阶段 8 save_requirement_profile",
    )
    assert saved_requirement["status"] == "ok"
    assert saved_requirement["requirement_profile_id"] == rp_id
    assert saved_requirement["revalidated"] is True
    assert saved_requirement["version"] == 2
    assert saved_requirement["interpretation_keys"] == ["summary"]
    requirement_artifact = store.load(rp_id)
    assert requirement_artifact is not None
    assert requirement_artifact["meta"]["version"] == 2
    assert requirement_artifact["interpretation"] == {"summary": "测试解读"}
    assert requirement_artifact["evidence_run_id"] == evidence_id
    profile_after_requirement = profile_store.load_profile(PROFILE_NAME)
    assert profile_after_requirement.core_state["requirement_profile_id"] == rp_id
    assert profile_after_requirement.core_state["stage"] == state_machine.STAGE_REQUIREMENT

    # 阶段 9：准备校准上下文
    alignment_context = _payload(
        plan_execution_alignment(), "阶段 9 plan_execution_alignment"
    )
    assert alignment_context["status"] == "ok"
    assert alignment_context["requirement"]["requirement_profile_id"] == rp_id
    assert alignment_context["requirement"]["evidence_run_id"] == evidence_id
    assert alignment_context["baseline_plan"]["strategy_summary"] == "基线"
    assert [phase["name"] for phase in alignment_context["baseline_plan"]["phases"]] == [
        "基础学习",
        "项目实战",
    ]
    completed = alignment_context["completed_evidence"]
    assert [entry["task_id"] for entry in completed] == ["task_done"]
    assert completed[0]["status"] == "completed"
    assert completed[0]["how_to"] == ["读官方教程", "写练习"]
    prompt = alignment_context["alignment_prompt"]
    assert prompt["requirement_profile_id"] == rp_id
    assert evidence_ref in prompt["available_evidence_ids"]

    alignment_json = json.dumps(
        {
            "requirement_profile_id": rp_id,
            "strategy_summary": "按企业需求校准",
            "roadmap": _proposed_roadmap(),
            "changes": [
                {
                    "type": "add_task",
                    "phase_id": "phase_1",
                    "details": {"name": "实现 RAG 检索链路"},
                    "reason": "企业高频要求 RAG",
                    "evidence_ids": [evidence_ref],
                }
            ],
            "diff_summary": DIFF_SUMMARY,
        },
        ensure_ascii=False,
    )

    # 阶段 9：先进入 EXECUTION_PLAN_DRAFT（已生成、未应用的 ExecutionPlan）
    from src.core.artifacts.models import ArtifactMeta, ExecutionPlan

    baseline_id = profile_store.load_profile(PROFILE_NAME).core_state["baseline_plan_id"]
    store.save(
        ExecutionPlan(
            meta=ArtifactMeta(
                id=store.new_id("ep"),
                stage=state_machine.STAGE_EXECUTION_PLAN,
                profile_name=PROFILE_NAME,
                created_at="2026-11-10T00:00:00",
                validation={"applied": False},
            ),
            requirement_profile_id=rp_id,
            baseline_plan_id=baseline_id,
            applied=False,
        )
    )

    # 阶段 9：预览（不得修改档案）
    before_preview = profile_store.load_profile(PROFILE_NAME)
    preview = _payload(
        save_execution_alignment(alignment_json, confirmed=False),
        "阶段 9 save_execution_alignment(confirmed=False)",
    )
    preview_id = preview["execution_plan_id"]
    assert preview["status"] == "needs_confirmation"
    assert preview["applied"] is False
    assert preview_id.startswith("ep_")
    assert preview["diff_summary"] == DIFF_SUMMARY
    assert preview["change_counts"] == {"add_task": 1}
    assert [task["task_id"] for task in preview["preserved_tasks"]] == ["task_done"]
    assert [task["task_id"] for task in preview["removed_tasks"]] == ["task_pending"]
    preview_artifact = store.load(preview_id)
    assert preview_artifact is not None
    assert preview_artifact["applied"] is False
    assert preview_artifact["meta"]["validation"]["confirmed"] is False
    after_preview = profile_store.load_profile(PROFILE_NAME)
    assert after_preview.plan == before_preview.plan
    assert [task.id for task in after_preview.tasks] == ["task_done", "task_pending"]
    assert after_preview.plan_history == []

    # 阶段 9：确认应用
    applied = _payload(
        save_execution_alignment(alignment_json, confirmed=True),
        "阶段 9 save_execution_alignment(confirmed=True)",
    )
    applied_id = applied["execution_plan_id"]
    assert applied["status"] == "ok"
    assert applied["applied"] is True
    assert applied_id.startswith("ep_")
    assert applied_id != preview_id
    assert applied["preserved_task_count"] == 1
    assert applied["removed_task_count"] == 1
    assert applied["plan_history_versions"] == 1
    assert applied["core_state"]["stage"] == "executing"

    profile_after = profile_store.load_profile(PROFILE_NAME)
    roadmap_after = profile_after.plan["roadmap"]
    assert roadmap_after["strategy_summary"] == "按企业需求校准"
    assert [phase["name"] for phase in roadmap_after["phases"]] == [
        "RAG 与 Agent 项目",
        "投递与面试",
    ]
    assert [phase["id"] for phase in roadmap_after["phases"]] == ["phase_1", "phase_2"]

    tasks_after = {task.id: task for task in profile_after.tasks}
    assert set(tasks_after) == {"task_done"}
    assert tasks_after["task_done"].status == "completed"
    assert tasks_after["task_done"].completed_at == "2026-10-01T10:00:00"
    assert tasks_after["task_done"].how_to == ["读官方教程", "写练习"]
    assert tasks_after["task_done"].done_criteria == "能独立写出脚本"

    assert len(profile_after.plan_history) == 1
    assert profile_after.plan_history[0].source == "company_alignment"
    assert profile_after.plan_history[0].content == before_preview.plan

    alignment_adjustments = [
        item for item in profile_after.adjustments if item.trigger == "company_alignment"
    ]
    assert len(alignment_adjustments) == 1
    adjustment = alignment_adjustments[0]
    assert adjustment.trigger_type == "event"
    assert adjustment.reason == DIFF_SUMMARY
    assert len(adjustment.changes) == 1
    assert adjustment.changes[0]["evidence_ids"] == [evidence_ref]

    assert profile_after.core_state["stage"] == "executing"
    assert profile_after.core_state["execution_plan_id"] == applied_id
    assert profile_after.core_state["requirement_profile_id"] == rp_id
    assert profile_after.core_state["evidence_run_id"] == evidence_id
    assert profile_after.core_state["company_pool_id"] == pool_id

    applied_artifact = store.load(applied_id)
    assert applied_artifact is not None
    assert applied_artifact["applied"] is True
    assert applied_artifact["meta"]["validation"]["applied"] is True
    assert applied_artifact["requirement_profile_id"] == rp_id

    # 新计划应用后先按执行版生成任务，再由 ExecutionState 解锁 get_next_tasks。
    from src.tools.task_tools import generate_tasks

    assert "已为当前阶段" in generate_tasks()

    action = state_machine.next_action(PROFILE_NAME)
    assert action["stage"] == state_machine.STAGE_EXECUTING
    assert action["next_tool"] == "get_next_tasks"
    assert "record_application" in action["optional_next_tools"]
    assert action["artifact_ids"]["execution_plan_id"] == applied_id

    for kind in ("md", "json"):
        report_path = Path(evidence_payload["report_paths"][kind])
        assert report_path.exists(), f"证据池 {kind} 报告不存在：{report_path}"
        assert report_path.suffix == f".{kind}"
