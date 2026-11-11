"""桌面入口：生成控制台启动脚本，并在用户桌面放一个快捷方式。

新版本只保留本地网页控制台。路线图定稿时由 ``save_roadmap`` 调用
``ensure_console_shortcut``，用户双击桌面快捷方式即可启动/关闭控制台。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .paths import DATA_ROOT

SHORTCUT_NAME = "Career Kit"
SCRIPT_NAME = "career-kit-console.ps1"
LOG_DIR_NAME = "console"


def data_root() -> Path:
    return Path(DATA_ROOT)


def console_dir() -> Path:
    return data_root() / LOG_DIR_NAME


def launcher_script_path() -> Path:
    return console_dir() / SCRIPT_NAME


def runtime_state_path() -> Path:
    """控制台运行状态文件：PID、带 token 的访问地址。"""
    return data_root() / "web.json"


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


def _launcher_script() -> str:
    python = _ps_quote(sys.executable)
    state = _ps_quote(runtime_state_path())
    logs = _ps_quote(console_dir())
    workdir = _ps_quote(data_root())
    template = r"""$ErrorActionPreference = "SilentlyContinue"
$Python = @@PYTHON@@
$StateFile = @@STATE@@
$LogDir = @@LOGDIR@@
$WorkDir = @@WORKDIR@@

function Read-ConsoleState {
    if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
    try {
        return Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-RunningConsole {
    $state = Read-ConsoleState
    if (-not $state -or -not $state.pid) { return $null }
    $process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
    if ($process) { return $state }
    return $null
}

function Open-Console {
    $state = Get-RunningConsole
    if ($state) {
        Write-Host "控制台已经在运行，正在为您打开页面。"
        if ($state.url) { Start-Process $state.url | Out-Null }
        return
    }
    Remove-Item -LiteralPath $StateFile -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $outLog = Join-Path $LogDir "console.log"
    $errLog = Join-Path $LogDir "console.err.log"
    Write-Host "正在启动 Career Kit，请稍候……"
    $process = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "src.web", "--open") `
        -WorkingDirectory $WorkDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $state = Get-RunningConsole
        if ($state) { break }
        if ($process -and $process.HasExited) { break }
    }
    if ($state) {
        Write-Host "已启动，页面会在浏览器中自动打开。"
    } else {
        Write-Host "启动没有成功，请稍后重试；如果多次失败，请重新安装 Career Kit。"
    }
}

function Stop-Console {
    $state = Get-RunningConsole
    if (-not $state) {
        Write-Host "当前没有正在运行的控制台。"
        Remove-Item -LiteralPath $StateFile -ErrorAction SilentlyContinue
        return
    }
    Stop-Process -Id ([int]$state.pid) -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StateFile -ErrorAction SilentlyContinue
    Write-Host "控制台已关闭。"
}

function Show-Status {
    $state = Get-RunningConsole
    if ($state) {
        Write-Host "控制台正在运行。"
    } else {
        Write-Host "控制台当前没有运行。"
    }
}

function Show-Menu {
    while ($true) {
        Write-Host ""
        Write-Host "Career Kit 控制台"
        Write-Host "请选择要进行的操作："
        Write-Host "  1. 打开控制台"
        Write-Host "  2. 关闭控制台"
        Write-Host "  3. 查看运行状态"
        Write-Host "  0. 退出"
        $choice = Read-Host "请输入数字后按回车"
        switch ($choice) {
            "1" { Open-Console }
            "2" { Stop-Console }
            "3" { Show-Status }
            "0" { return }
            default { Write-Host "请输入 0 到 3 之间的数字。" }
        }
    }
}

Show-Menu
"""
    return (
        template.replace("@@PYTHON@@", python)
        .replace("@@STATE@@", state)
        .replace("@@LOGDIR@@", logs)
        .replace("@@WORKDIR@@", workdir)
    )


def write_launcher_script() -> Path:
    target = launcher_script_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = _launcher_script()
    if not target.exists() or target.read_text(encoding="utf-8-sig") != content:
        target.write_text(content, encoding="utf-8-sig")
    return target


def _create_windows_shortcut(script: Path, desktop: Path) -> Path:
    link = desktop / f"{SHORTCUT_NAME}.lnk"
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "New-Item -ItemType Directory -Force -Path "
        f"{_ps_quote(desktop)} | Out-Null; "
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut({_ps_quote(link)}); "
        "$shortcut.TargetPath = (Get-Command powershell.exe).Source; "
        "$shortcut.Arguments = "
        f"'-NoProfile -ExecutionPolicy Bypass -File \"{script}\"'; "
        f"$shortcut.WorkingDirectory = {_ps_quote(data_root())}; "
        "$shortcut.Description = 'Career Kit 控制台'; "
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


def _create_posix_shortcut(script: Path, desktop: Path) -> Path:
    if sys.platform == "darwin":
        target = desktop / f"{SHORTCUT_NAME}.command"
    else:
        target = desktop / f"{SHORTCUT_NAME}.sh"
    content = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f'"{sys.executable}" -m src.web --open\n'
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
        script = write_launcher_script()
        desktop.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            return _create_windows_shortcut(script, desktop), ""
        return _create_posix_shortcut(script, desktop), ""
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
