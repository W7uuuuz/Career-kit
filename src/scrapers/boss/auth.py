"""BOSS 直聘登录态管理。

纪律：
- 登录态只在 2 小时内有效；过期自动销毁，不靠“cookie 还在”猜有效。
- API 返回「您的环境存在异常」时，主动销毁登录态并让调用方走重新登录。
- 旧版没有时间戳的 state.json 一律视为过期——避免历史登录态静默失效。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from ...paths import CACHE_DIR

AUTH_STATE_PATH = CACHE_DIR / "boss" / "auth" / "state.json"

# 登录态 TTL：2 小时。BOSS 的 cookies 实际寿命可能更长，但产品按更保守的
# 有效期处理，避免“请求能发出去但返回风控/空数据”的静默失效。
LOGIN_TTL_SECONDS = 2 * 60 * 60

# API 风控/环境异常标记：命中后登录态不可继续使用。
_ENV_ANOMALY_MARKERS = ("环境存在异常", "环境异常")


def _read_state() -> dict[str, Any]:
    if not AUTH_STATE_PATH.exists():
        return {}
    try:
        state = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def _state_cookies(state: dict[str, Any]) -> dict[str, str]:
    cookies = state.get("cookies", [])
    if not isinstance(cookies, list):
        return {}
    return {
        str(c["name"]): str(c["value"])
        for c in cookies
        if isinstance(c, dict) and c.get("name")
    }


def load_cookies() -> dict[str, str]:
    """加载 cookies，返回 {name: value} 字典。"""
    return _state_cookies(_read_state())


def save_cookies(cookies: dict[str, str]) -> None:
    """保存 cookies 与时间戳；时间戳是登录态有效性的唯一依据。"""
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    state = {
        "saved_at": datetime.now(UTC).isoformat(),
        "saved_at_ts": now,
        "ttl_seconds": LOGIN_TTL_SECONDS,
        "cookies": [
            {
                "name": k,
                "value": v,
                "domain": ".zhipin.com",
                "path": "/",
                "httpOnly": k in ("wt2", "zp_at", "wbg"),
                "secure": k == "bst",
                "sameSite": "Lax",
            }
            for k, v in cookies.items()
        ],
        "origins": [],
    }
    AUTH_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def invalidate_auth(reason: str = "") -> None:
    """销毁登录态（删除 state.json），并让 stoken 缓存一起失效。

    reason 只用于调用方日志/调试；不把原因写回用户 cookie 文件，避免敏感信息。
    """
    try:
        AUTH_STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    try:
        from .stoken import invalidate_stoken

        invalidate_stoken()
    except Exception:
        # stoken 清理失败不应阻断登录态销毁
        pass


def auth_status() -> dict[str, Any]:
    """返回登录态诊断信息（不触发销毁）。"""
    state = _read_state()
    cookies = _state_cookies(state)
    saved_at = state.get("saved_at_ts")
    if not isinstance(saved_at, (int, float)):
        age = None
    else:
        age = max(0.0, time.time() - float(saved_at))
    return {
        "exists": AUTH_STATE_PATH.exists(),
        "has_wt2": bool(cookies.get("wt2")),
        "saved_at": state.get("saved_at", ""),
        "age_seconds": age,
        "ttl_seconds": LOGIN_TTL_SECONDS,
        "expired": bool(
            not cookies.get("wt2")
            or not isinstance(saved_at, (int, float))
            or (age is not None and age >= LOGIN_TTL_SECONDS)
        ),
    }


def is_env_anomaly_message(message: str) -> bool:
    """判断 BOSS 返回是否是登录态不可用的环境异常。"""
    text = str(message or "")
    return any(marker in text for marker in _ENV_ANOMALY_MARKERS)


def has_valid_cookies() -> bool:
    """检查登录态是否存在且未超过 2 小时；过期时立即销毁。"""
    state = _read_state()
    cookies = _state_cookies(state)
    if not cookies.get("wt2"):
        return False

    saved_at = state.get("saved_at_ts")
    # 旧版 state.json 没有时间戳：无法证明未过期，按过期处理。
    if not isinstance(saved_at, (int, float)):
        invalidate_auth("missing_saved_at")
        return False
    if time.time() - float(saved_at) >= LOGIN_TTL_SECONDS:
        invalidate_auth("ttl_expired")
        return False
    return True
