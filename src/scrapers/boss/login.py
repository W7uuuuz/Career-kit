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
"""

from __future__ import annotations

import contextlib
import sys
import time

from . import cdp
from .auth import describe_ttl, save_login_marker

PROFILE_DIR = cdp.CDP_DATA_DIR
POLL_INTERVAL_SEC = 2.0
POLL_TIMEOUT_SEC = 300.0
LOGIN_PROBE_MAX_INTERVAL = 15
LOGIN_PROBE_MAX_TRANSIENT_ERRORS = 2


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
    try:
        cdp.ensure_cdp_browser(cdp_port)
        session = cdp.CDPSession(cdp_port)
    except cdp.BossCDPError as exc:
        print(f"[!] {exc}")
        print("[!] 恢复建议：安装 Chrome 或 Edge 后重试；若端口被占用，"
              "可设置环境变量 CAREER_KIT_BOSS_CDP_PORT 换端口。")
        return cdp.LoginProbeResult(cdp.LoginProbeStatus.RESPONSE_ERROR, message=str(exc))

    login_target_id: str | None = None
    result = cdp.LoginProbeResult(
        cdp.LoginProbeStatus.RESPONSE_ERROR, message="登录未开始"
    )
    try:
        login_target_id, login_sid = cdp.create_page_session(session, background=False)
        session.send("Page.navigate", {"url": cdp.LOGIN_URL}, login_sid)
        print("[login] 即将弹出专用浏览器，请忽略默认新标签页并直接扫码；"
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
        # 成功后关闭登录标签页；失败时保留登录页与浏览器，方便继续扫码。
        if result.status is cdp.LoginProbeStatus.AVAILABLE and login_target_id is not None:
            with contextlib.suppress(Exception):
                session.send("Target.closeTarget", {"targetId": login_target_id})
        with contextlib.suppress(Exception):
            session.close()

    if result.status is cdp.LoginProbeStatus.AVAILABLE:
        save_login_marker()
        print(
            f"[login] OK 登录成功，已写入登录标记（{describe_ttl()}内有效）。"
            "浏览器窗口保持打开，后续抓取自动复用；"
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
