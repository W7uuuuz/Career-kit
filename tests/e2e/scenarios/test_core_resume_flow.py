"""简历解析、技能摸排门禁、计划导入与知识库检索。"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.data import HAVE, WANT, WHO
from e2e.drivers import flow

pytestmark = pytest.mark.e2e

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


async def test_resume_probing_gate_and_plan_import(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()

        resume_md = FIXTURES / "resumes" / "frontend.md"
        parsed = await driver.parse_resume(resume_md)
        parsed.assert_contains("林舟", "FastAPI", "intake")

        resume_txt = FIXTURES / "resumes" / "backend.txt"
        parsed_txt = await driver.parse_resume(resume_txt)
        parsed_txt.assert_contains("React")

        await driver.intake("who", WHO)
        await driver.intake("want", WANT)
        # 未确认证据 —— 摸排门禁必须阻塞
        await driver.intake(
            "have",
            {"skills": [{"skill": "Python", "evidence": "简历自述"}]},
        )
        blocked = await mcp.call("finalize_profile")
        blocked.assert_error("PROBING_REQUIRED")

        # 用户确认证据后放行
        await driver.intake("have", HAVE)
        finalized = await mcp.call("finalize_profile")
        finalized.assert_ok().assert_contains("档案已确认")
        assert driver.profile["summary"]

        # 知识库检索
        knowledge_file = sandbox.knowledge_dir / "jds" / "manual" / "agent.md"
        knowledge_file.parent.mkdir(parents=True, exist_ok=True)
        knowledge_file.write_text("# Agent JD\n熟悉 LangGraph 与 RAG。", encoding="utf-8")
        found = await driver.search_knowledge("Agent")
        found.assert_contains("Agent", "jds/manual/agent.md")

        # 导入既有计划文档
        plan_file = sandbox.tmp / "my_plan.md"
        plan_file.write_text(
            "# 我的计划\n\n1. 学 Python\n2. 做 RAG 项目\n3. 投实习\n",
            encoding="utf-8",
        )
        imported = await driver.import_plan(plan_file)
        imported.assert_contains("save_roadmap", "路线图")
