"""桌面入口：在桌面创建直接启动职业地图的快捷方式。

快捷方式不再经过交互脚本：双击即启动（或复用已运行的实例）；
页面全部关闭后由 ``--exit-when-idle`` 自动停服。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .paths import DATA_ROOT

SHORTCUT_NAME = "Career Kit"
LOG_DIR_NAME = "console"
LAUNCH_ARGS = ("-m", "src.web", "--open", "--exit-when-idle")


def data_root() -> Path:
    return Path(DATA_ROOT)


def console_dir() -> Path:
    return data_root() / LOG_DIR_NAME


def runtime_state_path() -> Path:
    """控制台运行状态文件：PID、带 token 的访问地址。"""
    return data_root() / "web.json"


def project_root() -> Path:
    """源码/安装目录根路径，作为启动时的工作目录。"""
    return Path(__file__).resolve().parent.parent


def _windows_desktop_dir() -> Path:
    """读取 Windows 真实桌面目录（兼容 OneDrive 重定向）。"""
    try:
        import ctypes
        from ctypes import wintypes

        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
        if buffer.value:
            return Path(buffer.value)
    except Exception:  # noqa: BLE001 - 读取失败时退回默认路径
        pass
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Desktop"


def desktop_dir() -> Path | None:
    """桌面目录；``CAREER_KIT_DESKTOP_DIR`` 可覆盖，空字符串表示跳过。"""
    override = os.environ.get("CAREER_KIT_DESKTOP_DIR")
    if override is not None:
        return Path(override).expanduser() if override.strip() else None
    if os.name == "nt":
        return _windows_desktop_dir()
    return Path.home() / "Desktop"


def _ps_quote(value: str | Path) -> str:
    """PowerShell 单引号字符串转义。"""
    return "'" + str(value).replace("'", "''") + "'"


def _python_executable() -> str:
    """优先使用 pythonw，双击时不弹控制台窗口。"""
    if os.name == "nt":
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _create_windows_shortcut(desktop: Path) -> Path:
    link = desktop / f"{SHORTCUT_NAME}.lnk"
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "New-Item -ItemType Directory -Force -Path "
        f"{_ps_quote(desktop)} | Out-Null; "
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut({_ps_quote(link)}); "
        f"$shortcut.TargetPath = {_ps_quote(_python_executable())}; "
        f"$shortcut.Arguments = {_ps_quote(' '.join(LAUNCH_ARGS))}; "
        f"$shortcut.WorkingDirectory = {_ps_quote(project_root())}; "
        "$shortcut.WindowStyle = 7; "
        f"$shortcut.IconLocation = {_ps_quote(_python_executable())}; "
        "$shortcut.Description = 'Career Kit 职业地图'; "
        "$shortcut.Save(); "
        f"Write-Output {_ps_quote(link)}"
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "创建快捷方式失败").strip())
    return link


def _create_posix_shortcut(desktop: Path) -> Path:
    if sys.platform == "darwin":
        target = desktop / f"{SHORTCUT_NAME}.command"
    else:
        target = desktop / f"{SHORTCUT_NAME}.sh"
    content = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f'exec "{_python_executable()}" {" ".join(LAUNCH_ARGS)}\n'
    )
    target.write_text(content, encoding="utf-8")
    target.chmod(0o755)
    return target


def ensure_console_shortcut() -> tuple[Path | None, str]:
    """确保桌面快捷方式存在；返回 (路径, 错误文本)。"""
    if os.environ.get("CAREER_KIT_SKIP_SHORTCUT") == "1":
        return None, ""
    desktop = desktop_dir()
    if desktop is None:
        return None, ""
    try:
        desktop.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            return _create_windows_shortcut(desktop), ""
        return _create_posix_shortcut(desktop), ""
    except Exception as exc:  # noqa: BLE001 - 桌面不可写时不应阻断主流程
        return None, str(exc)


def main() -> int:
    path, error = ensure_console_shortcut()
    if path:
        print(f"桌面快捷方式已创建：{path}")
        return 0
    if error:
        print(f"桌面快捷方式创建失败：{error}", file=sys.stderr)
        return 1
    print("已跳过桌面快捷方式。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
