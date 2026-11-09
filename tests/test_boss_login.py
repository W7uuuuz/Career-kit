"""BOSS 登录流程回归（CDP 专用浏览器）。

确定性、无网络、不启动真实浏览器：
- ensure_cdp_browser / CDPSession / create_page_session / probe_login_state /
  save_login_marker 全部打桩；
- time 用可推进的假时钟，避免真实等待。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.boss.cdp as cdp
import src.scrapers.boss.login as login
import src.scrapers.boss.scraper as scraper
import src.tools.boss_tools as boss_tools


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
    monkeypatch.setattr(
        login.cdp, "create_page_session", lambda *a, **k: ("probe-target", "probe-sid")
    )
    probes = iter([
        _result(cdp.LoginProbeStatus.UNAUTHENTICATED),
        _result(cdp.LoginProbeStatus.AVAILABLE),
    ])
    probe_sids: list[str] = []

    def _probe(_session, sid, **kwargs):
        probe_sids.append(sid)
        return next(probes)

    monkeypatch.setattr(login.cdp, "probe_login_state", _probe)

    session = FakeSession()
    result = login._wait_for_login(session, timeout=60)

    assert result.status is cdp.LoginProbeStatus.AVAILABLE
    assert clock.sleeps, "两次探测之间应有退避等待"
    assert set(probe_sids) == {"probe-sid"}
    assert ("Target.closeTarget", {"targetId": "probe-target"}, None) in session.sent


def test_wait_for_login_stops_immediately_on_restricted(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(login, "time", clock)
    monkeypatch.setattr(
        login.cdp, "create_page_session", lambda *a, **k: ("probe-target", "probe-sid")
    )
    monkeypatch.setattr(
        login.cdp,
        "probe_login_state",
        lambda *a, **k: _result(cdp.LoginProbeStatus.RESTRICTED, code=37, message="安全校验"),
    )

    result = login._wait_for_login(FakeSession(), timeout=60)

    assert result.status is cdp.LoginProbeStatus.RESTRICTED
    assert clock.sleeps == []


def _patch_login_flow(monkeypatch, probe_result):
    session = FakeSession()
    created: list[bool] = []
    probe_sids: list[str] = []
    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", lambda *a, **k: None)
    monkeypatch.setattr(login.cdp, "CDPSession", lambda *a, **k: session)

    def _create(_session, background=True):
        created.append(background)
        if background:
            return "probe-target", "probe-sid"
        return "login-target", "login-sid"

    def _probe(_session, sid, **kwargs):
        probe_sids.append(sid)
        return probe_result

    monkeypatch.setattr(login.cdp, "create_page_session", _create)
    monkeypatch.setattr(login.cdp, "probe_login_state", _probe)
    monkeypatch.setattr(login.cdp, "stop_cdp_browser", lambda: 1)
    return session, created, probe_sids


def test_login_opens_visible_page_and_probes_in_separate_target(monkeypatch):
    """登录页 target 不得传给探测；登录页只导航一次。"""
    monkeypatch.setattr(login, "save_login_marker", lambda *a, **k: None)
    session, created, probe_sids = _patch_login_flow(
        monkeypatch, _result(cdp.LoginProbeStatus.AVAILABLE)
    )

    result = login.login(timeout=5)

    assert result.status is cdp.LoginProbeStatus.AVAILABLE
    assert created[0] is False, "登录页必须是可见标签页"
    assert True in created, "探测必须使用独立后台标签页"
    navigations = [item for item in session.sent if item[0] == "Page.navigate"]
    assert len(navigations) == 1, "登录页只导航一次"
    assert navigations[0][2] == "login-sid"
    assert set(probe_sids) == {"probe-sid"}, "探测必须使用后台页，绝不传登录页 sid"
    assert "login-sid" not in probe_sids


def test_login_success_saves_marker_keeps_browser(monkeypatch):
    state = {"marker": 0, "stopped": 0}
    monkeypatch.setattr(
        login, "save_login_marker", lambda *a, **k: state.__setitem__("marker", 1)
    )
    session, _created, _probe_sids = _patch_login_flow(
        monkeypatch, _result(cdp.LoginProbeStatus.AVAILABLE)
    )
    monkeypatch.setattr(
        login.cdp, "stop_cdp_browser", lambda: state.__setitem__("stopped", 1) or 1
    )

    result = login.login(timeout=5)

    assert result.status is cdp.LoginProbeStatus.AVAILABLE
    assert state["marker"] == 1
    assert state["stopped"] == 0, "登录成功后窗口必须常驻，不得关闭专用浏览器"
    assert session.closed is True
    closed_targets = [
        item[1]["targetId"] for item in session.sent if item[0] == "Target.closeTarget"
    ]
    assert "login-target" in closed_targets, "成功后只关闭登录标签页"


def test_login_failure_keeps_login_page_and_browser(monkeypatch):
    state = {"marker": 0, "stopped": 0}
    monkeypatch.setattr(
        login, "save_login_marker", lambda *a, **k: state.__setitem__("marker", 1)
    )
    session, _created, _probe_sids = _patch_login_flow(
        monkeypatch,
        _result(cdp.LoginProbeStatus.RESTRICTED, code=37, message="安全校验"),
    )
    monkeypatch.setattr(
        login.cdp, "stop_cdp_browser", lambda: state.__setitem__("stopped", 1) or 1
    )

    result = login.login(timeout=5)

    assert result.status is cdp.LoginProbeStatus.RESTRICTED
    assert state["marker"] == 0
    assert state["stopped"] == 0, "失败时保留专用浏览器"
    closed_targets = [
        item[1]["targetId"] for item in session.sent if item[0] == "Target.closeTarget"
    ]
    assert "login-target" not in closed_targets, "失败时保留登录页供继续扫码"


def test_login_reports_missing_browser(monkeypatch):
    def _raise(*args, **kwargs):
        raise cdp.BossCDPError("未检测到 Chrome 或 Edge")

    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", _raise)
    monkeypatch.setattr(
        login.cdp,
        "CDPSession",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应创建 CDP 连接")),
    )

    result = login.login(timeout=1)

    assert result.status is cdp.LoginProbeStatus.RESPONSE_ERROR


def test_boss_login_status_is_side_effect_free(monkeypatch):
    calls = {"probe": 0}
    monkeypatch.setattr(
        boss_tools.auth,
        "auth_status",
        lambda: {"exists": True, "expired": False, "ttl_seconds": boss_tools.auth.LOGIN_TTL_SECONDS},
    )
    monkeypatch.setattr(boss_tools.cdp, "is_cdp_ready", lambda *a, **k: True)
    monkeypatch.setattr(boss_tools.cdp, "cdp_browser_process_count", lambda: 1)
    monkeypatch.setattr(
        boss_tools.cdp,
        "check_login_state",
        lambda *a, **k: calls.__setitem__("probe", calls["probe"] + 1),
    )

    payload = json.loads(boss_tools.boss_login(action="status"))

    assert payload["logged_in"] is True
    assert payload["browser_running"] is True
    assert payload["ttl_seconds"] == boss_tools.auth.LOGIN_TTL_SECONDS
    assert payload["ttl_text"] == boss_tools.auth.describe_ttl()
    assert "probe" not in payload
    assert calls["probe"] == 0, "status 默认不得做真实探测"


def test_boss_login_success_does_not_stop_and_close_does(monkeypatch):
    stopped = {"count": 0}
    monkeypatch.setattr(
        boss_tools.boss_login_flow,
        "login",
        lambda *a, **k: _result(cdp.LoginProbeStatus.AVAILABLE),
    )
    monkeypatch.setattr(
        boss_tools.cdp, "stop_cdp_browser", lambda: stopped.__setitem__("count", stopped["count"] + 1) or 1
    )

    login_payload = json.loads(boss_tools.boss_login(action="login"))
    assert login_payload["logged_in"] is True
    assert stopped["count"] == 0, "登录成功后不得关闭浏览器"

    close_payload = json.loads(boss_tools.boss_login(action="close"))
    assert stopped["count"] == 1
    assert close_payload["stopped"] == 1


def test_env_anomaly_error_mentions_network_and_relogin():
    message = scraper._env_anomaly_error("您的环境存在异常")

    assert "代理/VPN" in message or "换网络" in message
    assert "重新登录" in message
    assert "boss_login" in message or "-m src.scrapers.boss.login" in message
