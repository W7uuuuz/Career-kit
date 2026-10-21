"""服务器重启后的档案连续性、能力证据与目标变更检测。"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.data import GAP, HAVE, ROADMAP, WANT, WHO
from e2e.drivers import flow

pytestmark = pytest.mark.e2e

JD_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "jds" / "agent_jd.md"


async def test_restart_keeps_progress_and_detects_goal_change(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()
        await driver.intake("who", WHO)
        await driver.intake("have", HAVE)
        await driver.intake("want", WANT)
        await driver.finalize()
        await driver.import_jd_file(JD_FILE)
        await driver.save_gap(GAP)
        await driver.save_roadmap(ROADMAP)
        await driver.generate_tasks()

        first_id = driver.task_ids()[0]
        await driver.checkin(first_id, notes="重启前完成")
        before = driver.profile
        assert before["checkins"], before
        assert before["have"].get("capability_evidence"), before["have"]
        version_before = before["version"]

        await mcp.restart()

        after = driver.profile
        assert after["version"] == version_before
        assert len(after["tasks"]) == len(before["tasks"])
        assert len(after["checkins"]) == len(before["checkins"])
        assert after["have"].get("capability_evidence")

        status = await driver.status()
        status.assert_contains("execution")
        assert "当前档案" in status.text and "default" in status.text

        # 目标变更检测：路线图之后改 want
        await driver.intake("want", {"target_role": "AI 应用工程师", "city": "上海"})
        changed = await driver.status()
        changed.assert_contains("目标", "analyze_gaps")
