"""状态旅程：企业适配全链路、跳过补齐、市场跳过、阶段 9、plan_fit 返工、import_plan。

外部抓取只用固定样本（tests/e2e/fixtures/scrapers/enterprise_jds.json）；
状态、工具门禁与 artifact 落库全部走真实 MCP 工具，不直接改库。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.data import GAP, HAVE, ROADMAP, WANT, WHO
from e2e.drivers import FlowDriver, flow

pytestmark = pytest.mark.e2e

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "scrapers"
    / "enterprise_jds.json"
)
COMPANIES = "字节跳动,腾讯"

INTERPRETATION = {
    "summary": "企业 JD 高频要求集中在 Python、LangGraph、RAG 与 Kubernetes。",
    "priorities": ["Kubernetes", "RAG"],
    "risks": ["样本量有限，结论只作方向参考"],
}

ALIGNMENT_TASKS = [
    {"name": "实现工具调用 Agent", "description": "接入 2 个工具并跑通", "priority": "high"},
    {"name": "设计 RAG 评测集", "description": "覆盖召回与答案质量", "priority": "high"},
]


def _use_scraper_fixture(sandbox) -> None:
    sandbox.env["CAREER_KIT_E2E_SCRAPER_FIXTURE"] = str(FIXTURE)


def _alignment(requirement_profile_id: str) -> dict:
    return {
        "requirement_profile_id": requirement_profile_id,
        "strategy_summary": "按企业高频要求重排执行版路线图。",
        "roadmap": {
            "strategy_summary": "按企业高频要求重排执行版路线图。",
            "phases": [
                {
                    "id": "phase_1",
                    "type": "learn",
                    "name": "Agent 工程基础",
                    "goal": "掌握 Agent 编排与 RAG 评测",
                    "kpi": {
                        "metric": "完成可运行 demo",
                        "target": "1 个",
                        "evidence": "GitHub 仓库",
                    },
                    "milestones": [
                        {
                            "name": "工具调用与评测",
                            "done_criteria": "Agent 可调用工具并产出评测报告",
                            "tasks": ALIGNMENT_TASKS,
                        }
                    ],
                }
            ],
        },
        "changes": [
            {
                "type": "add_phase",
                "details": {"name": "Agent 工程基础"},
                "reason": "企业 JD 高频要求 Agent 与 RAG 工程能力",
                "evidence_ids": ["JD001"],
            }
        ],
        "diff_summary": "把基线路线图收敛为 Agent 工程 + RAG 评测的执行版。",
    }


async def _setup_profile(driver: FlowDriver) -> None:
    await driver.begin()
    await driver.intake("who", WHO)
    await driver.intake("have", HAVE)
    await driver.intake("want", WANT)
    await driver.finalize()


async def _setup_baseline_without_market(driver: FlowDriver) -> None:
    """市场跳过后直接落差距与基线（不伪造 MarketBaseline）。"""
    await _setup_profile(driver)
    gap = await driver.save_gap(GAP)
    gap.assert_contains("差距分析已保存")
    await driver.save_roadmap(ROADMAP)


async def _setup_requirement_ready(
    driver: FlowDriver, *, per_company_limit: int = 5
) -> dict:
    await _setup_baseline_without_market(driver)
    await driver.select_companies(
        include=COMPANIES, target_tiers="小厂", confirmed=True
    )
    evidence = await driver.collect_evidence(per_company_limit=per_company_limit)
    evidence_data = evidence.json()
    evidence.assert_contains("next_tool", "analyze_company_requirements")
    analysis = await driver.analyze_requirements(evidence_data["artifact_id"])
    analyzed = analysis.json()
    requirement_id = analyzed["requirement_profile_id"]
    await driver.save_requirement(requirement_id, INTERPRETATION)
    return {
        "evidence_id": evidence_data["artifact_id"],
        "requirement_id": requirement_id,
        "analysis": analyzed,
    }


async def _assert_status(
    driver: FlowDriver, stage_index: int, stage_name: str, next_tool: str
) -> None:
    status = await driver.status()
    status.assert_contains(f"{stage_index}/12 {stage_name}", f"下一步**：{next_tool}")


async def test_enterprise_full_chain(sandbox):
    """A：企业适配完整链路，含阶段 9 预览与应用。"""
    _use_scraper_fixture(sandbox)
    async with flow(sandbox) as (mcp, driver):
        assert {"select_target_companies", "collect_company_evidence"} <= mcp.tool_names()
        await _setup_baseline_without_market(driver)
        await _assert_status(driver, 6, "目标企业筛选", "select_target_companies")

        pool = (await driver.select_companies(
            include=COMPANIES, target_tiers="小厂", confirmed=True
        )).json()
        assert pool["confirmed"] is True, pool
        assert sandbox.artifact(pool["artifact_id"])["meta"]["validation"]["confirmed"]
        await _assert_status(driver, 7, "岗位与面经采集", "collect_company_evidence")

        evidence = (await driver.collect_evidence()).json()
        assert evidence["counts"]["kept_jobs"] >= 2, evidence
        assert sandbox.artifact(evidence["artifact_id"])["jd_items"], "证据未落库"
        await _assert_status(
            driver, 8, "企业需求分析", "analyze_company_requirements"
        )

        analysis = (await driver.analyze_requirements(evidence["artifact_id"])).json()
        requirement_id = analysis["requirement_profile_id"]
        assert analysis["sample_size"]["jd"] >= 2, analysis
        await _assert_status(driver, 8, "企业需求分析", "save_requirement_profile")

        saved = await driver.save_requirement(requirement_id, INTERPRETATION)
        saved.assert_contains("plan_execution_alignment")
        await _assert_status(driver, 9, "执行方案校准", "plan_execution_alignment")

        plan_context = (await driver.plan_alignment(requirement_id)).json()
        assert plan_context["requirement"]["requirement_profile_id"] == requirement_id
        assert plan_context["alignment_prompt"]

        alignment = _alignment(requirement_id)
        preview = (await driver.save_alignment(alignment)).json()
        assert preview["status"] == "needs_confirmation", preview
        assert preview["applied"] is False
        await _assert_status(driver, 9, "执行方案校准", "save_execution_alignment")

        applied = (await driver.save_alignment(alignment, confirmed=True)).json()
        assert applied["status"] == "ok" and applied["applied"] is True, applied
        assert sandbox.artifact(applied["execution_plan_id"])["applied"] is True
        await _assert_status(driver, 10, "任务执行与打卡", "detail_current_phase")

        await driver.detail_phase()
        await driver.save_detail(
            {
                "phase_id": "phase_1",
                "tasks": [
                    {
                        "name": "实现工具调用 Agent",
                        "checkin_mode": "once",
                        "priority": "high",
                    }
                ],
            }
        )
        tasks = await driver.generate_tasks()
        tasks.assert_contains("已为当前阶段")
        assert driver.tasks, driver.tasks
        await _assert_status(driver, 10, "任务执行与打卡", "get_next_tasks")


async def test_enterprise_skip_then_recover(sandbox):
    """B：先按基线执行并记录跳过，补齐企业 artifact 后恢复企业链路。"""
    _use_scraper_fixture(sandbox)
    async with flow(sandbox) as (mcp, driver):
        await _setup_baseline_without_market(driver)
        await driver.detail_phase()
        await driver.generate_tasks()
        assert driver.profile["guidance"].get("enterprise_alignment_skipped_at")
        await _assert_status(driver, 10, "任务执行与打卡", "get_next_tasks")

        pool = (await driver.select_companies(
            include=COMPANIES, target_tiers="小厂", confirmed=True
        )).json()
        assert pool["confirmed"] is True
        assert sandbox.artifact(pool["artifact_id"])["meta"]["validation"]["confirmed"]
        await _assert_status(driver, 7, "岗位与面经采集", "collect_company_evidence")

        evidence = (await driver.collect_evidence()).json()
        assert sandbox.artifact(evidence["artifact_id"])["jd_items"], "证据未落库"
        analysis = (await driver.analyze_requirements(evidence["artifact_id"])).json()
        await driver.save_requirement(
            analysis["requirement_profile_id"], INTERPRETATION
        )
        requirement = sandbox.artifact(analysis["requirement_profile_id"])
        assert requirement["meta"]["validation"]["status"] == "saved"

        # 企业 artifact 补齐后 skip 标记不再短路，状态回到企业链路。
        await _assert_status(driver, 9, "执行方案校准", "plan_execution_alignment")
        skipped_at = driver.profile["guidance"].get("enterprise_alignment_skipped_at")
        assert skipped_at, "跳过事实应保留可审计"


async def test_market_skipped_gap_and_roadmap(sandbox):
    """C：市场跳过后直接差距、路线图与企业筛选。"""
    async with flow(sandbox) as (mcp, driver):
        await _setup_profile(driver)
        await _assert_status(driver, 3, "市场基线调研", "gather_research_data")

        await driver.save_gap(GAP)
        await _assert_status(driver, 5, "培养方案规划", "generate_roadmap")
        gap_id = driver.profile["core_state"]["gap_report_id"]
        gap_artifact = sandbox.artifact(gap_id)
        assert gap_artifact["meta"]["validation"]["market_skipped"] is True
        assert gap_artifact["meta"]["inputs"]["target_spec_id"]

        await driver.save_roadmap(ROADMAP)
        await _assert_status(driver, 6, "目标企业筛选", "select_target_companies")
        baseline_id = driver.profile["core_state"]["baseline_plan_id"]
        baseline = sandbox.artifact(baseline_id)
        assert baseline["meta"]["validation"]["market_skipped"] is True
        assert baseline["gap_report_id"] == gap_id

        pool = (await driver.select_companies(
            include=COMPANIES, target_tiers="小厂", confirmed=True
        )).json()
        assert pool["confirmed"] is True
        await _assert_status(driver, 7, "岗位与面经采集", "collect_company_evidence")


async def test_stage_nine_first_save_preview_and_apply(sandbox):
    """D：阶段 9 首次保存（REQUIREMENT_READY）可直接预览/应用。"""
    _use_scraper_fixture(sandbox)
    async with flow(sandbox) as (mcp, driver):
        ctx = await _setup_requirement_ready(driver)
        await _assert_status(driver, 9, "执行方案校准", "plan_execution_alignment")

        alignment = _alignment(ctx["requirement_id"])
        preview = (await driver.save_alignment(alignment)).json()
        assert preview["status"] == "needs_confirmation"
        assert preview["execution_plan_id"]
        assert sandbox.artifact(preview["execution_plan_id"])["applied"] is False
        await _assert_status(driver, 9, "执行方案校准", "save_execution_alignment")

        applied = (await driver.save_alignment(alignment, confirmed=True)).json()
        assert applied["applied"] is True
        assert sandbox.artifact(applied["execution_plan_id"])["applied"] is True
        await _assert_status(driver, 10, "任务执行与打卡", "detail_current_phase")


async def test_plan_fit_rework_recommendation_is_reachable(sandbox):
    """E：执行中 plan_fit 判定失配，推荐工具可达且第二次保存/应用可落地。"""
    _use_scraper_fixture(sandbox)
    async with flow(sandbox) as (mcp, driver):
        ctx = await _setup_requirement_ready(driver, per_company_limit=8)
        terms = {
            item["term"]: item for item in ctx["analysis"]["high_frequency"]
        }
        assert "Kubernetes" in terms, terms
        assert terms["Kubernetes"]["company_count"] >= 2

        baseline_id = driver.profile["core_state"]["baseline_plan_id"]
        alignment = _alignment(ctx["requirement_id"])
        first_applied = (await driver.save_alignment(alignment, confirmed=True)).json()
        assert first_applied["applied"] is True
        await driver.generate_tasks()
        await _assert_status(driver, 10, "任务执行与打卡", "get_next_tasks")

        fit = (await driver.plan_fit("milestone")).json()
        assert fit["status"] == "major_drift", fit
        assert fit["next_tool"] == "plan_execution_alignment", fit
        assert any(
            signal["code"] == "uncovered_requirement"
            and signal["severity"] == "high"
            for signal in fit["signals"]
        ), fit

        # 推荐工具在 EXECUTING 可直接调用，证明返工路径没有被门禁挡住。
        reachable = await driver.plan_alignment(ctx["requirement_id"])
        reachable.assert_contains("alignment_prompt", "methodology")

        # 第一次 apply 已改写 profile.plan；第二次返工仍以 BaselinePlan artifact
        # 为基线，预演与应用都必须成功（旧实现会死锁在 BASELINE_PLAN_MISMATCH）。
        rework = _alignment(ctx["requirement_id"])
        rework["roadmap"]["phases"][0]["name"] = "Agent 工程返工阶段"
        rework["roadmap"]["phases"][0]["goal"] = "按 plan_fit 反馈补齐评测闭环"
        rework["diff_summary"] = "按 plan_fit 反馈返工执行版。"
        preview = (await driver.save_alignment(rework)).json()
        assert preview["status"] == "needs_confirmation", preview
        assert preview["applied"] is False
        applied = (await driver.save_alignment(rework, confirmed=True)).json()
        assert applied["status"] == "ok" and applied["applied"] is True, applied
        assert applied["execution_plan_id"] != first_applied["execution_plan_id"]
        artifact = sandbox.artifact(applied["execution_plan_id"])
        assert artifact["baseline_plan_id"] == baseline_id
        assert artifact["roadmap"]["phases"][0]["name"] == "Agent 工程返工阶段"
        await _assert_status(driver, 10, "任务执行与打卡", "detail_current_phase")


async def test_import_plan_creates_imported_baseline(sandbox):
    """F：空档案导入既有计划 → imported BaselinePlan → COMPANY_PENDING。"""
    plan_file = sandbox.tmp / "imported_plan.md"
    plan_file.write_text(
        "# 我的计划\n\n1. 学 Python 与 Agent\n2. 做 RAG 项目\n3. 投实习\n",
        encoding="utf-8",
    )
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()
        imported = await driver.import_plan(plan_file)
        imported.assert_contains("save_roadmap")
        await _assert_status(driver, 5, "培养方案规划", "save_roadmap")

        await driver.save_roadmap(ROADMAP)
        await _assert_status(driver, 6, "目标企业筛选", "select_target_companies")
        baseline_id = driver.profile["core_state"]["baseline_plan_id"]
        baseline = sandbox.artifact(baseline_id)
        assert baseline["meta"]["validation"]["imported"] is True
        assert baseline["roadmap"]["phases"]
