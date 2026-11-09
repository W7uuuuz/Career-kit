"""BOSS 直聘登录——CDP 专用浏览器扫码。

流程：
    python -m src.scrapers.boss.login
      → 启动 Career Kit 专用 Chrome/Edge（profile: ~/.career-kit/cache/boss/cdp-profile）
      → 打开一个可见登录标签页，等待扫码
      → 用独立的后台探测标签页旁听搜索接口，确认能拿到明文薪资后写入登录标记
      → 保持专用浏览器窗口常驻；需要关闭时用 boss_login(action="close")

为什么用 CDP：
    复用真实浏览器的登录态与指纹，页面自己发出搜索请求，不注入 XHR，
    不伪造登录态。未登录/风控时明确失败，不保存注定失效的状态。

标签页隔离：
    登录标签页是用户可见界面，探测与抓取一律使用后台标签页；
    登录标签页只导航一次，绝不被探测逻辑复用或改写。
多窗口：
    创建登录页后两轮清扫其它恢复的 page target，只保留唯一的登录窗口并激活；
    成功与失败都不关闭该登录页，浏览器保持常驻。
"""

from __future__ import annotations

import contextlib
import sys
import time
from dataclasses import replace
from urllib.parse import quote

from . import cdp
from .auth import describe_ttl, save_login_marker

PROFILE_DIR = cdp.CDP_DATA_DIR
POLL_INTERVAL_SEC = 2.0
POLL_TIMEOUT_SEC = 300.0
LOGIN_PROBE_MAX_INTERVAL = 15
LOGIN_PROBE_MAX_TRANSIENT_ERRORS = 2
# 清理旧标签页的两轮清扫间隔：覆盖 Chrome 恢复会话时晚到的页面。
TARGET_SWEEP_DELAY = 0.4


def _page_targets(session: cdp.CDPSession) -> list[dict]:
    try:
        targets = session.send("Target.getTargets").get("result", {}).get("targetInfos", [])
    except Exception:  # noqa: BLE001 - 枚举失败时本轮不清扫
        return []
    return [
        info
        for info in targets
        if isinstance(info, dict) and info.get("type") == "page"
    ]


def _close_other_pages(
    session: cdp.CDPSession,
    keep_target_id: str,
    sweeps: int = 2,
    delay: float | None = None,
) -> list[str]:
    """关闭除登录页外的其它 page target，两轮清扫以覆盖晚到的恢复标签页。

    只处理 ``type=page``；跳过 devtools:// 与登录页自身；单个 target 失败不中断。
    """
    pause = TARGET_SWEEP_DELAY if delay is None else delay
    closed: list[str] = []
    for index in range(max(1, sweeps)):
        for info in _page_targets(session):
            target_id = str(info.get("targetId") or "")
            if not target_id or target_id == keep_target_id:
                continue
            if str(info.get("url") or "").startswith("devtools://"):
                continue
            try:
                session.send("Target.closeTarget", {"targetId": target_id})
                closed.append(target_id)
            except Exception:  # noqa: BLE001 - 单个旧标签关闭失败不阻断登录
                continue
        if index < max(1, sweeps) - 1 and pause > 0:
            time.sleep(pause)
    return closed


def _focus_login_page(
    session: cdp.CDPSession, target_id: str, sid: str
) -> None:
    """把登录页激活到前台，保证用户看到并聚焦唯一的扫码窗口。"""
    with contextlib.suppress(Exception):
        session.send("Target.activateTarget", {"targetId": target_id})
    with contextlib.suppress(Exception):
        session.send("Page.bringToFront", {}, sid)


LOGIN_SUCCESS_HTML = (
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<title>BOSS 登录成功</title></head>"
    "<body style=\"font-family:system-ui,sans-serif;max-width:560px;"
    "margin:12vh auto;padding:0 24px;line-height:1.7;color:#1f2329;\">"
    "<h1 style=\"font-size:22px;\">BOSS 登录成功</h1>"
    "<p>此窗口用于 Career Kit 后续抓取，可保持打开；"
    "不要关闭专用浏览器，抓取会自动复用。</p>"
    "<p>需要关闭浏览器时，对 Agent 说「关闭 BOSS 浏览器」"
    "或调用 boss_login(action=\"close\")。</p>"
    "</body></html>"
)


def _login_success_url() -> str:
    """登录成功提示页：纯内联 data URL，无外部资源。"""
    return "data:text/html;charset=utf-8," + quote(LOGIN_SUCCESS_HTML)


def _wait_for_login(
    session: cdp.CDPSession,
    timeout: float = POLL_TIMEOUT_SEC,
    interval: float = POLL_INTERVAL_SEC,
) -> cdp.LoginProbeResult:
    """用独立后台探测页轮询登录态，直到拿到明文薪资、命中风控或超时。"""
    probe_target_id, probe_sid = cdp.create_page_session(session, background=True)
    deadline = time.time() + timeout
    attempt = 0
    transient_errors = 0
    result = cdp.LoginProbeResult(
        cdp.LoginProbeStatus.UNAUTHENTICATED, message="尚未完成扫码登录"
    )
    try:
        while time.time() <= deadline:
            query, city_code = cdp.LOGIN_PROBE_TARGETS[
                attempt % len(cdp.LOGIN_PROBE_TARGETS)
            ]
            try:
                result = cdp.probe_login_state(
                    session, probe_sid, query=query, city_code=city_code
                )
            except (TimeoutError, OSError) as exc:
                result = cdp.LoginProbeResult(
                    cdp.LoginProbeStatus.RESPONSE_ERROR,
                    message=f"CDP 传输层异常: {exc}",
                    retryable=True,
                )
            except Exception as exc:  # noqa: BLE001 - 单次探测失败不中断等待
                result = cdp.LoginProbeResult(
                    cdp.LoginProbeStatus.RESPONSE_ERROR,
                    message=f"{type(exc).__name__}: {exc}",
                    retryable=True,
                )

            if result.status is cdp.LoginProbeStatus.AVAILABLE:
                return result
            if result.status is cdp.LoginProbeStatus.RESTRICTED:
                return result
            if (
                result.status is cdp.LoginProbeStatus.RESPONSE_ERROR
                and not result.retryable
            ):
                return result
            if result.status is cdp.LoginProbeStatus.RESPONSE_ERROR:
                transient_errors += 1
                if transient_errors > LOGIN_PROBE_MAX_TRANSIENT_ERRORS:
                    return result
            else:
                transient_errors = 0

            remaining = deadline - time.time()
            if remaining <= 0:
                break
            delay = min(interval * (2 ** attempt), LOGIN_PROBE_MAX_INTERVAL, remaining)
            time.sleep(delay)
            attempt += 1
    finally:
        with contextlib.suppress(Exception):
            session.send("Target.closeTarget", {"targetId": probe_target_id})
    return cdp.LoginProbeResult(
        cdp.LoginProbeStatus.RESPONSE_ERROR, message="等待登录超时"
    )


def login(
    cdp_port: int | None = None, timeout: float = POLL_TIMEOUT_SEC
) -> cdp.LoginProbeResult:
    """打开可见登录页等待扫码；成功后写标记并保持浏览器常驻。"""
    was_ready = cdp.is_cdp_ready(cdp_port)
    try:
        cdp.ensure_cdp_browser(cdp_port)
        session = cdp.CDPSession(cdp_port)
    except cdp.BossCDPError as exc:
        print(f"[!] {exc}")
        print("[!] 恢复建议：安装 Chrome 或 Edge 后重试；若端口被占用，"
              "可设置环境变量 CAREER_KIT_BOSS_CDP_PORT 换端口。")
        return cdp.LoginProbeResult(
            cdp.LoginProbeStatus.RESPONSE_ERROR,
            message=str(exc),
            browser_launched=False,
            browser_open=cdp.is_cdp_ready(cdp_port),
        )
    launched = not was_ready

    login_target_id: str | None = None
    login_sid: str | None = None
    result = cdp.LoginProbeResult(
        cdp.LoginProbeStatus.RESPONSE_ERROR, message="登录未开始"
    )
    try:
        login_target_id, login_sid = cdp.create_page_session(session, background=False)
        session.send("Page.navigate", {"url": cdp.LOGIN_URL}, login_sid)
        # Chrome 恢复会话时可能带出旧标签页：清扫两轮只保留登录页，再激活它。
        _close_other_pages(session, login_target_id)
        _focus_login_page(session, login_target_id, login_sid)
        print("[login] 即将打开专用登录窗口，请扫码；"
              f"（最长等待 {int(timeout)} 秒）")
        result = _wait_for_login(session, timeout=timeout)
    except (TimeoutError, OSError) as exc:
        result = cdp.LoginProbeResult(
            cdp.LoginProbeStatus.RESPONSE_ERROR,
            message=f"CDP 传输层异常: {exc}",
            retryable=True,
        )
    except Exception as exc:  # noqa: BLE001 - 登录流程失败需要返回可恢复原因
        result = cdp.LoginProbeResult(
            cdp.LoginProbeStatus.RESPONSE_ERROR,
            message=f"{type(exc).__name__}: {exc}",
            retryable=True,
        )
    finally:
        # 成功后把保留的登录页切到明确的成功提示页，避免停留在扫码页误导用户。
        if result.status is cdp.LoginProbeStatus.AVAILABLE and login_sid is not None:
            with contextlib.suppress(Exception):
                session.send("Page.navigate", {"url": _login_success_url()}, login_sid)
        # 成功与失败都保留登录页与浏览器：浏览器常驻，失败时用户可继续扫码。
        with contextlib.suppress(Exception):
            session.close()

    result = replace(
        result,
        browser_launched=launched,
        browser_open=cdp.is_cdp_ready(cdp_port),
    )

    if result.status is cdp.LoginProbeStatus.AVAILABLE:
        save_login_marker()
        print(
            f"[login] OK 登录成功，已写入登录标记（{describe_ttl()}内有效）。"
            "窗口已切到登录成功页；浏览器窗口保持打开，后续抓取自动复用；"
            "需要关闭时用 boss_login(action=\"close\")。"
        )
    elif result.status is cdp.LoginProbeStatus.RESTRICTED:
        print(f"[!] {cdp.describe_login_probe_result(result)}")
        print("[!] 恢复建议：先在浏览器中完成验证/滑块，稍后再调用 "
              "boss_login(action=\"login\")；若反复失败，先关闭代理/VPN 或换网络。")
        print("[!] 登录页与浏览器保持打开，可继续扫码。")
    else:
        print(f"[!] {cdp.describe_login_probe_result(result)}")
        print("[!] 恢复建议：确认已扫码并在 BOSS 页面完成登录；"
              "登录页与浏览器保持打开，可稍后重新调用 boss_login(action=\"login\") 继续检测。")
        print("[!] 若页面异常，关闭代理/VPN 或换网络后重试；"
              "不再需要时用 boss_login(action=\"close\") 关闭浏览器。")
    return result


def _configure_output_encoding() -> None:
    """统一 UTF-8 输出，避免中文在 GBK/管道捕获时乱码。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - 控制台编码设置失败不阻断
            pass
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_output_encoding()
    if len(sys.argv) > 1:
        print(__doc__.strip()[:400])
        print("\n[!] 本工具不接受参数。直接运行 python -m src.scrapers.boss.login 即可。")
        sys.exit(2)
    result = login()
    sys.exit(0 if result.status is cdp.LoginProbeStatus.AVAILABLE else 1)


if __name__ == "__main__":
    main()
