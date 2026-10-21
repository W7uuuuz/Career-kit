"""LLM 首屏引导 E2E：第一轮必须简短、先问简历和目标，不倒手册。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from e2e.drivers import LLMDriver, flow
from e2e.harness import REPO_ROOT
from e2e.quality import QualityReport

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="未设置 ANTHROPIC_API_KEY",
)
async def test_llm_first_reply_is_short_and_asks_questions(sandbox, quality) -> None:
    prompt = (REPO_ROOT / ".claude" / "commands" / "career-kit.md").read_text(encoding="utf-8")
    prompt = prompt.replace("$ARGUMENTS", "转行 AI，但不知道具体方向")

    async with flow(sandbox) as (mcp, _deterministic):
        llm = LLMDriver(mcp, sandbox)
        result = await llm.run(
            ["你好，我想转行，但不知道做什么。"],
            system_prompt=prompt,
            max_tool_iterations=6,
        )

    called = {c["tool"] for c in result["calls"]}
    assert "start_session" in called, result["calls"]
    assert "analyze_gaps" not in called, "首轮不应直接进入差距分析"

    assistant_texts = [
        item["text"]
        for item in result["transcript"]
        if item.get("role") == "assistant" and item.get("text")
    ]
    assert assistant_texts, result["transcript"]
    first = assistant_texts[0]

    assert len(first) <= 1200, f"首屏过长（{len(first)} 字）：{first[:500]}"
    assert "Phase 1" not in first and "## 完整流程" not in first, first[:500]
    assert any(token in first for token in ("简历", "目标", "方向")), first[:500]

    report = QualityReport("LLM 首屏引导")
    report.add("首屏长度", 100 if len(first) <= 600 else 60, 4, f"{len(first)} 字")
    report.add("是否倒手册", 100 if "Phase 1" not in first else 0, 4, "未复述内部手册" if "Phase 1" not in first else "复述了内部手册")
    report.add("是否问关键问题", 100 if any(t in first for t in ("简历", "目标", "方向")) else 0, 2, "问了简历/目标")
    report.add("是否过早分析", 100 if "analyze_gaps" not in called else 0, 3, f"调用：{sorted(called)}")
    quality.write(report.to_dict(), filename="quality-onboarding.json")

    assert report.total >= 70, report.findings()
