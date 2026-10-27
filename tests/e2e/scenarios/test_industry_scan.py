"""扫盲子流程：行业快照 -> 继续模式。"""

from __future__ import annotations

import pytest

from e2e.drivers import flow

pytestmark = pytest.mark.e2e


async def test_industry_scan_subflow(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()

        result = await mcp.call(
            "get_industry_snapshot",
            {"industry": "internet", "major": "计科", "city": "杭州"},
        )
        data = result.assert_ok().json()

        assert data["industry"]["id"] == "internet"
        assert data["roles"]
        assert data["major_match"]["match"] == "core"
        assert data["major_match"]["canonical"] == "计算机科学与技术"
        assert data["gaps"], "没有实时/去向数据时应如实列出缺口"
        assert data["saved_to_profile"] is True

        profile = sandbox.profile_json()
        assert profile["want"]["industry_id"] == "internet"
        assert profile["want"]["scan_completed_at"]
        assert profile["want"]["scan_summary"]
        assert profile["who"]["major"] == "计算机科学与技术"
        assert "industry" not in profile["want"]

        resumed = await mcp.call("start_session")
        resumed.assert_ok().assert_contains("扫盲继续模式")
