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
    def __init__(self, targets: list[dict] | None = None) -> None:
        self.sent: list[tuple] = []
        self.closed = False
        self.targets = list(targets or [])

    def send(self, method, params=None, sid=None, timeout=30):
        self.sent.append((method, params, sid))
        if method == "Target.getTargets":
            return {"result": {"targetInfos": [dict(t) for t in self.targets]}}
        if method == "Target.closeTarget":
            target_id = (params or {}).get("targetId")
            self.targets = [t for t in self.targets if t.get("targetId") != target_id]
            return {}
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


def _patch_login_flow(monkeypatch, probe_result, restored_targets=None):
    session = FakeSession(targets=list(restored_targets or []))
    created: list[bool] = []
    probe_sids: list[str] = []
    monkeypatch.setattr(login, "TARGET_SWEEP_DELAY", 0)
    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", lambda *a, **k: None)
    monkeypatch.setattr(login.cdp, "CDPSession", lambda *a, **k: session)

    def _create(_session, background=True):
        created.append(background)
        if background:
            session.targets.append(
                {"targetId": "probe-target", "type": "page", "url": "about:blank"}
            )
            return "probe-target", "probe-sid"
        session.targets.append(
            {"targetId": "login-target", "type": "page", "url": "about:blank"}
        )
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
    login_navigations = [
        item
        for item in session.sent
        if item[0] == "Page.navigate" and item[1].get("url") == cdp.LOGIN_URL
    ]
    assert len(login_navigations) == 1, "登录页只导航一次到 LOGIN_URL"
    assert login_navigations[0][2] == "login-sid"
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
    assert "login-target" not in closed_targets, "成功后必须保留登录页，浏览器才能常驻"
    assert any(t.get("targetId") == "login-target" for t in session.targets)

    success_navs = [
        item
        for item in session.sent
        if item[0] == "Page.navigate"
        and str(item[1].get("url") or "").startswith("data:text/html;charset=utf-8,")
    ]
    assert len(success_navs) == 1, "成功后必须切到登录成功提示页"
    assert success_navs[0][2] == "login-sid"
    from urllib.parse import unquote

    decoded = unquote(success_navs[0][1]["url"])
    assert "BOSS 登录成功" in decoded
    assert "boss_login(action=\"close\")" in decoded
    assert "data:text/html;charset=utf-8," in success_navs[0][1]["url"]


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
    assert any(t.get("targetId") == "login-target" for t in session.targets)
    success_navs = [
        item
        for item in session.sent
        if item[0] == "Page.navigate"
        and str(item[1].get("url") or "").startswith("data:text/html")
    ]
    assert success_navs == [], "失败时不得导航到成功页"


def test_login_closes_other_restored_pages(monkeypatch):
    """Chrome 恢复会话带出的旧标签页必须被清理，只留登录页；devtools 除外。"""
    monkeypatch.setattr(login, "save_login_marker", lambda *a, **k: None)
    restored = [
        {"targetId": "old-1", "type": "page", "url": "https://www.zhipin.com/"},
        {"targetId": "old-2", "type": "page", "url": "about:blank"},
        {"targetId": "devtools", "type": "page", "url": "devtools://inspect"},
        {"targetId": "worker", "type": "service_worker", "url": "https://x"},
    ]
    session, _created, _probe_sids = _patch_login_flow(
        monkeypatch,
        _result(cdp.LoginProbeStatus.RESTRICTED, code=37, message="安全校验"),
        restored_targets=restored,
    )

    login.login(timeout=5)

    closed = [
        item[1]["targetId"] for item in session.sent if item[0] == "Target.closeTarget"
    ]
    assert "old-1" in closed and "old-2" in closed
    assert "devtools" not in closed, "不得关闭 devtools target"
    assert "worker" not in closed, "只清理 page target"
    assert "login-target" not in closed
    remaining = {t.get("targetId") for t in session.targets}
    assert "login-target" in remaining
    assert "old-1" not in remaining and "old-2" not in remaining


def test_login_focuses_the_only_login_page(monkeypatch):
    monkeypatch.setattr(login, "save_login_marker", lambda *a, **k: None)
    session, _created, _probe_sids = _patch_login_flow(
        monkeypatch, _result(cdp.LoginProbeStatus.RESTRICTED, code=37, message="安全校验")
    )

    login.login(timeout=5)

    assert (
        "Target.activateTarget",
        {"targetId": "login-target"},
        None,
    ) in session.sent
    assert ("Page.bringToFront", {}, "login-sid") in session.sent


def test_login_reports_missing_browser(monkeypatch):
    def _raise(*args, **kwargs):
        raise cdp.BossCDPError("未检测到 Chrome 或 Edge")

    monkeypatch.setattr(login.cdp, "ensure_cdp_browser", _raise)
    monkeypatch.setattr(login.cdp, "is_cdp_ready", lambda *a, **k: False)
    monkeypatch.setattr(
        login.cdp,
        "CDPSession",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应创建 CDP 连接")),
    )

    result = login.login(timeout=1)

    assert result.status is cdp.LoginProbeStatus.RESPONSE_ERROR
    assert result.browser_open is False
    assert result.browser_launched is False


def test_login_reports_browser_open_state(monkeypatch):
    monkeypatch.setattr(login, "save_login_marker", lambda *a, **k: None)
    monkeypatch.setattr(login.cdp, "is_cdp_ready", lambda *a, **k: True)
    _patch_login_flow(monkeypatch, _result(cdp.LoginProbeStatus.AVAILABLE))

    result = login.login(timeout=5)

    assert result.browser_open is True, "浏览器已在运行且登录后仍可用时必须如实上报"
    assert result.browser_launched is False, "端口已就绪时不应声称新拉起浏览器"


def test_boss_login_status_is_side_effect_free(monkeypatch):
    calls = {"probe": 0}
    monkeypatch.setattr(
        boss_tools.auth,
        "auth_status",
        lambda: {
            "exists": True,
            "expired": False,
            "valid": True,
            "reason": "ok",
            "ttl_seconds": boss_tools.auth.LOGIN_TTL_SECONDS,
        },
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


def test_status_logged_in_false_when_marker_valid_but_cdp_unavailable(tmp_path, monkeypatch):
    """标记有效但 CDP 不可用时，status.logged_in 必须与 has_valid_cookies 同源为 false。"""
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(boss_tools.auth, "AUTH_STATE_PATH", state_path)
    boss_tools.auth.save_login_marker()
    monkeypatch.setattr(boss_tools.auth, "cdp_backend_available", lambda *a, **k: False)
    monkeypatch.setattr(boss_tools.cdp, "is_cdp_ready", lambda *a, **k: False)
    monkeypatch.setattr(boss_tools.cdp, "cdp_browser_process_count", lambda: 0)

    payload = json.loads(boss_tools.boss_login(action="status"))

    assert payload["logged_in"] is False
    assert payload["auth"]["reason"] == "cdp_unavailable"
    assert state_path.exists(), "登录标记仍在，只是当前 CDP 不可用"


def test_login_payload_reports_browser_kept_open_only_when_open(monkeypatch):
    monkeypatch.setattr(
        boss_tools.boss_login_flow,
        "login",
        lambda *a, **k: cdp.LoginProbeResult(
            cdp.LoginProbeStatus.AVAILABLE,
            browser_launched=True,
            browser_open=True,
        ),
    )
    payload = json.loads(boss_tools.boss_login(action="login"))
    assert payload["browser_kept_open"] is True
    assert "保持常驻" in payload["next_step"]

    monkeypatch.setattr(
        boss_tools.boss_login_flow,
        "login",
        lambda *a, **k: cdp.LoginProbeResult(
            cdp.LoginProbeStatus.RESPONSE_ERROR,
            message="未检测到 Chrome 或 Edge",
            browser_launched=False,
            browser_open=False,
        ),
    )
    monkeypatch.setattr(boss_tools.cdp, "is_cdp_ready", lambda *a, **k: False)

    failed = json.loads(boss_tools.boss_login(action="login"))
    assert failed["browser_kept_open"] is False
    assert "保持打开" not in failed.get("recovery", "")


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
