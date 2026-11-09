"""BOSS 直聘会话工具：登录态、扫码登录与专用浏览器生命周期。

BOSS 是有状态数据源：登录标记、TTL、浏览器生命周期由本工具承担，
不混进无状态的批量抓取。用户只需同意一次抓取，登录与抓取复用同一会话。
"""

from __future__ import annotations

from typing import Any

from ..guidance import BOSS_LOGIN_URL, login_action
from ..mcp_app import mcp
from ..scrapers.boss import auth, cdp, login as boss_login_flow
from .errors import error_response
from .tool_helpers import _json


def _login_command() -> str:
    import sys

    return f'"{sys.executable}" -m src.scrapers.boss.login'


def _status_payload(live: bool) -> dict[str, Any]:
    info = auth.auth_status()
    # validity() 是唯一判定源：标记 + TTL + CDP 可用。
    logged_in = bool(
        info.get("valid", bool(info.get("exists")) and not info.get("expired"))
    )
    payload: dict[str, Any] = {
        "action": "status",
        "logged_in": logged_in,
        "ttl_seconds": auth.LOGIN_TTL_SECONDS,
        "ttl_text": auth.describe_ttl(),
        "auth": info,
        "cdp_ready": cdp.is_cdp_ready(),
        "browser_running": cdp.cdp_browser_process_count() > 0,
        "login_url": BOSS_LOGIN_URL,
    }
    if live:
        # 只有显式 live=true 才做真实探测；探测固定在后台标签页，不碰用户可见页。
        probe = cdp.check_login_state()
        payload["probe"] = {
            "status": probe.status.value,
            "code": probe.code,
            "message": probe.message,
            "retryable": probe.retryable,
        }
        payload["logged_in"] = probe.status is cdp.LoginProbeStatus.AVAILABLE
    payload["next_step"] = (
        "已登录，可直接抓取；抓取会复用常驻浏览器，不需要再次登录。"
        if payload["logged_in"]
        else "用户同意抓取 BOSS 后调用 boss_login(action=\"login\") 扫码，无需再单独询问是否登录。"
    )
    return payload


def _login_payload(timeout: int) -> dict[str, Any]:
    result = boss_login_flow.login(timeout=timeout)
    ok = result.status is cdp.LoginProbeStatus.AVAILABLE
    browser_launched = bool(getattr(result, "browser_launched", False))
    browser_open = bool(getattr(result, "browser_open", False)) or cdp.is_cdp_ready()
    payload: dict[str, Any] = {
        "action": "login",
        "logged_in": ok,
        "status": result.status.value,
        "code": result.code,
        "message": result.message,
        "retryable": result.retryable,
        "ttl_seconds": auth.LOGIN_TTL_SECONDS,
        "ttl_text": auth.describe_ttl(),
        "browser_launched": browser_launched,
        "browser_kept_open": browser_open,
        "login_url": BOSS_LOGIN_URL,
    }
    if ok:
        if browser_open:
            payload["next_step"] = (
                "登录成功，浏览器窗口保持常驻，直接重试原抓取；"
                "不需要再次追问用户是否登录。"
            )
        else:
            payload["next_step"] = (
                "登录成功，但未能确认专用浏览器窗口仍在；直接重试原抓取，"
                "抓取会自动复用同一登录态并在需要时拉起浏览器。"
            )
    else:
        if browser_open:
            payload["recovery"] = (
                "登录页与浏览器保持打开，可继续扫码后重新调用 boss_login(action=\"login\")；"
                "不再需要时调用 boss_login(action=\"close\") 关闭浏览器。"
            )
        else:
            payload["recovery"] = (
                "本次未能拉起或保持专用浏览器窗口：先确认已安装 Chrome/Edge 且端口可用，"
                "再调用 boss_login(action=\"login\") 重试；不需要时用 boss_login(action=\"close\")。"
            )
        payload["login_action"] = login_action(_login_command())
        payload["next_step"] = (
            "把失败原因转述给用户，并说明登录窗口是否仍打开，可继续扫码或修复浏览器后重试。"
        )
    return payload


@mcp.tool()
def boss_login(action: str = "status", live: bool = False, timeout: int = 180) -> str:
    """管理 BOSS 直聘登录会话（status / login / close）。

    何时调用：
    - 用户同意抓取 BOSS 后，先调用 action="status" 判断是否已登录；
    - 未登录时调用 action="login" 打开可见登录页，用户只需扫码；
    - 需要关闭专用浏览器时调用 action="close"。

    Args:
        action: status（只读检查，零副作用）/ login（打开登录页等待扫码）/
            close（关闭专用浏览器）
        live: 仅 action="status" 生效；true 时额外做一次真实搜索探测（后台标签页）
        timeout: action="login" 的最长等待秒数

    Returns:
        JSON 字符串：登录标记、剩余 TTL（唯一来源 LOGIN_TTL_SECONDS）、
        CDP 端口与专用浏览器进程状态，以及下一步建议。
        登录成功不会关闭浏览器；失败时保留登录页与浏览器供继续扫码。
    """
    act = str(action or "status").strip().lower()
    if act == "status":
        return _json(_status_payload(bool(live)))
    if act == "login":
        return _json(_login_payload(max(1, int(timeout or 180))))
    if act == "close":
        stopped = cdp.stop_cdp_browser()
        return _json({
            "action": "close",
            "stopped": stopped,
            "message": (
                f"已关闭专用浏览器（{stopped} 个进程）。"
                if stopped
                else "未发现需要关闭的专用浏览器进程。"
            ),
        })
    return error_response(
        "INVALID_PARAM",
        f"不支持的 action：{action}；只接受 status / login / close。",
        {"allowed": ["status", "login", "close"]},
    )


__all__ = ["boss_login"]
