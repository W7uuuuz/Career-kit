"""桌面快捷方式与控制台启动脚本。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.desktop as desktop


def test_launcher_script_uses_plain_language(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "DATA_ROOT", tmp_path / "data")
    script = desktop.write_launcher_script()
    text = script.read_text(encoding="utf-8-sig")
    assert "打开控制台" in text
    assert "关闭控制台" in text
    assert "查看运行状态" in text
    assert "PID" not in text
    assert "src.web" in text


def test_ensure_shortcut_can_be_skipped(monkeypatch):
    monkeypatch.setenv("CAREER_KIT_SKIP_SHORTCUT", "1")
    path, error = desktop.ensure_console_shortcut()
    assert path is None and error == ""


def test_ensure_shortcut_creates_desktop_entry(monkeypatch, tmp_path):
    monkeypatch.delenv("CAREER_KIT_SKIP_SHORTCUT", raising=False)
    monkeypatch.setattr(desktop, "DATA_ROOT", tmp_path / "data")
    desktop_dir = tmp_path / "Desktop"
    monkeypatch.setenv("CAREER_KIT_DESKTOP_DIR", str(desktop_dir))
    monkeypatch.setattr(
        desktop,
        "_create_windows_shortcut",
        lambda script, folder: folder / "Career Kit.lnk",
    )
    path, error = desktop.ensure_console_shortcut()
    assert error == ""
    assert path.parent == desktop_dir
    assert path.name in {"Career Kit.lnk", "Career Kit.sh"}
    assert desktop.launcher_script_path().exists()
