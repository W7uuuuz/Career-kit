"""E2E 基础设施：隔离沙箱、真实 MCP stdio 会话、工具结果与产物记录。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[2]


class ToolResult:
    """一次 MCP 工具调用的结果。"""

    def __init__(self, name: str, args: dict[str, Any], text: str, duration: float):
        self.name = name
        self.args = args
        self.text = text
        self.duration = duration

    def json(self) -> dict[str, Any]:
        """解析 JSON 返回；非 JSON 时抛出清晰错误。"""
        try:
            data = json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{self.name} 返回的不是 JSON：{self.text[:300]}"
            ) from exc
        assert isinstance(data, dict), f"{self.name} 应返回 JSON 对象"
        return data

    def maybe_json(self) -> dict[str, Any]:
        """能解析就返回 dict，否则返回 {'_text': ...}。"""
        try:
            data = json.loads(self.text)
        except json.JSONDecodeError:
            return {"_text": self.text}
        return data if isinstance(data, dict) else {"_text": self.text}

    @property
    def ok(self) -> bool:
        return not self.maybe_json().get("isError")

    def assert_ok(self) -> "ToolResult":
        data = self.maybe_json()
        assert not data.get("isError"), (
            f"{self.name} 返回错误：{data.get('code')} {data.get('message')}\n"
            f"details={data.get('details')}"
        )
        return self

    def assert_contains(self, *needles: str) -> "ToolResult":
        for needle in needles:
            assert needle in self.text, (
                f"{self.name} 返回内容缺少 {needle!r}：{self.text[:300]}"
            )
        return self

    def assert_error(self, code: str | None = None) -> "ToolResult":
        data = self.maybe_json()
        assert data.get("isError") is True, (
            f"{self.name} 预期错误，实际成功：{self.text[:300]}"
        )
        if code:
            assert data.get("code") == code, (
                f"{self.name} 错误码应为 {code}，实际 {data.get('code')}"
            )
        return self


@dataclass
class Sandbox:
    """一次 E2E 的用户环境：独立数据目录、HOME、TMP 与产物目录。"""

    root: Path
    data_dir: Path
    home: Path
    tmp: Path
    artifacts: Path
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, test_name: str, run_root: Path) -> "Sandbox":
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in test_name)[:80]
        artifacts = run_root / safe
        artifacts.mkdir(parents=True, exist_ok=True)

        root = Path(tempfile.mkdtemp(prefix="ck_e2e_sandbox_"))
        data_dir = root / "data"
        home = root / "home"
        tmp = root / "tmp"
        for path in (data_dir, home, tmp):
            path.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env.update(
            {
                "CAREER_KIT_DATA_DIR": str(data_dir),
                "HOME": str(home),
                "USERPROFILE": str(home),
                "TMP": str(tmp),
                "TEMP": str(tmp),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "CAREER_KIT_E2E": "1",
            }
        )
        return cls(root=root, data_dir=data_dir, home=home, tmp=tmp, artifacts=artifacts, env=env)

    @property
    def profile_file(self) -> Path:
        return self.data_dir / "default.json"

    @property
    def knowledge_dir(self) -> Path:
        return self.data_dir / "knowledge"

    def active_profile_name(self) -> str:
        active = self.data_dir / ".active_profile"
        if not active.exists():
            return "default"
        name = active.read_text(encoding="utf-8").strip()
        if not name or not (self.data_dir / f"{name}.json").exists():
            return "default"
        return name

    def profile_json(self, name: str | None = None) -> dict[str, Any]:
        name = name or self.active_profile_name()
        path = self.data_dir / f"{name}.json"
        assert path.exists(), f"档案文件不存在：{path}"
        return json.loads(path.read_text(encoding="utf-8"))

    def finalize(self, failed: bool) -> None:
        """失败时保留数据快照；成功时清理临时沙箱。"""
        if failed:
            target = self.artifacts / "data"
            if not target.exists() and self.data_dir.exists():
                shutil.copytree(self.data_dir, target)
            return
        if os.environ.get("CAREER_KIT_E2E_KEEP") == "1":
            return
        shutil.rmtree(self.root, ignore_errors=True)


class McpSession:
    """通过 stdio 启动真实 MCP Server，并记录每次工具调用。"""

    def __init__(self, sandbox: Sandbox, timeout: float = 120.0):
        self.sandbox = sandbox
        self.timeout = timeout
        self.session: ClientSession | None = None
        self.tools: list[Any] = []
        self._stack: AsyncExitStack | None = None
        self._errlog = None
        self._transcript = sandbox.artifacts / "transcript.jsonl"
        self._call_count = 0

    async def __aenter__(self) -> "McpSession":
        return await self.start()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> "McpSession":
        self._errlog = open(self.sandbox.artifacts / "server.log", "a", encoding="utf-8")
        params = StdioServerParameters(
            command=os.sys.executable,
            args=["-m", "src.server"],
            cwd=str(self.sandbox.root),
            env=self.sandbox.env,
            encoding="utf-8",
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(
            stdio_client(params, errlog=self._errlog)
        )
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = list((await self.session.list_tools()).tools)
        return self

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        if self._errlog is not None:
            self._errlog.close()
            self._errlog = None
        self.session = None

    async def restart(self) -> "McpSession":
        await self.close()
        return await self.start()

    async def call(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        assert self.session is not None, "MCP 会话未启动"
        payload = args or {}
        started = time.monotonic()
        response = await asyncio.wait_for(
            self.session.call_tool(name, payload), timeout=timeout or self.timeout
        )
        duration = time.monotonic() - started
        text = response.content[0].text if response.content else ""
        result = ToolResult(name, payload, text, duration)
        self._record(result)
        return result

    def _record(self, result: ToolResult) -> None:
        self._call_count += 1
        entry = {
            "seq": self._call_count,
            "tool": result.name,
            "args": result.args,
            "result": result.text,
            "duration_ms": round(result.duration * 1000, 1),
        }
        with self._transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def tool_names(self) -> set[str]:
        return {tool.name for tool in self.tools}


class QualityRecorder:
    """把质量评估结果落盘，便于人工优化。"""

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox

    def write(self, report: dict[str, Any], filename: str = "quality.json") -> None:
        path = self.sandbox.artifacts / filename
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md = _quality_markdown(report)
        (self.sandbox.artifacts / filename.replace(".json", ".md")).write_text(
            md, encoding="utf-8"
        )


def _quality_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 质量评估：{report.get('name', '')}",
        "",
        f"- 总分：**{report.get('total', 0)}/100**",
        f"- 结论：{report.get('verdict', '')}",
        "",
        "| 维度 | 得分 | 权重 | 说明 |",
        "|------|------|------|------|",
    ]
    for metric in report.get("metrics", []):
        lines.append(
            f"| {metric['name']} | {metric['score']} | {metric['weight']} | {metric.get('detail', '')} |"
        )
    findings = report.get("findings") or []
    if findings:
        lines += ["", "## 可优化项", ""]
        lines += [f"- {item}" for item in findings]
    return "\n".join(lines) + "\n"
