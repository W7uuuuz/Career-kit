"""BOSS 登录流程回归（CDP 专用浏览器）。

确定性、无网络、不启动真实浏览器：
- ensure_cdp_browser / CDPSession / probe_login_state / save_login_marker 全部打桩；
- time 用可推进的假时钟，避免真实等待。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.boss.cdp as cdp
import src.scrapers.boss.login as login
import src.scrapers.boss.scraper as scraper


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeSession:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.closed = False

    def send(self, method, params=None, sid=None, timeout=30):
        self.sent.append((method, params, sid))
        return {}

    def close(self) -> None:
        self.closed = True


def _result(status, **kwargs):
    return cdp.LoginProbeResult(status, **kwargs)


def test_wait_for_login_returns_available_after_probe(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(login, "time", clock)
    probes = iter([
        _result(cdp.LoginProbeStatus.UNAUTHENTICATED),
        _result(cdp.LoginProbeStatus.AVAILABLE),
    ])
    monkeypatch.setattr(login.cdp, "probe_login_state", lambda *a, **k: next(probes))

    result = login._wait_for_login(FakeSession(), "sid", timeout=60)

    assert result.status is cdp.LoginProbeStatus.AVAILABLE
    assert clock.sleeps, "两次探测之间应有退避等待"


def test_wait_for_login_stops_immediately_on_restricted(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(login, "time", clock)
    monkeypatch.setattr(
        login.cdp,
        "probe_login_state",
        lambda *a, **k: _result(cdp.LoginProbeStatus.RESTRICTED, code=37, message="安全校验"),
    )

    result = login._wait_for_login(FakeSession(), "sid", timeout=60)

    assert result.status is cdp.LoginProbeStatus.RESTRICTED
    assert clock.sleeps == []


def test_login_success_saves_marker_and_closes_browser(monkeypatch):
    session = FakeSession()
    state = {"marker": 0, "stopped": 0}

    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", lambda *a, **k: None)
    monkeypatch.setattr(login.cdp, "CDPSession", lambda *a, **k: session)
    monkeypatch.setattr(
        login.cdp, "attach_existing_page", lambda *a, **k: ("target", "sid")
    )
    monkeypatch.setattr(
        login,
        "_wait_for_login",
        lambda *a, **k: _result(cdp.LoginProbeStatus.AVAILABLE),
    )
    monkeypatch.setattr(
        login, "save_login_marker", lambda *a, **k: state.__setitem__("marker", 1)
    )
    monkeypatch.setattr(
        login.cdp, "stop_cdp_browser", lambda: state.__setitem__("stopped", 1) or 1
    )

    assert login.login(timeout=5) is True
    assert state["marker"] == 1
    assert state["stopped"] == 1
    assert session.closed is True


def test_login_failure_keeps_browser_open(monkeypatch):
    session = FakeSession()
    state = {"marker": 0, "stopped": 0}

    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", lambda *a, **k: None)
    monkeypatch.setattr(login.cdp, "CDPSession", lambda *a, **k: session)
    monkeypatch.setattr(
        login.cdp, "attach_existing_page", lambda *a, **k: ("target", "sid")
    )
    monkeypatch.setattr(
        login,
        "_wait_for_login",
        lambda *a, **k: _result(cdp.LoginProbeStatus.UNAUTHENTICATED, message="超时"),
    )
    monkeypatch.setattr(
        login, "save_login_marker", lambda *a, **k: state.__setitem__("marker", 1)
    )
    monkeypatch.setattr(
        login.cdp, "stop_cdp_browser", lambda: state.__setitem__("stopped", 1) or 1
    )

    assert login.login(timeout=5) is False
    assert state["marker"] == 0
    assert state["stopped"] == 0, "失败时保留专用浏览器，方便用户重新检测"
    assert session.closed is True


def test_login_reports_missing_browser(monkeypatch):
    def _raise(*args, **kwargs):
        raise cdp.BossCDPError("未检测到 Chrome 或 Edge")

    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", _raise)
    monkeypatch.setattr(
        login.cdp,
        "CDPSession",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应创建 CDP 连接")),
    )

    assert login.login(timeout=1) is False


def test_env_anomaly_error_mentions_network_and_relogin():
    message = scraper._env_anomaly_error("您的环境存在异常")

    assert "代理/VPN" in message or "换网络" in message
    assert "重新登录" in message
    assert "-m src.scrapers.boss.login" in message
