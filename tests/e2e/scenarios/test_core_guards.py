"""守卫与失败恢复：非法输入、摸排门禁、内容质量门、层级校验、抓取失败。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from e2e.data import GAP, HAVE, ROADMAP, WANT, WHO
from e2e.drivers import flow

pytestmark = pytest.mark.e2e

JD_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "jds" / "agent_jd.md"


async def test_guards_and_recovery(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()
        await driver.intake("who", WHO)
        version = sandbox.profile_json()["version"]

        bad_json = await mcp.call("intake", {"section": "who", "data": "{not-json"})
        bad_json.assert_error("INVALID_JSON")
        assert sandbox.profile_json()["version"] == version, "坏 JSON 不应写入档案"

        await driver.intake("want", WANT)
        await driver.intake(
            "have", {"skills": [{"skill": "Python", "evidence": "简历自述"}]}
        )
        probing = await mcp.call("finalize_profile")
        probing.assert_error("PROBING_REQUIRED")

        await driver.intake("have", HAVE)
        await driver.finalize()

        # 差距分析内容质量门：缺 source 必须拒绝
        unsourced = {
            "match_score": 60,
            "skill_gaps": [{"skill": "LangGraph", "priority": "high"}],
        }
        rejected = await mcp.call(
            "save_gap_analysis",
            {"gap_json": json.dumps(unsourced, ensure_ascii=False)},
        )
        rejected.assert_error("INCOMPLETE_ANALYSIS")
        rejected.assert_contains("source")

        await driver.save_gap(GAP)

        # 层级跳跃：小厂起点直接冲大厂实习 -> 返回硬校验问题
        bad_roadmap = json.loads(json.dumps(ROADMAP, ensure_ascii=False))
        bad_roadmap["start_level"] = "小厂"
        bad_roadmap["phases"][-1]["target_level"] = "大厂"
        result = await driver.save_roadmap(bad_roadmap)
        data = result.assert_ok().json()
        assert data["context"]["hard_issues"], data
        assert any("层级" in issue for issue in data["context"]["hard_issues"])

        # 未知企业源 -> 可诊断错误 + 可用列表
        unknown = await mcp.call(
            "fetch_company_jobs", {"company": "nonexistent", "params": "{}"}
        )
        unknown.assert_error("ANALYSIS_FAILED")
        unknown.assert_contains("available", "recovery")

        # 未知 URL -> 明确失败，不伪造详情
        unknown_detail = await mcp.call("fetch_jd_detail", {"url": "https://example.com/"})
        unknown_detail.assert_error("ANALYSIS_FAILED")

        # 失败后仍可走导入 JD 的恢复路径
        recovered = await driver.import_jd_file(JD_FILE)
        recovered.assert_ok()
