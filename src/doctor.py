"""Career Kit 安装体检。

只诊断、不修改用户配置；默认不联网。
用法：
    python -m src.doctor
    career-kit-doctor
    python -m src.doctor --browser --network
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

# 预期工具数：与 docs/tools.md、README 保持一致
EXPECTED_TOOL_COUNT = 39

# 核心工具：缺失即判定注册损坏（比单纯计数更可诊断）
CORE_TOOLS = (
    "start_session",
    "finalize_profile",
    "research_market",
    "gather_research_data",
    "analyze_gaps",
    "search_cases",
    "save_roadmap",
    "save_roadmap_audit",
    "generate_tasks",
    "checkin_task",
    "record_application",
    "get_weekly_review",
    "export_dashboard",
)


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def check_interpreter() -> Check:
    if sys.version_info < (3, 11):  # noqa: UP036 —— doctor 恰恰要给装错解释器的用户跑，运行时可能真低于 3.11
        return Check(
            "解释器",
            FAIL,
            f"Python {sys.version.split()[0]} 低于 3.11：{sys.executable}",
            "使用 Python 3.11+ 创建 venv 后重装：pip install -e .",
        )
    if "WindowsApps" in sys.executable:
        return Check(
            "解释器",
            WARN,
            f"当前可能是应用商店 Python：{sys.executable}",
            "建议使用项目 .venv 的绝对路径。",
        )
    return Check("解释器", OK, f"Python {sys.version.split()[0]} · {sys.executable}")


def check_mcp_package() -> Check:
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        return Check(
            "mcp 依赖",
            FAIL,
            f"无法导入 mcp：{exc}",
            f'用当前解释器安装："{sys.executable}" -m pip install -e .',
        )
    return Check("mcp 依赖", OK, f"mcp 可导入（{getattr(mcp, '__version__', 'unknown')}）")


def check_server() -> Check:
    try:
        import src.server as server
    except Exception as exc:
        return Check(
            "MCP 服务",
            FAIL,
            f"无法导入 src.server：{exc}",
            "确认当前目录是 Career Kit 仓库，且已执行 pip install -e .",
        )
    try:
        tools = server.mcp._tool_manager.list_tools()
        count = len(tools)
        names = {t.name for t in tools}
    except Exception as exc:
        return Check("MCP 服务", FAIL, f"无法读取工具列表：{exc}")
    missing = [name for name in CORE_TOOLS if name not in names]
    if missing:
        return Check(
            "MCP 服务",
            FAIL,
            f"核心工具缺失：{', '.join(missing)}",
            "确认代码版本与依赖一致；如刚升级，重启 Agent 会话。",
        )
    if count != EXPECTED_TOOL_COUNT:
        return Check(
            "MCP 服务",
            WARN,
            f"工具数为 {count}，预期 {EXPECTED_TOOL_COUNT}",
            "文档（docs/tools.md）与实际注册数不一致；确认代码版本。",
        )
    return Check(
        "MCP 服务", OK, f"{count} 个工具已注册，核心 {len(CORE_TOOLS)} 个齐全"
    )


def check_data_dir() -> Check:
    try:
        from src.paths import DATA_ROOT

        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=DATA_ROOT, prefix=".doctor-", delete=True):
            pass
    except Exception as exc:
        return Check(
            "数据目录",
            FAIL,
            f"数据目录不可写：{exc}",
            f"设置可写目录：CAREER_KIT_DATA_DIR={Path.home() / '.career-kit'}",
        )
    source = os.environ.get("CAREER_KIT_DATA_DIR", "默认 ~/.career-kit")
    return Check("数据目录", OK, f"{DATA_ROOT}（{source}）")


def check_browser() -> Check:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return Check(
            "浏览器内核",
            WARN,
            f"playwright 不可导入：{exc}",
            "抓取类工具需要：playwright install chromium",
        )

    try:
        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
    except Exception as exc:
        return Check(
            "浏览器内核",
            WARN,
            f"无法读取 Chromium 路径：{exc}",
            "执行：playwright install chromium",
        )
    if not executable.exists():
        return Check(
            "浏览器内核",
            WARN,
            f"Chromium 未安装：{executable}",
            "执行：python -m playwright install chromium",
        )
    return Check("浏览器内核", OK, str(executable))


def check_network() -> list[Check]:
    import httpx

    targets = {
        "BOSS直聘": "https://www.zhipin.com/",
        "腾讯": "https://join.qq.com/",
        "百度": "https://talent.baidu.com/",
        "阿里": "https://campus-talent.alibaba.com/",
        "牛客": "https://www.nowcoder.com/",
    }
    checks = []
    for name, url in targets.items():
        try:
            response = httpx.get(url, timeout=8, follow_redirects=True)
            status = OK if response.status_code < 500 else WARN
            checks.append(Check(f"网络/{name}", status, f"HTTP {response.status_code} · {url}"))
        except Exception as exc:
            checks.append(
                Check(
                    f"网络/{name}",
                    WARN,
                    f"不可达：{exc}",
                    "可先用 import_jd 导入本地 JD，不影响建档/规划。",
                )
            )
    return checks


def _load_jsonc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        return json.loads(text)


def _commands_from_config(path: Path) -> list[str]:
    data = _load_jsonc(path)
    if not isinstance(data, dict):
        return []
    if "mcpServers" in data:
        entry = (data.get("mcpServers") or {}).get("career-kit") or {}
    else:
        entry = (data.get("mcp") or {}).get("career-kit") or {}
    command = entry.get("command")
    if isinstance(command, list):
        return [str(x) for x in command]
    if isinstance(command, str):
        return [command]
    return []


def check_configs(cwd: Path) -> list[Check]:
    candidates = [
        cwd / ".mcp.json",
        cwd / "opencode.json",
        cwd / "opencode.jsonc",
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
    ]
    checks = []
    found = False
    expected = Path(sys.executable).resolve()

    for path in candidates:
        if not path.exists():
            continue
        try:
            command = _commands_from_config(path)
        except Exception as exc:
            checks.append(Check(f"配置/{path.name}", WARN, f"解析失败：{exc}"))
            continue
        if not command:
            continue
        found = True
        if command[0] in ("python", "python3"):
            checks.append(
                Check(
                    f"配置/{path.name}",
                    WARN,
                    "使用了裸 python，可能指向错误解释器",
                    f'改为："{sys.executable}" -m src.server',
                )
            )
            continue
        try:
            resolved = Path(command[0]).resolve()
        except OSError:
            resolved = Path(command[0])
        if resolved == expected:
            checks.append(Check(f"配置/{path.name}", OK, f"使用当前解释器：{resolved}"))
        else:
            checks.append(
                Check(
                    f"配置/{path.name}",
                    WARN,
                    f"解释器与当前不同：{resolved}",
                    f"建议改为：{expected}",
                )
            )

    if not found:
        checks.append(
            Check(
                "MCP 配置",
                WARN,
                "未检测到 career-kit 注册",
                "按 README 注册；opencode 使用项目 opencode.json 或全局 ~/.config/opencode/opencode.jsonc",
            )
        )
    return checks


def run_checks(*, browser: bool = False, network: bool = False) -> list[Check]:
    checks = [
        check_interpreter(),
        check_mcp_package(),
        check_server(),
        check_data_dir(),
    ]
    if browser:
        checks.append(check_browser())
    checks.extend(check_configs(Path.cwd()))
    if network:
        checks.extend(check_network())
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Career Kit 安装体检")
    parser.add_argument("--browser", action="store_true", help="检查 Playwright Chromium")
    parser.add_argument("--network", action="store_true", help="检查招聘站点连通性")
    args = parser.parse_args(argv)

    checks = run_checks(browser=args.browser, network=args.network)
    print("Career Kit Doctor")
    print("=" * 60)
    for check in checks:
        print(f"[{check.status}] {check.name}: {check.detail}")
        if check.hint and check.status != OK:
            print(f"       {check.hint}")
    failures = [c for c in checks if c.status == FAIL]
    warnings = [c for c in checks if c.status == WARN]
    print("=" * 60)
    print(f"结果：{len(checks) - len(failures) - len(warnings)} OK · {len(warnings)} WARN · {len(failures)} FAIL")
    if failures:
        print("请先修复 FAIL 项，再启动 MCP 服务。")
        return 1
    if warnings:
        print("存在 WARN；不阻断启动，但建议按提示修正。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
