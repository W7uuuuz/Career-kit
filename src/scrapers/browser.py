"""Playwright 浏览器启动策略。

优先使用用户系统默认浏览器（Chrome / Edge），与 BOSS 登录保持同一产品理念；
未检测到 Chrome / Edge 时回退 Playwright 内置 Chromium，保证无桌面浏览器的
Linux / CI 环境仍可运行。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

_CHROME_EXES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
_EDGE_EXES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def _path_exists(path: str) -> bool:
    return Path(path).exists()


def _windows_default_channel() -> str | None:
    """返回 Windows 默认浏览器的 Playwright channel。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return None
    if "ChromeHTML" in prog_id:
        return "chrome"
    if "MSEdgeHTM" in prog_id:
        return "msedge"
    return None


def _installed_channel() -> str | None:
    """按已安装情况返回 Chrome / Edge channel。"""
    for path in _CHROME_EXES:
        if _path_exists(path) or shutil.which("chrome"):
            return "chrome"
    for path in _EDGE_EXES:
        if _path_exists(path) or shutil.which("msedge"):
            return "msedge"
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        return "chrome"
    if shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable"):
        return "msedge"
    return None


def detect_default_browser_channel() -> str | None:
    """返回 "chrome" / "msedge"；未检测到返回 None。"""
    return _windows_default_channel() or _installed_channel()


def launch_browser(playwright: Any, *, headless: bool = True) -> Any:
    """启动浏览器，优先系统默认浏览器，失败时回退内置 Chromium。"""
    channel = detect_default_browser_channel()
    fallback_error: Exception | None = None
    if channel:
        try:
            return playwright.chromium.launch(channel=channel, headless=headless)
        except Exception as exc:
            fallback_error = exc
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as exc:
        if fallback_error is not None:
            raise RuntimeError(
                f"默认浏览器（{channel}）启动失败：{fallback_error}；"
                f"内置 Chromium 启动失败：{exc}"
            ) from exc
        raise
