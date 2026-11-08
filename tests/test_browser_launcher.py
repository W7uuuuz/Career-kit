"""Playwright 浏览器启动策略：默认浏览器优先、Chromium 兜底。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scrapers import browser  # noqa: E402


class _FakeChromium:
    def __init__(self, calls: list[dict], fail_channel: bool = False) -> None:
        self.calls = calls
        self.fail_channel = fail_channel

    def launch(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_channel and "channel" in kwargs:
            raise RuntimeError("channel launch failed")
        return "browser"


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


def test_launch_prefers_detected_default_browser(monkeypatch):
    monkeypatch.setattr(browser, "detect_default_browser_channel", lambda: "msedge")
    calls: list[dict] = []
    playwright = _FakePlaywright(_FakeChromium(calls))

    assert browser.launch_browser(playwright, headless=True) == "browser"
    assert calls == [{"channel": "msedge", "headless": True}]


def test_launch_uses_bundled_chromium_without_detected_browser(monkeypatch):
    monkeypatch.setattr(browser, "detect_default_browser_channel", lambda: None)
    calls: list[dict] = []
    playwright = _FakePlaywright(_FakeChromium(calls))

    assert browser.launch_browser(playwright, headless=True) == "browser"
    assert calls == [{"headless": True}]


def test_launch_falls_back_when_default_browser_fails(monkeypatch):
    monkeypatch.setattr(browser, "detect_default_browser_channel", lambda: "chrome")
    calls: list[dict] = []
    playwright = _FakePlaywright(_FakeChromium(calls, fail_channel=True))

    assert browser.launch_browser(playwright, headless=True) == "browser"
    assert calls == [{"channel": "chrome", "headless": True}, {"headless": True}]
