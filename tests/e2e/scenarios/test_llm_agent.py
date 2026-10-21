"""真实 LLM Agent E2E（opt-in）：验证选工具、守规则与最终状态。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from e2e.drivers import LLMDriver, flow
from e2e.harness import REPO_ROOT
from e2e.quality import QualityReport, evaluate_profile

pytestmark = [pytest.mark.e2e, pytest.mark.e2e_llm]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="未设置 ANTHROPIC_API_KEY",
)
async def test_llm_agent_completes_onboarding(sandbox, quality) -> None:
    resume = sandbox.tmp / "resume.md"
    shutil.copyfile(FIXTURES / "resumes" / "frontend.md", resume)

    prompt = (REPO_ROOT / ".claude" / "commands" / "career-kit.md").read_text(encoding="utf-8")
    prompt = prompt.replace("$ARGUMENTS", "转行 AI Agent 开发")

    async with flow(sandbox) as (mcp, _deterministic):
        llm = LLMDriver(mcp, sandbox)
        result = await llm.run(
            [
                "你好，我想转行 AI，但不确定具体方向。",
                "我是应届生，会 Python 和 React，做过 FastAPI 项目。",
                f"这是我简历的路径：{resume}",
                "我想去深圳做 AI Agent 开发，薪资 20k-30k。",
                "请基于真实 JD 做差距分析，然后生成路线图和第一阶段任务。",
                "第一个任务做完了。",
            ],
            system_prompt=prompt,
            max_tool_iterations=10,
        )

    called = [c["tool"] for c in result["calls"]]
    called_set = set(called)
    assert "start_session" in called_set, called
    assert "intake" in called_set, called
    assert "finalize_profile" in called_set, called

    discovery = {"explore_goals", "import_jd", "import_jd_file", "fetch_company_jobs", "parse_resume"}
    assert called_set & discovery, f"Agent 没有获取目标或数据：{called}"

    planning = {"save_gap_analysis", "save_roadmap", "generate_tasks"}
    assert called_set & planning, f"Agent 没有进入分析/规划：{called}"

    profile = sandbox.profile_json()
    assert profile["who"], profile
    assert profile["want"], profile
    assert profile.get("summary"), profile

    error_rate = len(result["errors"]) / max(1, len(called))
    report = QualityReport("LLM Agent 建档与推进")
    report.extend(evaluate_profile(profile))
    report.add(
        "关键工具覆盖",
        min(100, len(called_set & (discovery | planning)) / 5 * 100),
        6,
        f"调用：{sorted(called_set)}",
    )
    report.add(
        "工具错误率",
        max(0, 100 - error_rate * 100),
        4,
        f"{len(result['errors'])}/{len(called)} 次调用报错",
    )
    report.add("工具调用数", 100 if len(called) <= 40 else 60, 2, f"{len(called)} 次")
    quality.write(report.to_dict(), filename="quality-llm.json")

    assert error_rate <= 0.3, result["errors"][:3]
    assert report.total >= 60, report.findings()
