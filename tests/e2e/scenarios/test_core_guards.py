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

        # BUG-021 门禁：证据齐全但缺 authorship/control_level/self_assessment 仍阻塞
        await driver.intake(
            "have",
            {"skills": [{"skill": "Python", "evidence": "课程项目", "user_verified": True}]},
        )
        probing2 = await mcp.call("finalize_profile")
        probing2.assert_error("PROBING_REQUIRED")
        probing2.assert_contains("authorship")

        await driver.intake("have", HAVE)
        await driver.finalize()

        # 差距分析：缺 source 为建议，不阻断保存
        unsourced = {
            "match_score": 60,
            "skill_gaps": [{"skill": "LangGraph", "priority": "high"}],
        }
        advised = await mcp.call(
            "save_gap_analysis",
            {"gap_json": json.dumps(unsourced, ensure_ascii=False)},
        )
        advised_data = advised.assert_ok().json()
        assert any(
            a["code"] == "gap_missing_source" for a in advised_data["context"]["advisories"]
        )

        # AI 作者身份：提示为 advisory
        no_flag = json.loads(json.dumps(GAP, ensure_ascii=False))
        no_flag["resume_red_flags"] = [
            rf for rf in no_flag["resume_red_flags"]
            if "AI" not in rf["signal"]
        ]
        no_flag["skill_gaps"] = [
            {**sg, "source": "导入 JD：AI Agent 开发工程师"} for sg in no_flag["skill_gaps"]
        ]
        flagged = await mcp.call(
            "save_gap_analysis",
            {"gap_json": json.dumps(no_flag, ensure_ascii=False)},
        )
        flagged_data = flagged.assert_ok().json()
        assert any(
            a["code"] == "ai_authorship_unmentioned"
            for a in flagged_data["context"]["advisories"]
        )

        await driver.save_gap(GAP)

        # 层级跨越：保存成功，给出 level_jump 建议（不再硬拒绝）
        bad_roadmap = json.loads(json.dumps(ROADMAP, ensure_ascii=False))
        bad_roadmap["start_level"] = "小厂"
        bad_roadmap["phases"][-1]["target_level"] = "大厂"
        result = await mcp.call(
            "save_roadmap",
            {"roadmap_json": json.dumps(bad_roadmap, ensure_ascii=False)},
        )
        data = result.assert_ok().json()
        assert any(a["code"] == "level_jump" for a in data["context"]["advisories"]), data

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
