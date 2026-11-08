"""BOSS 直聘登录——CDP 专用浏览器扫码。

流程：
    python -m src.scrapers.boss.login
      → 启动 Career Kit 专用 Chrome/Edge（profile: ~/.career-kit/cache/boss/cdp-profile）
      → 打开 BOSS 登录页，等待扫码
      → 旁听搜索接口确认能拿到明文薪资后写入登录标记
      → 关闭专用浏览器并退出

为什么用 CDP：
    复用真实浏览器的登录态与指纹，页面自己发出搜索请求，不注入 XHR，
    不伪造登录态。未登录/风控时明确失败，不保存注定失效的状态。
"""

from __future__ import annotations

import contextlib
import sys
import time

from . import cdp
from .auth import save_login_marker

PROFILE_DIR = cdp.CDP_DATA_DIR
POLL_INTERVAL_SEC = 2.0
POLL_TIMEOUT_SEC = 300.0
LOGIN_PROBE_MAX_INTERVAL = 15
LOGIN_PROBE_MAX_TRANSIENT_ERRORS = 2


def _wait_for_login(
    session: cdp.CDPSession,
    sid: str,
    timeout: float = POLL_TIMEOUT_SEC,
    interval: float = POLL_INTERVAL_SEC,
) -> cdp.LoginProbeResult:
    """轮询登录探测，直到拿到明文薪资、命中风控或超时。"""
    deadline = time.time() + timeout
    attempt = 0
    transient_errors = 0
    result = cdp.LoginProbeResult(
        cdp.LoginProbeStatus.UNAUTHENTICATED, message="尚未完成扫码登录"
    )
    while time.time() <= deadline:
        query, city_code = cdp.LOGIN_PROBE_TARGETS[
            attempt % len(cdp.LOGIN_PROBE_TARGETS)
        ]
        try:
            result = cdp.probe_login_state(session, sid, query=query, city_code=city_code)
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
    return cdp.LoginProbeResult(
        cdp.LoginProbeStatus.RESPONSE_ERROR, message="等待登录超时"
    )


def login(cdp_port: int | None = None, timeout: float = POLL_TIMEOUT_SEC) -> bool:
    """启动专用 CDP 浏览器并等待扫码；成功后写标记并关闭浏览器。"""
    try:
        cdp.ensure_cdp_browser(cdp_port)
        session = cdp.CDPSession(cdp_port)
    except cdp.BossCDPError as exc:
        print(f"[!] {exc}")
        print("[!] 恢复建议：安装 Chrome 或 Edge 后重试；若端口被占用，"
              "可设置环境变量 CAREER_KIT_BOSS_CDP_PORT 换端口。")
        return False

    target_id: str | None = None
    logged_in = False
    try:
        target_id, sid = cdp.attach_existing_page(session, background=False)
        session.send("Page.navigate", {"url": cdp.LOGIN_URL}, sid)
        print("[login] 即将弹出专用浏览器，请忽略默认新标签页并直接扫码；"
              f"（最长等待 {int(timeout)} 秒）")
        result = _wait_for_login(session, sid, timeout=timeout)
    finally:
        if target_id is not None:
            with contextlib.suppress(Exception):
                session.send("Target.closeTarget", {"targetId": target_id})
        with contextlib.suppress(Exception):
            session.close()

    if result.status is cdp.LoginProbeStatus.AVAILABLE:
        save_login_marker()
        logged_in = True
        print(
            "[login] OK 登录成功，已写入登录标记（6 小时内有效）。"
            "fetch_company_jobs(company=\"boss\") 现在可用。"
        )
    elif result.status is cdp.LoginProbeStatus.RESTRICTED:
        print(f"[!] {cdp.describe_login_probe_result(result)}")
        print("[!] 恢复建议：先在浏览器中完成验证/滑块，稍后再运行本命令；"
              "若反复失败，先关闭代理/VPN 或换网络。")
    else:
        print(f"[!] {cdp.describe_login_probe_result(result)}")
        print("[!] 恢复建议：确认已扫码并在 BOSS 页面完成登录；"
              "专用浏览器会保持打开，可稍后重新运行本命令继续检测。"
              "若页面异常，关闭代理/VPN 或换网络后重试。")

    if logged_in:
        stopped = cdp.stop_cdp_browser()
        if stopped:
            print(f"[login] 已关闭专用浏览器（{stopped} 个进程）。")
        else:
            print("[login] 未发现需要关闭的专用浏览器进程。")
    return logged_in


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
    sys.exit(0 if login() else 1)


if __name__ == "__main__":
    main()
