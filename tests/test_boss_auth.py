"""BOSS 登录态 TTL 与环境异常销毁回归。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.scrapers.boss.auth as auth
import src.scrapers.boss.scraper as scraper


@pytest.fixture()
def auth_path(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr(auth, "AUTH_STATE_PATH", path)
    return path


def test_login_state_has_timestamp_and_is_valid(auth_path):
    auth.save_cookies({"wt2": "token", "bst": "value"})
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    assert state["saved_at_ts"] <= time.time()
    assert state["ttl_seconds"] == auth.LOGIN_TTL_SECONDS
    assert auth.has_valid_cookies() is True
    assert auth.load_cookies()["wt2"] == "token"


def test_login_state_expires_after_two_hours(auth_path):
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


def test_env_anomaly_destroys_login_state(auth_path, monkeypatch):
    auth.save_cookies({"wt2": "token"})
    assert auth_path.exists()

    class FakeResponse:
        def json(self):
            return {"code": 1, "message": "您的环境存在异常"}

    monkeypatch.setattr(scraper.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(scraper, "get_stoken", lambda: None)

    result = scraper.Scraper()._search_api("后端", "100010000", 10)

    assert "环境存在异常" in result[0]["error"]
    assert "登录" in result[0]["error"]
    assert not auth_path.exists(), "环境异常必须销毁登录态"


def test_detail_env_anomaly_destroys_login_state(auth_path, monkeypatch):
    auth.save_cookies({"wt2": "token"})

    class FakeResponse:
        text = "<html>API 错误: 您的环境存在异常</html>"

    monkeypatch.setattr(scraper.httpx, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(scraper, "get_stoken", lambda: None)

    result = scraper.Scraper()._fetch_detail("https://www.zhipin.com/job_detail/x.html")

    assert "环境存在异常" in result["error"]
    assert not auth_path.exists()


def test_search_rejects_cache_when_login_expired(auth_path, monkeypatch):
    auth.save_cookies({"wt2": "token"})
    state = json.loads(auth_path.read_text(encoding="utf-8"))
    state["saved_at_ts"] = time.time() - auth.LOGIN_TTL_SECONDS - 1
    auth_path.write_text(json.dumps(state), encoding="utf-8")

    called = {"cache": False}

    class FakeCache:
        def get(self, key):
            called["cache"] = True
            return [{"title": "cached"}]

    monkeypatch.setattr(scraper.Scraper, "_make_cache", lambda self, namespace: FakeCache())

    result = scraper.Scraper().search(keyword="后端")

    assert "登录" in result[0]["error"]
    assert called["cache"] is False, "登录态过期时不得继续使用旧缓存"
