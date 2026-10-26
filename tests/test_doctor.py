"""doctor 体检命令回归测试（不联网）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(cwd: Path, data_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CAREER_KIT_DATA_DIR"] = str(data_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "src.doctor"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_doctor_reports_healthy_server(tmp_path):
    result = _run(tmp_path, tmp_path / "data")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] MCP 服务" in result.stdout
    assert "35 个工具" in result.stdout
    assert "核心" in result.stdout
    assert "[OK] 数据目录" in result.stdout


def test_doctor_warns_on_bare_python_config(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "career-kit": {"command": "python", "args": ["-m", "src.server"]}
                }
            }
        ),
        encoding="utf-8",
    )
    result = _run(tmp_path, tmp_path / "data")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[WARN] 配置/.mcp.json" in result.stdout
    assert "裸 python" in result.stdout
