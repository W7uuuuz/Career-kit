"""真实数据源 E2E（opt-in）：搜索、详情、字段与知识库落盘。"""

from __future__ import annotations

import os
import re

import pytest

from e2e.drivers import flow
from e2e.quality import QualityReport, evaluate_dataset

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_live]

_SOURCES = [
    s.strip()
    for s in os.environ.get("CAREER_KIT_E2E_SOURCES", "tencent,baidu,alibaba").split(",")
    if s.strip()
]

_SCOPE = {"tencent": "campus", "baidu": "social", "alibaba": "campus", "bytedance": "experienced", "nowcoder": "all"}


def _skip_if_disabled(company: str) -> None:
    if os.environ.get("CAREER_KIT_E2E_LIVE") != "1":
        pytest.skip("未设置 CAREER_KIT_E2E_LIVE=1，跳过真实数据源测试")
    if company not in _SOURCES:
        pytest.skip(f"{company} 不在 CAREER_KIT_E2E_SOURCES 中")


def _parse_jobs(text: str, company: str) -> list[dict]:
    rows = []
    current = None
    for line in text.splitlines():
        match = re.match(r"\d+\.\s+\*\*(.+?)\*\*(.*)", line)
        if match:
            current = {
                "title": match.group(1).strip(),
                "company": company,
                "location": "",
                "url": "",
            }
            tail = match.group(2)
            parts = [p.strip() for p in tail.split("|") if p.strip()]
            if parts:
                current["location"] = parts[0]
            if len(parts) > 1:
                current["salary"] = parts[1]
            rows.append(current)
            continue
        if current and "链接：" in line:
            current["url"] = line.split("链接：", 1)[1].strip()
    return [r for r in rows if r["title"]]


@pytest.mark.parametrize("company", _SOURCES)
async def test_live_source_quality(company, sandbox, quality):
    _skip_if_disabled(company)

    async with flow(sandbox) as (mcp, driver):
        await _run_source(company, driver, sandbox, quality)


async def _run_source(company, driver, sandbox, quality):
    sources = await driver.list_sources()
    sources.assert_contains(company)
    guide = await driver.guide(company)
    assert len(guide.text) > 100, f"{company} guide 过短"

    params = {"keyword": "AI", "limit": 2}
    scope = _SCOPE.get(company)
    if scope:
        params["scope"] = scope
    fetched = await driver.fetch_jobs(company, params)
    rows = _parse_jobs(fetched.text, company)
    assert rows, f"{company} 未解析到岗位：{fetched.text[:500]}"
    assert all(r["url"] for r in rows), rows
    if not any(r.get("salary") for r in rows):
        assert "未提供薪资" in fetched.text, "无薪资来源不应提示可汇总薪资行情"

    detail = await driver.fetch_detail(rows[0]["url"])
    assert len(detail.text) >= 80, f"{company} 详情过短：{detail.text[:200]}"

    files = [p for p in sandbox.knowledge_dir.rglob("*") if p.is_file()]
    assert files, f"{company} 抓取后知识库没有落盘"

    report = QualityReport(f"真实数据源：{company}")
    report.extend(evaluate_dataset(rows, [{"description": detail.text}], keyword="AI"))
    quality.write(report.to_dict(), filename=f"quality-{company}.json")

    assert report.total >= 60, report.findings()
