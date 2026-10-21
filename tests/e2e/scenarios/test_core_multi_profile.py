"""多档案：列表、切换、回收站删除、恢复与活跃档案回退。"""

from __future__ import annotations

import json

import pytest

from e2e.data import WANT, WHO
from e2e.drivers import flow

pytestmark = pytest.mark.e2e


async def test_multi_profile_switch_delete_restore(sandbox):
    async with flow(sandbox) as (mcp, driver):
        await driver.begin()
        await driver.intake("who", WHO)
        await driver.intake("want", WANT)

        # 模拟用户已有两份档案
        for name, who in (("alice", "Alice"), ("bob", "Bob")):
            (sandbox.data_dir / f"{name}.json").write_text(
                json.dumps(
                    {"who": {"name": who}, "want": {"target_role": "AI 工程师"}},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        listed = await driver.list_profiles()
        listed.assert_contains("default", "alice", "bob", "当前使用")

        switched = await driver.switch_profile("alice")
        switched.assert_contains("已切换到档案「alice」")
        status = await driver.status()
        status.assert_contains("alice")

        await driver.intake("who", {"name": "Alice", "city": "上海"})
        assert driver.profile["who"]["city"] == "上海"
        assert driver.profile["who"]["name"] == "Alice"
        assert sandbox.active_profile_name() == "alice"

        deleted = await driver.delete_profile("bob")
        deleted.assert_contains("已删除档案「bob」", "回收站")
        trash = await driver.list_trash()
        trash.assert_contains("bob")

        restored = await driver.restore_profile("bob")
        restored.assert_contains("已恢复档案「bob」")

        # 删除当前活跃档案 -> 回退 default
        await driver.delete_profile("alice")
        fallback = await driver.status()
        fallback.assert_contains("default")
        await driver.restore_profile("alice")

        # default 数据未被其他档案污染
        default = sandbox.profile_json("default")
        assert default["who"]["name"] == WHO["name"]
        assert default["want"]["target_role"] == WANT["target_role"]
