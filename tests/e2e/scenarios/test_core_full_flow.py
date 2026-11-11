"""核心全链路：建档 → 导入 JD → 差距分析 → 路线图 → 任务 → 打卡 → 洞察 → 产出。"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.data import DETAIL, GAP, HAVE, INSIGHT, ROADMAP, WANT, WHO
from e2e.drivers import flow
from e2e.quality import (
    QualityReport,
    evaluate_gap,
    evaluate_guidance,
    evaluate_profile,
    evaluate_roadmap,
    evaluate_tasks,
)

pytestmark = pytest.mark.e2e

JD_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "jds" / "agent_jd.md"


async def test_new_user_full_flow_quality(sandbox, quality):
    async with flow(sandbox) as (mcp, driver):
        assert {"start_session", "fetch_company_jobs", "save_roadmap"} <= mcp.tool_names()
        assert {"record_application", "get_weekly_review"} <= mcp.tool_names()

        await driver.begin()
        await driver.intake("who", WHO)
        await driver.intake("have", HAVE)
        await driver.intake("want", WANT)
        await driver.finalize()

        # 已有目标时 explore_goals 不应重复探索，而是确认当前目标
        explore = await driver.explore_goals()
        explore.assert_contains("目标")

        import_jd = await driver.import_jd_file(JD_FILE)
        await driver.search_knowledge("Agent")

        await driver.analyze_gaps()
        save_gap = await driver.save_gap(GAP)
        await driver.generate_roadmap()
        save_roadmap = await driver.save_roadmap(ROADMAP)

        await driver.generate_tasks()
        await driver.detail_phase()
        await driver.save_detail(DETAIL)
        tasks_result = await driver.generate_tasks()
        next_tasks = await driver.next_tasks()

        assert len(driver.tasks) >= 3, driver.tasks
        assert {t["phase_id"] for t in driver.tasks} == {"phase_1"}, (
            "只生成当前阶段任务，后续阶段保留里程碑"
        )
        daily_id = driver.task_id_by_name("学习 LangGraph")
        once_id = driver.task_id_by_name("实现工具调用 Agent")
        await driver.checkin(daily_id, amount=1, notes="E2E 每日推进")
        await driver.checkin(once_id, notes="E2E 完成 demo")

        # 求职漏斗：记录投递 → 推进面试 → 周检视
        await driver.record_application("字节跳动", "Agent 工程师", notes="E2E 登记投递")
        funnel_step = await driver.record_application(
            "字节跳动", "Agent 工程师", status="interview", application_id="app_001",
            notes="E2E 推进面试",
        )
        funnel_step.assert_contains("trigger_insight")
        dup = await mcp.call(
            "record_application",
            {"company": "字节跳动", "role": "Agent 工程师"},
        )
        dup_data = dup.assert_ok().json()
        assert dup_data.get("duplicate") is True, dup.text
        weekly = await driver.weekly_review()
        weekly.assert_contains("周检视")
        assert sandbox.profile_json()["applications"], "投递记录未落盘"

        insight_prompt = await driver.trigger_insight("stage_audit")
        apply_insight = await driver.apply_insight(INSIGHT)
        progress = await driver.progress()
        status = await driver.status()

        profile = driver.profile
        assert profile["gap"]["skill_gaps"], profile["gap"]
        assert profile["plan"]["roadmap"]["phases"], profile["plan"]
        assert any(c["task_id"] == once_id for c in profile["checkins"])
        assert profile["have"].get("capability_evidence"), profile["have"]
        assert profile["adjustments"], profile["adjustments"]

        report = QualityReport("全新用户全链路")
        report.extend(evaluate_profile(profile))
        report.extend(evaluate_gap(profile["gap"]))
        report.extend(evaluate_roadmap(profile["plan"]["roadmap"], profile["gap"]))
        report.extend(evaluate_tasks(profile["tasks"]))
        report.extend(
            evaluate_guidance(
                [
                    import_jd,
                    save_gap,
                    save_roadmap,
                    tasks_result,
                    next_tasks,
                    insight_prompt,
                    apply_insight,
                    progress,
                    status,
                ]
            )
        )
        quality.write(report.to_dict())

        assert report.total >= 70, report.findings()
        for metric in report.metrics:
            assert metric.score >= 50, (
                f"{metric.name} 质量过低（{metric.score}）：{metric.detail}"
            )
        guidance_metrics = [
            m for m in report.metrics if "下一步指引" in m.name or "指引可执行" in m.name
        ]
        assert guidance_metrics, "缺少指引质量指标"
        assert all(m.score >= 75 for m in guidance_metrics), [
            (m.name, m.score, m.detail) for m in guidance_metrics
        ]
