"""桌面快捷方式：双击直接启动职业地图，不再经过交互脚本。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.desktop as desktop


def test_launch_args_open_map_and_exit_when_idle():
    assert "-m" in desktop.LAUNCH_ARGS
    assert "src.web" in desktop.LAUNCH_ARGS
    assert "--open" in desktop.LAUNCH_ARGS
    assert "--exit-when-idle" in desktop.LAUNCH_ARGS


def test_ensure_shortcut_can_be_skipped(monkeypatch):
    monkeypatch.setenv("CAREER_KIT_SKIP_SHORTCUT", "1")
    path, error = desktop.ensure_console_shortcut()
    assert path is None and error == ""


def test_ensure_shortcut_creates_desktop_entry(monkeypatch, tmp_path):
    monkeypatch.delenv("CAREER_KIT_SKIP_SHORTCUT", raising=False)
    desktop_dir = tmp_path / "Desktop"
    monkeypatch.setenv("CAREER_KIT_DESKTOP_DIR", str(desktop_dir))
    monkeypatch.setattr(
        desktop,
        "_create_windows_shortcut",
        lambda folder: folder / "Career Kit.lnk",
    )

    path, error = desktop.ensure_console_shortcut()

    assert error == ""
    assert path.parent == desktop_dir
    assert path.name in {"Career Kit.lnk", "Career Kit.sh", "Career Kit.command"}


def test_shortcut_uses_project_root_as_workdir():
    root = desktop.project_root()
    assert (root / "src" / "web.py").is_file()
    assert (root / "src" / "desktop.py").is_file()
