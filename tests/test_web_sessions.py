"""浏览器会话租约与关页停服。"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.web as web  # noqa: E402


def _post(base: str, path: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"X-CK-Token": token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def _start(**kwargs) -> tuple[web.UvicornServer, str, threading.Thread, str]:
    server, token = web.create_server(port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, token, thread, f"http://{host}:{port}"


def test_registry_close_starts_exit_grace(monkeypatch):
    monkeypatch.setattr(web, "SESSION_EXIT_GRACE_SECONDS", 5.0)
    registry = web.SessionRegistry()

    registry.open("tab-1", now=100.0)
    assert registry.active() == 1
    assert registry.should_exit(started_at=0.0, now=200.0) is False

    registry.close("tab-1", now=200.0)
    assert registry.active() == 0
    assert registry.should_exit(started_at=0.0, now=204.9) is False
    assert registry.should_exit(started_at=0.0, now=205.1) is True


def test_registry_prunes_stale_sessions(monkeypatch):
    monkeypatch.setattr(web, "SESSION_TTL_SECONDS", 10.0)
    registry = web.SessionRegistry()

    registry.open("tab-1", now=0.0)
    registry.prune(now=11.0)

    assert registry.active() == 0
    assert registry.ever_opened() is True


def test_session_close_as_last_tab_stops_server(monkeypatch):
    monkeypatch.setattr(web, "SESSION_EXIT_GRACE_SECONDS", 0.2)
    server, token, thread, base = _start(exit_when_idle=True)
    try:
        _post(base, "/api/session/open", token, {"id": "tab-1"})
        request = urllib.request.Request(
            base + f"/api/session/close?id=tab-1&token={token}",
            data=b"",
            method="POST",
        )
        urllib.request.urlopen(request).read()

        thread.join(timeout=5)

        assert not thread.is_alive()
    finally:
        server.server_close()


def test_shutdown_endpoint_stops_server():
    server, token, thread, base = _start()
    try:
        assert _post(base, "/api/shutdown", token)["ok"] is True
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        server.server_close()


def test_session_endpoints_require_token():
    server, _token, thread, base = _start()
    try:
        request = urllib.request.Request(
            base + "/api/session/open",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("session endpoint should require token")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_live_instance_url_prefers_healthy_server(monkeypatch, tmp_path):
    state = tmp_path / "web.json"
    state.write_text(
        json.dumps({"url": "http://127.0.0.1:9/?token=abc"}), encoding="utf-8"
    )
    monkeypatch.setattr(web, "runtime_state_path", lambda: state)

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        web.urllib.request, "urlopen", lambda url, timeout=1.0: _Response()
    )

    assert web._live_instance_url() == "http://127.0.0.1:9/?token=abc"


def test_live_instance_url_ignores_stale_state(monkeypatch, tmp_path):
    state = tmp_path / "web.json"
    state.write_text(
        json.dumps({"url": "http://127.0.0.1:9/?token=abc"}), encoding="utf-8"
    )
    monkeypatch.setattr(web, "runtime_state_path", lambda: state)

    def _down(url, timeout=1.0):
        raise web.urllib.error.URLError("down")

    monkeypatch.setattr(web.urllib.request, "urlopen", _down)

    assert web._live_instance_url() == ""
