"""浏览器交互 E2E：生成 HTML 后真实打开、勾选打卡、localStorage 与重置。"""

from __future__ import annotations

from pathlib import Path

import pytest

from e2e.data import DETAIL, GAP, HAVE, ROADMAP, WANT, WHO
from e2e.drivers import flow

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_browser]

JD_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "jds" / "agent_jd.md"


async def test_dashboard_checkin_interaction(sandbox):
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
        await driver.detail_phase()
        await driver.save_detail(DETAIL)
        await driver.generate_tasks()

        await driver.export("roadmap")
        dashboard = sandbox.assets_dir / "默认档案" / "路线图" / "路线图.html"
        assert dashboard.exists(), f"未找到职业地图：{dashboard}"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright 未安装")

    screenshot = sandbox.artifacts / "dashboard-failure.png"
    try:
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Chromium 不可用，跳过浏览器 E2E：{exc}")

            page = await browser.new_page()
            console_errors: list[str] = []
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type == "error" else None,
            )
            await page.goto(dashboard.resolve().as_uri())
            await page.wait_for_selector("#total-pct")

            initial_pct = await page.locator("#total-pct").inner_text()
            checkbox = page.locator('input[type="checkbox"][data-action="once"]').first
            assert await checkbox.count() > 0, "仪表盘没有可勾选的一次性任务"
            # 勾选会触发整卡重渲染，用 click 而不是 check（check 会等待旧元素状态）
            await checkbox.click()
            await page.wait_for_timeout(300)
            after_pct = await page.locator("#total-pct").inner_text()

            keys = await page.evaluate("Object.keys(localStorage)")
            assert any(k.startswith("career-kit-checkins-") for k in keys), keys
            assert after_pct != initial_pct, (initial_pct, after_pct)

            await page.evaluate("window.confirm = () => true")
            await page.locator("#reset-btn").click()
            await page.wait_for_timeout(300)
            reset_pct = await page.locator("#total-pct").inner_text()
            assert reset_pct == initial_pct, (initial_pct, reset_pct)
            assert not console_errors, console_errors

            await browser.close()
    except Exception:
        try:
            await page.screenshot(path=str(screenshot), full_page=True)  # type: ignore[name-defined]
        except Exception:
            pass
        raise
