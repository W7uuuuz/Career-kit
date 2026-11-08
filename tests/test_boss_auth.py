"""BOSS 登录态（CDP marker）与环境异常销毁回归。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.boss.auth as auth
import src.scrapers.boss.cdp as cdp
import src.scrapers.boss.scraper as scraper


@pytest.fixture()
def auth_path(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(auth, "AUTH_STATE_PATH", path)
    return path


class FakeCache:
    def __init__(self):
        self.get_calls = 0
        self.set_calls = 0

    def get(self, key):
        self.get_calls += 1
        return None

    def set(self, key, value):
        self.set_calls += 1


def test_login_state_has_timestamp_and_is_valid(auth_path):
    auth.save_cookies({"wt2": "token", "bst": "value"})
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    assert state["saved_at_ts"] <= time.time()
    assert state["ttl_seconds"] == auth.LOGIN_TTL_SECONDS
    assert auth.has_valid_cookies() is True
    assert auth.load_cookies()["wt2"] == "token"


def test_login_state_expires_after_ttl(auth_path):
    auth.save_cookies({"wt2": "token"})
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    state["saved_at_ts"] = time.time() - auth.LOGIN_TTL_SECONDS - 1
    auth_path.write_text(json.dumps(state), encoding="utf-8")

    assert auth.has_valid_cookies() is False
    assert not auth_path.exists(), "过期登录态应被销毁"


def test_legacy_state_without_timestamp_is_invalidated(auth_path):
    auth_path.write_text(
        json.dumps({"cookies": [{"name": "wt2", "value": "old"}]}),
        encoding="utf-8",
    )
    assert auth.has_valid_cookies() is False
    assert not auth_path.exists()


def test_cdp_login_marker_requires_cdp_backend(auth_path, monkeypatch):
    auth.save_login_marker()
    assert json.loads(auth_path.read_text(encoding="utf-8"))["mode"] == "cdp"

    monkeypatch.setattr(auth, "cdp_backend_available", lambda *a, **k: True)
    assert auth.has_valid_cookies() is True

    monkeypatch.setattr(auth, "cdp_backend_available", lambda *a, **k: False)
    assert auth.has_valid_cookies() is False
    assert auth_path.exists(), "浏览器暂不可用不应销毁登录标记"


def test_cdp_login_marker_expires(auth_path, monkeypatch):
    auth.save_login_marker()
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    state["saved_at_ts"] = time.time() - auth.LOGIN_TTL_SECONDS - 1
    auth_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(auth, "cdp_backend_available", lambda *a, **k: True)

    assert auth.has_valid_cookies() is False
    assert not auth_path.exists()


def test_search_rejects_cache_when_login_expired(auth_path, monkeypatch):
    auth.save_cookies({"wt2": "token"})
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    state["saved_at_ts"] = time.time() - auth.LOGIN_TTL_SECONDS - 1
    auth_path.write_text(json.dumps(state), encoding="utf-8")

    cache = FakeCache()
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: cache)

    result = scraper.Scraper().search(keyword="后端")

    assert "登录" in result[0]["error"]
    assert cache.get_calls == 0, "登录态过期时不得继续使用旧缓存"


def test_search_login_gate_destroys_marker(auth_path, monkeypatch):
    auth.save_login_marker()
    monkeypatch.setattr(scraper, "has_valid_cookies", lambda: True)
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())

    def _raise(*args, **kwargs):
        raise cdp.LoginGateError("未检测到 BOSS 直聘登录态")

    monkeypatch.setattr(scraper.cdp, "scrape_list", _raise)

    result = scraper.Scraper().search(keyword="后端")

    assert "登录" in result[0]["error"]
    assert not auth_path.exists(), "登录 gate 失败必须销毁旧标记"


def test_detail_cdp_error_returns_error(auth_path, monkeypatch):
    monkeypatch.setattr(scraper, "has_valid_cookies", lambda: True)
    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())
    monkeypatch.setattr(
        scraper.cdp,
        "scrape_detail",
        lambda *a, **k: (_ for _ in ()).throw(cdp.BossCDPError("页面未渲染出 JD")),
    )

    result = scraper.Scraper().get_detail("https://www.zhipin.com/job_detail/x.html")

    assert result["error"] == "页面未渲染出 JD"
