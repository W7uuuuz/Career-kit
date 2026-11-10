"""服务器重启后的档案连续性、能力证据与目标变更检测。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from e2e.data import GAP, HAVE, ROADMAP, WANT, WHO
from e2e.drivers import flow

pytestmark = pytest.mark.e2e

JD_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "jds" / "agent_jd.md"


def _seed_research_fact(sandbox) -> None:
    """输入 fixture：补一份真实调研事实，让 gap/roadmap artifact 可正常同步。

    状态模型把市场调研视为可跳过步骤；这里保留 E2E 经典路径（正常调研后分析），
    不改产品断言。
    """
    name = sandbox.active_profile_name()
    conn = sqlite3.connect(sandbox.data_dir / "career-kit.db")
    try:
        row = conn.execute(
            "SELECT data FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        assert row is not None
        data = json.loads(row[0])
        data["research"] = {
            "report_md": "e2e://research.md",
            "jd_samples": [
                {"title": "AI Agent 开发", "company": "字节跳动", "url": "e2e://jd/1"}
            ],
            "cases": [],
            "counts": {"jd_samples": 1, "cases": 0},
            "generated_at": "2026-11-10T00:00:00",
        }
        conn.execute(
            "UPDATE profiles SET data = ? WHERE name = ?",
            (json.dumps(data, ensure_ascii=False), name),
        )
        conn.commit()
    finally:
        conn.close()


async def test_restart_keeps_progress_and_detects_goal_change(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()
        await driver.intake("who", WHO)
        await driver.intake("have", HAVE)
        await driver.intake("want", WANT)
        await driver.finalize()
        await driver.import_jd_file(JD_FILE)
        _seed_research_fact(sandbox)
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
        assert "当前档案" in status.text and "默认档案" in status.text

        # 目标变更检测：路线图之后改 want
        await driver.intake("want", {"target_role": "AI 应用工程师", "city": "上海"})
        changed = await driver.status()
        changed.assert_contains("目标", "analyze_gaps")
