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
    assert "52 个工具" in result.stdout
    assert "核心" in result.stdout
    assert "[OK] 数据目录" in result.stdout
    # 包版本检查必须出现在输出中；健康环境允许 WARN（不要求 0 FAIL）
    assert "包版本" in result.stdout
    assert "0 FAIL" in result.stdout


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


def test_check_package_version_matches(monkeypatch):
    import importlib.metadata

    from src import doctor

    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: doctor.EXPECTED_PACKAGE_VERSION
    )
    check = doctor.check_package_version()
    assert check.status == doctor.OK
    assert check.name == "包版本"
    assert check.detail == f"career-kit {doctor.EXPECTED_PACKAGE_VERSION}"


def test_check_package_version_mismatch(monkeypatch):
    import importlib.metadata

    from src import doctor

    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.1.0")
    check = doctor.check_package_version()
    assert check.status == doctor.WARN
    assert "0.1.0" in check.detail and doctor.EXPECTED_PACKAGE_VERSION in check.detail
    assert "uv pip install -e ." in check.hint


def test_check_package_version_not_installed(monkeypatch):
    import importlib.metadata

    from src import doctor

    def _raise(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    check = doctor.check_package_version()
    assert check.status == doctor.WARN
    assert "未以包形式安装" in check.detail


def test_expected_package_version_matches_metadata_files():
    """doctor 的预期版本必须与 pyproject.toml / server.json 一致。"""
    import json
    import tomllib
    from pathlib import Path

    from src import doctor

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == doctor.EXPECTED_PACKAGE_VERSION
    assert server["version"] == doctor.EXPECTED_PACKAGE_VERSION
    assert server["packages"][0]["version"] == doctor.EXPECTED_PACKAGE_VERSION
