"""BOSS 直聘登录态管理（CDP 版本）。

纪律：
- 登录态由 CDP 专用浏览器扫码产生，写入本地登录标记；TTL 到期自动销毁。
- 有效期同时参考 CDP 可用性：端口已就绪，或本机有可启动的 Chrome/Edge
  （抓取时会自动拉起专用 profile，因此「浏览器暂时关闭」不等于登录态失效）。
- API 返回「您的环境存在异常」时主动销毁登录态并让调用方走重新登录。
- 旧版没有时间戳的 state.json 一律视为过期——避免历史登录态静默失效。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from ...paths import CACHE_DIR
from .cdp import cdp_backend_available

AUTH_STATE_PATH = CACHE_DIR / "boss" / "auth" / "state.json"

# 登录态 TTL：6 小时。CDP 复用真实登录态，但产品仍按保守有效期处理，
# 避免「请求能发出去但返回风控/空数据」的静默失效。
# 本常量是 BOSS 登录有效期的唯一事实源；state.json 里的旧 ttl_seconds 不再生效。
LOGIN_TTL_SECONDS = 6 * 60 * 60


def login_ttl_hours() -> int:
    """登录态有效期（小时），由 LOGIN_TTL_SECONDS 派生。"""
    return max(1, LOGIN_TTL_SECONDS // 3600)


def describe_ttl() -> str:
    """用户可见的登录有效期文案，唯一来源为 LOGIN_TTL_SECONDS。"""
    return f"{login_ttl_hours()} 小时"

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


def _serialize_cookies(cookies: dict[str, str]) -> list[dict[str, Any]]:
    return [
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
    ]


def _write_state(state: dict[str, Any]) -> None:
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_cookies() -> dict[str, str]:
    """加载 cookies，返回 {name: value} 字典（CDP 模式通常为空）。"""
    return _state_cookies(_read_state())


def save_cookies(cookies: dict[str, str]) -> None:
    """保存旧版 cookie 登录态（保留兼容）；时间戳是有效性的唯一依据。"""
    now = time.time()
    _write_state(
        {
            "saved_at": datetime.now(UTC).isoformat(),
            "saved_at_ts": now,
            "ttl_seconds": LOGIN_TTL_SECONDS,
            "cookies": _serialize_cookies(cookies),
            "origins": [],
        }
    )


def save_login_marker(cookies: dict[str, str] | None = None) -> None:
    """写入 CDP 扫码登录标记。

    标记只代表「在专用浏览器里完成了扫码且接口返回明文薪资」，
    不能替代真实的接口校验；抓取时仍会由 BOSS 响应做最终判定。
    """
    now = time.time()
    _write_state(
        {
            "mode": "cdp",
            "saved_at": datetime.now(UTC).isoformat(),
            "saved_at_ts": now,
            "ttl_seconds": LOGIN_TTL_SECONDS,
            "cookies": _serialize_cookies(cookies or {}),
            "origins": [],
        }
    )


def invalidate_auth(reason: str = "") -> None:
    """销毁登录态（删除 state.json）。"""
    try:
        AUTH_STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def auth_status() -> dict[str, Any]:
    """返回登录态诊断信息（不触发销毁）。"""
    state = _read_state()
    cookies = _state_cookies(state)
    current = validity()
    return {
        "exists": AUTH_STATE_PATH.exists(),
        "mode": current["mode"],
        "has_wt2": bool(cookies.get("wt2")),
        "saved_at": state.get("saved_at", ""),
        "age_seconds": current["age_seconds"],
        "ttl_seconds": LOGIN_TTL_SECONDS,
        "ttl_text": describe_ttl(),
        "cdp_available": current["cdp_available"],
        "expired": current["expired"],
        "valid": current["valid"],
        "reason": current["reason"],
    }


def validity() -> dict[str, Any]:
    """登录态有效性的唯一判定：登录标记 + TTL + CDP 可用。

    - 缺时间戳 / 超过 TTL → 无效且 expired=True（调用方可据此销毁标记）；
    - CDP 标记但浏览器不可用 → 无效、expired=False（浏览器暂关不等于登录失效）；
    - 旧版 cookie 登录态 → TTL 内且存在 wt2 才算有效。

    只做只读判定，不删除 state.json；销毁由 ``has_valid_cookies`` 负责。
    """
    state = _read_state()
    cookies = _state_cookies(state)
    mode = state.get("mode") or "cookie"
    saved_at = state.get("saved_at_ts")
    age = (
        None
        if not isinstance(saved_at, (int, float))
        else max(0.0, time.time() - float(saved_at))
    )
    cdp_available = cdp_backend_available()
    result: dict[str, Any] = {
        "valid": False,
        "reason": "",
        "expired": False,
        "mode": mode,
        "has_marker": AUTH_STATE_PATH.exists(),
        "saved_at_ts": saved_at if isinstance(saved_at, (int, float)) else None,
        "age_seconds": age,
        "ttl_seconds": LOGIN_TTL_SECONDS,
        "ttl_text": describe_ttl(),
        "cdp_available": cdp_available,
    }
    if not isinstance(saved_at, (int, float)):
        result.update(reason="missing_saved_at", expired=True)
        return result
    if age is not None and age >= LOGIN_TTL_SECONDS:
        result.update(reason="ttl_expired", expired=True)
        return result
    if mode == "cdp":
        if cdp_available:
            result.update(valid=True, reason="ok")
        else:
            result.update(reason="cdp_unavailable")
        return result
    if cookies.get("wt2"):
        result.update(valid=True, reason="ok")
    else:
        result.update(reason="missing_wt2", expired=True)
    return result


def is_env_anomaly_message(message: str) -> bool:
    """判断 BOSS 返回是否是登录态不可用的环境异常。"""
    text = str(message or "")
    return any(marker in text for marker in _ENV_ANOMALY_MARKERS)


def has_valid_cookies() -> bool:
    """检查登录标记是否存在且未过期，并确认 CDP 后端可用。

    与 ``boss_tools.status.logged_in`` 共用 ``validity()`` 的同一判定。
    过期或缺时间戳时立即销毁，避免静默使用失效登录态；
    CDP 只是暂时不可用时不销毁标记（浏览器稍后仍可复用同一登录态）。
    """
    current = validity()
    if current["valid"]:
        return True
    if current["reason"] in ("missing_saved_at", "ttl_expired"):
        invalidate_auth(current["reason"])
    return False
