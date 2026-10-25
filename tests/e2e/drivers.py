"""E2E 驱动：确定性用户与真实 LLM Agent 两种驱动。"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from .harness import McpSession, Sandbox, ToolResult


@asynccontextmanager
async def flow(sandbox: Sandbox):
    """在测试体内管理 MCP 生命周期，避免异步 fixture 跨任务退出。"""
    mcp = McpSession(sandbox)
    await mcp.start()
    try:
        yield mcp, FlowDriver(mcp, sandbox)
    finally:
        await mcp.close()


class FlowDriver:
    """确定性用户驱动——每一步都走 MCP 协议，并校验关键状态。"""

    def __init__(self, mcp: McpSession, sandbox: Sandbox):
        self.mcp = mcp
        self.sandbox = sandbox

    async def begin(self) -> ToolResult:
        result = await self.mcp.call("start_session")
        result.assert_ok().assert_contains("Career Kit")
        return result

    async def intake(self, section: str, data: dict[str, Any]) -> ToolResult:
        result = await self.mcp.call(
            "intake", {"section": section, "data": json.dumps(data, ensure_ascii=False)}
        )
        result.assert_ok().assert_contains("已记录")
        return result

    async def finalize(self) -> ToolResult:
        return (await self.mcp.call("finalize_profile")).assert_ok()

    async def parse_resume(self, path: Path) -> ToolResult:
        return (await self.mcp.call("parse_resume", {"file_path": str(path)})).assert_ok()

    async def explore_goals(self) -> ToolResult:
        return (await self.mcp.call("explore_goals")).assert_ok()

    async def import_jd(self, text: str) -> ToolResult:
        return (await self.mcp.call("import_jd", {"jd_text": text})).assert_ok()

    async def import_jd_file(self, path: Path) -> ToolResult:
        return (await self.mcp.call("import_jd_file", {"file_path": str(path)})).assert_ok()

    async def import_plan(self, path: Path) -> ToolResult:
        return (await self.mcp.call("import_plan", {"file_path": str(path)})).assert_ok()

    async def analyze_gaps(self) -> ToolResult:
        return (await self.mcp.call("analyze_gaps")).assert_ok()

    async def save_gap(self, gap: dict[str, Any]) -> ToolResult:
        return (
            await self.mcp.call(
                "save_gap_analysis",
                {"gap_json": json.dumps(gap, ensure_ascii=False)},
            )
        ).assert_ok()

    async def generate_roadmap(self) -> ToolResult:
        return (await self.mcp.call("generate_roadmap")).assert_ok()

    async def save_roadmap(self, roadmap: dict[str, Any]) -> ToolResult:
        return (
            await self.mcp.call(
                "save_roadmap",
                {"roadmap_json": json.dumps(roadmap, ensure_ascii=False)},
            )
        ).assert_ok()

    async def generate_tasks(self) -> ToolResult:
        return (await self.mcp.call("generate_tasks")).assert_ok()

    async def detail_phase(self) -> ToolResult:
        return (await self.mcp.call("detail_current_phase")).assert_ok()

    async def save_detail(self, detail: dict[str, Any]) -> ToolResult:
        return (
            await self.mcp.call(
                "save_current_detail",
                {"detail_json": json.dumps(detail, ensure_ascii=False)},
            )
        ).assert_ok()

    async def next_tasks(self) -> ToolResult:
        return (await self.mcp.call("get_next_tasks")).assert_ok()

    async def checkin(
        self,
        task_id: str,
        *,
        status: str = "completed",
        notes: str = "",
        amount: float = 0,
    ) -> ToolResult:
        return (
            await self.mcp.call(
                "checkin_task",
                {"task_id": task_id, "status": status, "notes": notes, "amount": amount},
            )
        ).assert_ok()

    async def record_application(
        self,
        company: str,
        role: str = "",
        *,
        status: str = "",
        application_id: str = "",
        channel: str = "",
        note: str = "",
    ) -> ToolResult:
        args = {"company": company}
        for key, value in (("role", role), ("status", status), ("application_id", application_id),
                           ("channel", channel), ("note", note)):
            if value:
                args[key] = value
        return (
            await self.mcp.call("record_application", args)
        ).assert_ok()

    async def weekly_review(self, days: int = 7) -> ToolResult:
        return (await self.mcp.call("get_weekly_review", {"days": days})).assert_ok()

    async def progress(self) -> ToolResult:
        return (await self.mcp.call("get_progress")).assert_ok()

    async def status(self) -> ToolResult:
        return (await self.mcp.call("get_workflow_status")).assert_ok()

    async def trigger_insight(self, trigger_type: str, description: str = "") -> ToolResult:
        return (
            await self.mcp.call(
                "trigger_insight",
                {"trigger_type": trigger_type, "event_description": description},
            )
        ).assert_ok()

    async def apply_insight(self, insight: dict[str, Any]) -> ToolResult:
        return (
            await self.mcp.call(
                "apply_insight",
                {"insight_json": json.dumps(insight, ensure_ascii=False)},
            )
        ).assert_ok()

    async def export(self, mode: str = "progress") -> ToolResult:
        return (await self.mcp.call("export_dashboard", {"mode": mode})).assert_ok()

    async def list_sources(self) -> ToolResult:
        return (await self.mcp.call("list_data_sources")).assert_ok()

    async def guide(self, company: str) -> ToolResult:
        return (await self.mcp.call("get_scraper_guide", {"company": company})).assert_ok()

    async def search_knowledge(self, query: str) -> ToolResult:
        return (await self.mcp.call("search_knowledge", {"query": query})).assert_ok()

    async def fetch_jobs(self, company: str, params: dict[str, Any]) -> ToolResult:
        return (
            await self.mcp.call(
                "fetch_company_jobs",
                {"company": company, "params": json.dumps(params, ensure_ascii=False)},
            )
        ).assert_ok()

    async def fetch_detail(self, url: str) -> ToolResult:
        return (await self.mcp.call("fetch_jd_detail", {"url": url})).assert_ok()

    async def list_profiles(self) -> ToolResult:
        return (await self.mcp.call("list_profiles")).assert_ok()

    async def switch_profile(self, name: str) -> ToolResult:
        return (await self.mcp.call("switch_profile", {"profile_name": name})).assert_ok()

    async def delete_profile(self, name: str, confirm: str = "true") -> ToolResult:
        return (
            await self.mcp.call("delete_profile", {"profile_name": name, "confirm": confirm})
        ).assert_ok()

    async def list_trash(self) -> ToolResult:
        return (await self.mcp.call("list_trash")).assert_ok()

    async def restore_profile(self, name: str) -> ToolResult:
        return (await self.mcp.call("restore_profile", {"profile_name": name})).assert_ok()

    # ------------------------------------------------------------------ state

    @property
    def profile(self) -> dict[str, Any]:
        return self.sandbox.profile_json()

    @property
    def tasks(self) -> list[dict[str, Any]]:
        return list(self.profile.get("tasks") or [])

    def task_id_by_name(self, needle: str) -> str:
        for task in self.tasks:
            if needle in str(task.get("name", "")):
                return str(task["id"])
        raise AssertionError(f"没有找到名称包含 {needle!r} 的任务：{[t.get('name') for t in self.tasks]}")

    def task_ids(self) -> list[str]:
        return [str(t["id"]) for t in self.tasks]


class LLMDriver:
    """真实 LLM Agent 驱动——工具 schema 来自 MCP，对话按用户剧本推进。"""

    def __init__(
        self,
        mcp: McpSession,
        sandbox: Sandbox,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        import anthropic

        self.mcp = mcp
        self.sandbox = sandbox
        self.model = (
            model
            or os.environ.get("CAREER_KIT_E2E_LLM_MODEL")
            or "mimo-v2.5"
        )
        self.base_url = (
            base_url
            or os.environ.get("CAREER_KIT_E2E_LLM_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or "https://token-plan-cn.xiaomimimo.com/anthropic"
        )
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            base_url=self.base_url,
        )
        self.calls: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []

    async def run(
        self,
        user_turns: list[str],
        *,
        system_prompt: str,
        max_tool_iterations: int = 10,
    ) -> dict[str, Any]:
        tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in self.mcp.tools
        ]
        messages: list[dict[str, Any]] = []

        for turn_no, user_text in enumerate(user_turns, 1):
            messages.append({"role": "user", "content": user_text})
            self.transcript.append({"turn": turn_no, "role": "user", "text": user_text})

            for _ in range(max_tool_iterations):
                response = await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model,
                    max_tokens=2048,
                    system=system_prompt,
                    tools=tools,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": response.content})
                text = "".join(
                    getattr(block, "text", "")
                    for block in response.content
                    if getattr(block, "type", "") == "text"
                )
                if text:
                    self.transcript.append(
                        {"turn": turn_no, "role": "assistant", "text": text}
                    )

                tool_calls = [
                    block
                    for block in response.content
                    if getattr(block, "type", "") == "tool_use"
                ]
                if not tool_calls:
                    break

                tool_results = []
                for call in tool_calls:
                    result = await self.mcp.call(call.name, dict(call.input or {}))
                    self.calls.append(
                        {"tool": call.name, "args": dict(call.input or {}), "ok": result.ok}
                    )
                    if not result.ok:
                        self.errors.append({"tool": call.name, "result": result.text})
                    self.transcript.append(
                        {
                            "turn": turn_no,
                            "role": "tool",
                            "tool": call.name,
                            "args": dict(call.input or {}),
                            "result": result.text[:2000],
                        }
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": result.text,
                        }
                    )
                messages.append({"role": "user", "content": tool_results})

        path = self.sandbox.artifacts / "llm-transcript.json"
        path.write_text(
            json.dumps(
                {
                    "model": self.model,
                    "calls": self.calls,
                    "errors": self.errors,
                    "transcript": self.transcript,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"calls": self.calls, "errors": self.errors, "transcript": self.transcript}
