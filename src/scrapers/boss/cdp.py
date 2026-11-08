"""BOSS 直聘 CDP 抓取核心（vendored，按需裁剪）。

来源：https://github.com/eatmoreduck/boss-zhipin-scraper
Copyright (c) 2026 eatmoreduck
MIT License（见同目录 THIRD_PARTY_NOTICES.md）。

保留的核心思路：
- 连接本地已登录的 Chrome/Edge（CDP），旁听页面自身发出的
  ``/wapi/zpgeek/search/joblist.json``，拿明文 ``salaryDesc``；
- 不注入 XHR，不伪造登录态；未登录/风控时返回明确状态；
- 列表抓取只保留真实抓到的岗位与薪资，详情可交互式补抓。

本文件在参考实现基础上做了裁剪与路径改造：
- 专用 profile 固定为 ``~/.career-kit/cache/boss/cdp-profile``；
- CDP 端口默认 9222，可用 ``CAREER_KIT_BOSS_CDP_PORT`` 覆盖；
- 不包含 CLI / CSV / 结果文件 / 分析报告等无关逻辑。
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import ntpath
import os
import platform
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from ...paths import CACHE_DIR

try:  # websocket-client 是运行依赖；导入失败时仍允许测试纯函数
    import websocket
except ImportError:  # pragma: no cover - 依赖缺失时由 CDPSession 明确报错
    websocket = None

log = logging.getLogger("career_kit.boss.cdp")

API_JOB_LIST_PATH = "/wapi/zpgeek/search/joblist.json"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
LOGIN_PROBE_QUERY = "Java"
LOGIN_PROBE_CITY = "101020100"
LOGIN_PROBE_TARGETS = (
    ("Java", "101020100"),
    ("AI Agent", "101010100"),
    ("产品经理", "101280600"),
)
LOGIN_RESTRICTED_CODES = {31, 37}
LOGIN_RESTRICTED_MESSAGE_KEYWORDS = (
    "环境存在异常",
    "访问频繁",
    "操作太频繁",
    "安全校验",
    "滑块",
    "验证",
)
PROBE_CAPTURE_TIMEOUT = 25
DEFAULT_LIST_PAGE_SIZE = 30
MAX_PAGES = 20

CDP_DATA_DIR = CACHE_DIR / "boss" / "cdp-profile"


def _default_port() -> int:
    raw = os.environ.get("CAREER_KIT_BOSS_CDP_PORT", "9222")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 9222


DEFAULT_CDP_PORT = _default_port()


class BossCDPError(RuntimeError):
    """CDP 抓取不可用（浏览器/连接/页面）。"""


class LoginGateError(BossCDPError):
    """首个搜索响应判定登录/风控不可用，抓取需要终止。"""


# ============================================================
# CDP 连接与网络旁听
# ============================================================
class CDPSession:
    """最小 CDP WebSocket 客户端。"""

    def __init__(self, cdp_port: int | None = None) -> None:
        if websocket is None:
            raise BossCDPError(
                "缺少依赖 websocket-client；请执行 pip install websocket-client"
            )
        self.cdp_port = cdp_port or DEFAULT_CDP_PORT
        try:
            resp = httpx.get(
                f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=5
            )
            resp.raise_for_status()
            ws_url = resp.json()["webSocketDebuggerUrl"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise BossCDPError(
                f"无法连接 CDP 端口 {self.cdp_port}（浏览器未启动或端口被占用）: {exc}"
            ) from exc
        self.ws = websocket.create_connection(ws_url, timeout=60)
        self.mid = 0
        self.events: list[dict[str, Any]] = []

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        sid: str | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        self.mid += 1
        msg: dict[str, Any] = {"id": self.mid, "method": method, "params": params or {}}
        if sid:
            msg["sessionId"] = sid
        self.ws.send(json.dumps(msg))

        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise TimeoutError(f"CDP send({method}) 超时 ({timeout}s)")
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException as exc:
                raise TimeoutError(f"CDP WebSocket recv 超时, method={method}") from exc
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if parsed.get("id") == self.mid:
                return parsed
            self.events.append(parsed)

    def drain_events(self, duration: float) -> None:
        deadline = time.time() + duration
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return
                self.ws.settimeout(min(0.5, remaining))
                try:
                    raw = self.ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if "method" in parsed:
                    self.events.append(parsed)
        finally:
            self.ws.settimeout(60)

    def eval_js(self, js: str, sid: str) -> Any:
        result = self.send("Runtime.evaluate", {"expression": js, "returnByValue": True}, sid)
        return result.get("result", {}).get("result", {}).get("value")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.ws.close()


BACKGROUND_VISIBILITY_SCRIPT = (
    "Object.defineProperty(document, 'hidden', {get: () => false});"
    "Object.defineProperty(document, 'visibilityState', {get: () => 'visible'});"
    "Object.defineProperty(document, 'webkitHidden', {get: () => false});"
    "Object.defineProperty(document, 'webkitVisibilityState', {get: () => 'visible'});"
)


def _enable_background_visibility(cdp: CDPSession, session_id: str) -> None:
    try:
        cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True}, session_id)
    except Exception:  # noqa: BLE001 - 焦点仿真失败可降级
        log.debug("setFocusEmulationEnabled 失败，回退 JS 可见性覆盖", exc_info=True)
    cdp.send(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": BACKGROUND_VISIBILITY_SCRIPT},
        session_id,
    )


def create_page_session(
    cdp: CDPSession, background: bool = True
) -> tuple[str, str]:
    """创建一个 about:blank target，默认不抢用户前台焦点。"""
    target = cdp.send("Target.createTarget", {"url": "about:blank", "background": background})
    target_id = target["result"]["targetId"]
    attached = cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    session_id = attached["result"]["sessionId"]
    if background:
        _enable_background_visibility(cdp, session_id)
    return target_id, session_id


def attach_existing_page(
    cdp: CDPSession, background: bool = True
) -> tuple[str, str]:
    """复用浏览器启动时的默认标签页，避免额外弹出一个新标签。

    Chromium 启动时至少有一个页面；与其再 createTarget，不如把默认页导航到
    目标 URL。没有可用页面时才回退创建 about:blank。
    """
    try:
        targets = cdp.send("Target.getTargets").get("result", {}).get("targetInfos", [])
    except Exception:  # noqa: BLE001 - 老版本 CDP 或瞬态异常时回退创建
        targets = []
    for info in targets:
        if not isinstance(info, dict) or info.get("type") != "page":
            continue
        if str(info.get("url") or "").startswith("devtools://"):
            continue
        try:
            attached = cdp.send(
                "Target.attachToTarget",
                {"targetId": info["targetId"], "flatten": True},
            )
            session_id = attached.get("result", {}).get("sessionId")
        except Exception:  # noqa: BLE001 - 单个 target 附着失败时尝试下一个
            continue
        if not session_id:
            continue
        if background:
            _enable_background_visibility(cdp, session_id)
        return str(info["targetId"]), str(session_id)
    return create_page_session(cdp, background)


class NetworkJoblistCapture:
    """监听并捕获页面自身发出的 joblist API 响应（零注入请求）。"""

    def __init__(self, cdp: CDPSession, sid: str) -> None:
        self.cdp = cdp
        self.sid = sid
        self._consumed: set[str] = set()

    def enable(self) -> None:
        self.cdp.send("Network.enable", {}, self.sid)

    @staticmethod
    def _is_joblist_url(url: str) -> bool:
        return API_JOB_LIST_PATH in url

    def _next_completed(self) -> str | None:
        requests: dict[str, bool] = {}
        finished: set[str] = set()
        for event in self.cdp.events:
            method = event.get("method", "")
            params = event.get("params", {})
            if method == "Network.requestWillBeSent":
                if self._is_joblist_url(params.get("request", {}).get("url", "")):
                    requests[params.get("requestId")] = True
            elif method == "Network.loadingFinished":
                finished.add(params.get("requestId"))
        for request_id in requests:
            if request_id in finished and request_id not in self._consumed:
                return request_id
        return None

    def wait_next_response(
        self,
        timeout: float,
        trigger: Any = None,
        poll: float = 0.5,
    ) -> dict[str, Any] | None:
        if trigger is not None:
            trigger()
        deadline = time.time() + timeout
        while time.time() < deadline:
            request_id = self._next_completed()
            if request_id is None:
                self.cdp.drain_events(min(poll, deadline - time.time()))
                continue
            self._consumed.add(request_id)
            body = self._fetch_body(request_id)
            if body is None:
                continue
            try:
                return json.loads(body)
            except (json.JSONDecodeError, ValueError) as exc:
                log.warning("joblist 响应不是有效 JSON: %s", exc)
        return None

    def _fetch_body(self, request_id: str) -> str | None:
        try:
            result = self.cdp.send(
                "Network.getResponseBody", {"requestId": request_id}, self.sid
            )
        except Exception:  # noqa: BLE001 - 单条响应失败跳过
            log.debug("读取响应体失败 request=%s", request_id, exc_info=True)
            return None
        payload = result.get("result", {})
        body = payload.get("body", "")
        if payload.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                return None
        return body


# ============================================================
# 列表字段映射
# ============================================================
def map_list_boss_active_status(job: dict[str, Any]) -> str:
    if not isinstance(job, dict):
        return ""
    desc = str(job.get("activeTimeDesc") or "").strip()
    if desc:
        return desc
    if job.get("bossOnline"):
        return "在线"
    return ""


def resolve_boss_active_status(list_status: str = "", detail_status: str = "") -> str:
    detail = str(detail_status or "").strip()
    if detail:
        return detail
    return str(list_status or "").strip()


def map_api_job(raw: dict[str, Any]) -> dict[str, Any] | None:
    """把 joblist.json 原始条目映射为统一 job 字典（明文薪资）。"""
    if not isinstance(raw, dict):
        return None
    encrypt_job_id = str(raw.get("encryptJobId") or "")
    encrypt_brand_id = str(raw.get("encryptBrandId") or "")
    location = "·".join(
        part
        for part in (
            raw.get("cityName") or "",
            raw.get("areaDistrict") or "",
            raw.get("businessDistrict") or "",
        )
        if part
    )
    return {
        "title": raw.get("jobName") or "",
        "salary": raw.get("salaryDesc") or "",
        "salary_source": "api" if raw.get("salaryDesc") else "api_empty",
        "location": location,
        "tags": " | ".join(
            part
            for part in (raw.get("jobExperience") or "", raw.get("jobDegree") or "")
            if part and part != "不限"
        ),
        "experience": raw.get("jobExperience") or "",
        "degree": raw.get("jobDegree") or "",
        "boss_name": raw.get("brandName") or "",
        "boss_title": raw.get("bossTitle") or "",
        "boss_active_status": map_list_boss_active_status(raw),
        "company_scale": raw.get("brandScaleName") or "",
        "company_stage": raw.get("brandStageName") or "",
        "company_industry": raw.get("brandIndustry") or "",
        "job_labels": " | ".join(raw.get("jobLabels") or []),
        "skills": " | ".join(raw.get("skills") or []),
        "security_id": raw.get("securityId") or "",
        "lid": raw.get("lid") or "",
        "encrypt_job_id": encrypt_job_id,
        "encrypt_boss_id": str(raw.get("encryptBossId") or ""),
        "encrypt_brand_id": encrypt_brand_id,
        "job_link": (
            f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html"
            if encrypt_job_id
            else ""
        ),
        "company_link": (
            f"https://www.zhipin.com/gongsi/{encrypt_brand_id}.html"
            if encrypt_brand_id
            else ""
        ),
        "welfare": " | ".join(raw.get("welfareList") or []),
    }


def map_api_jobs(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    job_list = (data.get("zpData") or {}).get("jobList")
    if not isinstance(job_list, list):
        return []
    return [job for job in (map_api_job(item) for item in job_list) if job]


def build_search_url(keyword: str, city_code: str, page: int) -> str:
    params = {"query": keyword, "city": city_code, "page": page}
    return f"https://www.zhipin.com/web/geek/job?{urlencode(params)}"


def build_detail_url(job: dict[str, Any]) -> str:
    """补上详情页所需的 lid / securityId 查询参数。"""
    link = str(job.get("job_link") or job.get("url") or "")
    if not link:
        return ""
    parsed = urlparse(link)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    existing = {key for key, _ in params}
    for query_key, job_key in (("lid", "lid"), ("securityId", "security_id")):
        value = job.get(job_key) or job.get(query_key) or ""
        if value and query_key not in existing:
            params.append((query_key, value))
            existing.add(query_key)
    return urlunparse(parsed._replace(query=urlencode(params)))


# ============================================================
# 详情页提取
# ============================================================
DETAIL_LOGIN_MARKER = "登录查看完整内容"
DETAIL_DESCRIPTION_MARKER = "职位描述"
DETAIL_COMPETITIVENESS_MARKER = "竞争力分析"
DETAIL_SAFETY_MARKER = "BOSS 安全提示"
MIN_DETAIL_TEXT_LENGTH = 120


class DetailExtractionError(ValueError):
    """页面没有可用 JD。"""


class DetailLoginRequiredError(DetailExtractionError):
    """详情页因未登录被截断。"""


EXTRACT_DETAIL_JS = """
(function(){
    var pageText = document.body ? document.body.innerText : '';
    var tags = [];
    var benefitWords = ['五险','补充医疗','定期体检','带薪年假','年终奖','零食','餐补',
        '节日福利','加班补助','股票期权','员工旅游','交通补助','通讯补贴','团建',
        '生日福利','免费班车','全勤奖','包吃','弹性工作','下午茶','租房补贴',
        '体检','健身','文化','充电假','司龄假','红包','能量补贴','社团','三薪',
        '绩效','底薪','保底','活动基金','学习基金','节日礼品','无障碍'];
    var noiseWords = ['BOSS直聘','boss','BOSS','来自BOSS直聘','金','金币'];
    function isBenefit(t) {
        if (t === '...' || t.length > 15 || t.length < 2) return true;
        for (var i = 0; i < benefitWords.length; i++) {
            if (t.includes(benefitWords[i])) return true;
        }
        for (var i = 0; i < noiseWords.length; i++) {
            if (t === noiseWords[i] || t.includes(noiseWords[i])) return true;
        }
        return false;
    }
    document.querySelectorAll('.job-tags .tag-all span, .job-keyword-list span').forEach(function(s){
        var t = s.innerText.trim();
        if(t && !isBenefit(t)) tags.push(t);
    });
    var jd = '';
    var sections = document.querySelectorAll('.job-detail-section, .job-sec');
    for (var i = 0; i < sections.length; i++) {
        var text = (sections[i].innerText || '').trim();
        if (text.indexOf('职位描述') !== -1 && text.length > jd.length) {
            jd = text;
        }
    }
    return JSON.stringify({
        jd: jd,
        page_text: pageText.substring(0, 12000),
        tags: tags,
        url: location.href
    });
})()
"""


def _normalize_detail_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").splitlines()]
    normalized = "\n".join(lines).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return re.sub(r"[ \t]{2,}", " ", normalized)


def _looks_like_navigation_page(text: str) -> bool:
    return (
        DETAIL_DESCRIPTION_MARKER not in text
        and "无障碍专区" in text
        and "首页" in text
        and "职位" in text
        and "公司" in text
    )


def _is_boss_activity_line(text: str) -> bool:
    return text == "在线" or text.endswith("活跃")


def _recruiter_footer_info(lines: list[str]) -> tuple[int | None, str]:
    stripped = [line.strip() for line in lines]
    end = len(stripped)
    while end and not stripped[end - 1]:
        end -= 1

    def card_info(card_end: int) -> tuple[int | None, str]:
        while card_end and not stripped[card_end - 1]:
            card_end -= 1
        if card_end < 4 or stripped[card_end - 2] != "·":
            return None, ""
        activity_or_name = stripped[card_end - 4]
        if _is_boss_activity_line(activity_or_name):
            start = card_end - 5
            status = activity_or_name
        else:
            start = card_end - 4
            status = ""
        if start < 0:
            return None, ""
        return start, status

    for marker in (DETAIL_COMPETITIVENESS_MARKER, DETAIL_SAFETY_MARKER):
        try:
            marker_index = stripped.index(marker)
        except ValueError:
            continue
        start, status = card_info(marker_index)
        if start is not None:
            return start, status
    return card_info(end)


def extract_detail_fields(
    extracted: Any, min_length: int = MIN_DETAIL_TEXT_LENGTH
) -> dict[str, str]:
    if not isinstance(extracted, dict):
        raise DetailExtractionError("detail extractor returned non-dict")

    raw_jd = str(extracted.get("jd") or "")
    page_text = str(extracted.get("page_text") or "")
    diagnostic = "\n".join((raw_jd, page_text))

    if DETAIL_LOGIN_MARKER in diagnostic:
        raise DetailLoginRequiredError(
            "detail page is truncated at the login wall; refresh the BOSS login session"
        )
    if _looks_like_navigation_page(diagnostic):
        raise DetailExtractionError("detail page rendered navigation chrome without a JD")

    text = raw_jd
    if not text and DETAIL_DESCRIPTION_MARKER in page_text:
        text = page_text
    if DETAIL_DESCRIPTION_MARKER in text:
        text = text.split(DETAIL_DESCRIPTION_MARKER, 1)[1]

    lines = text.replace("\r\n", "\n").splitlines()
    footer_start, boss_active_status = _recruiter_footer_info(lines)
    if footer_start is not None:
        lines = lines[:footer_start]
    else:
        for index, line in enumerate(lines):
            if line.strip() == DETAIL_SAFETY_MARKER:
                lines = lines[:index]
                break

    jd = _normalize_detail_whitespace("\n".join(lines))
    if len(jd) < min_length:
        raise DetailExtractionError(
            f"job description too short after validation: {len(jd)} < {min_length}"
        )
    return {"jd": jd, "boss_active_status": boss_active_status}


def extract_job_description(
    extracted: Any, min_length: int = MIN_DETAIL_TEXT_LENGTH
) -> str:
    return extract_detail_fields(extracted, min_length=min_length)["jd"]


# ============================================================
# 城市解析
# ============================================================
class CityResolutionError(ValueError):
    """无法把用户输入解析为有效城市码。"""


_CITY_MAP_PATH = Path(__file__).with_name("city_codes.json")
_city_map_cache: tuple[dict[str, str], dict[str, str]] | None = None


def load_city_map() -> tuple[dict[str, str], dict[str, str]]:
    """读取本地全量城市码表，返回 (name_to_code, code_to_name)。"""
    global _city_map_cache
    if _city_map_cache is not None:
        return _city_map_cache
    name_to_code: dict[str, str] = {}
    try:
        raw = json.loads(_CITY_MAP_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            name_to_code = {
                str(name): str(code)
                for name, code in raw.items()
                if name and code is not None
            }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.debug("读取本地城市码表失败: %s", exc)
    code_to_name = {code: name for name, code in name_to_code.items()}
    _city_map_cache = name_to_code, code_to_name
    return _city_map_cache


def resolve_city(city_input: str) -> tuple[str, str]:
    """把中文城市名/城市码解析为 (name, code)。"""
    city_input = str(city_input or "").strip()
    if not city_input:
        return "", ""
    name_to_code, code_to_name = load_city_map()
    if city_input in name_to_code:
        return city_input, name_to_code[city_input]
    if city_input in code_to_name:
        return code_to_name[city_input], city_input
    if re.fullmatch(r"\d{9}", city_input):
        return city_input, city_input
    raise CityResolutionError(
        f"无法解析城市「{city_input}」：请在 city_codes.json 中选择受支持的城市名，"
        "或直接传 9 位 city code。"
    )


# ============================================================
# 登录态分类
# ============================================================
class LoginProbeStatus(Enum):
    AVAILABLE = "available"
    UNAUTHENTICATED = "unauthenticated"
    RESTRICTED = "restricted"
    EMPTY = "empty"
    RESPONSE_ERROR = "response_error"


@dataclass(frozen=True)
class LoginProbeResult:
    status: LoginProbeStatus
    code: int | None = None
    message: str = ""
    retryable: bool = False


def classify_login_probe_response(
    data: Any, http_status: int = 200
) -> LoginProbeResult:
    """把 BOSS 搜索响应分类为登录/风控/空/异常，不把失败折叠成 bool。"""
    if http_status == 401:
        return LoginProbeResult(LoginProbeStatus.UNAUTHENTICATED, message="HTTP 401")
    if http_status in (403, 429):
        return LoginProbeResult(LoginProbeStatus.RESTRICTED, message=f"HTTP {http_status}")
    if http_status != 200:
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            message=f"HTTP {http_status}",
            retryable=http_status == 0 or http_status >= 500,
        )
    if not isinstance(data, dict):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR, message="响应不是 JSON 对象", retryable=True
        )

    raw_code = data.get("code")
    try:
        code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        code = None
    message = str(data.get("message") or data.get("msg") or "")

    if code in LOGIN_RESTRICTED_CODES:
        return LoginProbeResult(LoginProbeStatus.RESTRICTED, code=code, message=message)
    if code not in (None, 0):
        if any(keyword in message for keyword in LOGIN_RESTRICTED_MESSAGE_KEYWORDS):
            return LoginProbeResult(LoginProbeStatus.RESTRICTED, code=code, message=message)
        return LoginProbeResult(LoginProbeStatus.RESPONSE_ERROR, code=code, message=message)

    zp_data = data.get("zpData")
    if not isinstance(zp_data, dict):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR, message="响应缺少 zpData", retryable=True
        )
    job_list = zp_data.get("jobList")
    if not isinstance(job_list, list):
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR, message="响应缺少 jobList", retryable=True
        )
    if not job_list:
        return LoginProbeResult(LoginProbeStatus.EMPTY, code=code)
    if any(
        (job.get("salaryDesc") or "").strip()
        for job in job_list
        if isinstance(job, dict)
    ):
        return LoginProbeResult(LoginProbeStatus.AVAILABLE, code=code)
    return LoginProbeResult(LoginProbeStatus.UNAUTHENTICATED, code=code)


def is_logged_in_search_response(data: Any) -> bool:
    return classify_login_probe_response(data).status is LoginProbeStatus.AVAILABLE


def describe_login_probe_result(result: LoginProbeResult) -> str:
    context = []
    if result.code is not None:
        context.append(f"code: {result.code}")
    if result.message:
        context.append(result.message)
    suffix = f"（{'; '.join(context)}）" if context else ""
    if result.status is LoginProbeStatus.UNAUTHENTICATED:
        return f"未检测到可用登录态{suffix}"
    if result.status is LoginProbeStatus.RESTRICTED:
        return f"BOSS 接口返回限制状态{suffix}"
    if result.status is LoginProbeStatus.EMPTY:
        return "探测样本没有职位，暂时无法确认登录态"
    return f"登录探测响应异常{suffix}"


def probe_login_state(
    cdp: CDPSession,
    sid: str,
    query: str = LOGIN_PROBE_QUERY,
    city_code: str = LOGIN_PROBE_CITY,
    timeout: float = PROBE_CAPTURE_TIMEOUT,
) -> LoginProbeResult:
    """导航搜索页并旁听页面自身首个 joblist 响应。"""
    capture = NetworkJoblistCapture(cdp, sid)
    capture.enable()

    def navigate() -> None:
        cdp.send("Page.navigate", {"url": build_search_url(query, city_code, 1)}, sid)

    data = capture.wait_next_response(timeout=timeout, trigger=navigate)
    if data is None:
        return LoginProbeResult(
            LoginProbeStatus.RESPONSE_ERROR,
            message="未捕获到页面自身的搜索响应",
            retryable=True,
        )
    return classify_login_probe_response(data)


def check_login_state(cdp_port: int | None = None) -> LoginProbeResult:
    """通过 CDP 检测 BOSS 登录状态（不会启动浏览器）。"""
    cdp: CDPSession | None = None
    target_id: str | None = None
    try:
        cdp = CDPSession(cdp_port)
        target_id, sid = create_page_session(cdp)
        return probe_login_state(cdp, sid)
    except (BossCDPError, TimeoutError, OSError, ValueError) as exc:
        return LoginProbeResult(LoginProbeStatus.RESPONSE_ERROR, message=str(exc))
    finally:
        if cdp is not None:
            if target_id is not None:
                try:
                    cdp.send("Target.closeTarget", {"targetId": target_id})
                except Exception:  # noqa: BLE001 - 清理失败忽略
                    log.debug("关闭登录探测 target 失败", exc_info=True)
            cdp.close()


# ============================================================
# 列表 / 详情抓取
# ============================================================
def _gate_first_response(data: Any) -> None:
    result = classify_login_probe_response(data)
    if result.status is LoginProbeStatus.AVAILABLE:
        return
    if result.status is LoginProbeStatus.UNAUTHENTICATED:
        raise LoginGateError(
            "未检测到 BOSS 直聘登录态。请先运行登录命令扫码，或先在专用浏览器中登录 zhipin.com。"
        )
    if result.status is LoginProbeStatus.RESTRICTED:
        raise LoginGateError(
            f"{describe_login_probe_result(result)}，已停止抓取。"
            "请先在浏览器中完成验证或稍后再试，不要重复触发登录探测。"
        )
    if result.status is LoginProbeStatus.EMPTY:
        return
    raise LoginGateError(f"{describe_login_probe_result(result)}，已停止抓取。")


def scrape_list(
    keyword: str,
    city: str = "全国",
    limit: int = DEFAULT_LIST_PAGE_SIZE,
    cdp_port: int | None = None,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """抓取列表页真实岗位（明文薪资），只返回 list 级字段。"""
    city_name, city_code = resolve_city(city)
    limit = max(1, int(limit or DEFAULT_LIST_PAGE_SIZE))
    pages = max_pages or max(1, (limit + DEFAULT_LIST_PAGE_SIZE - 1) // DEFAULT_LIST_PAGE_SIZE)
    pages = min(pages, MAX_PAGES)

    ensure_cdp_browser(cdp_port)
    cdp = CDPSession(cdp_port)
    target_id: str | None = None
    all_jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        target_id, sid = attach_existing_page(cdp, background=True)
        capture = NetworkJoblistCapture(cdp, sid)
        capture.enable()
        for page in range(1, pages + 1):
            if page == 1:
                url = build_search_url(keyword, city_code, page)

                def trigger_navigate(target_url: str = url) -> None:
                    cdp.send("Page.navigate", {"url": target_url}, sid)
                    time.sleep(1.5)

                data = capture.wait_next_response(
                    timeout=PROBE_CAPTURE_TIMEOUT, trigger=trigger_navigate
                )
                if data is None:
                    if not all_jobs:
                        raise BossCDPError(
                            "未捕获到 BOSS 搜索响应：可能未登录、被风控或页面加载失败。"
                            "请确认专用浏览器可正常打开 zhipin.com 搜索页。"
                        )
                    break
                _gate_first_response(data)
            else:
                cdp.eval_js("window.scrollTo(0, document.body.scrollHeight); void 0;", sid)
                data = capture.wait_next_response(timeout=20)
                if data is None:
                    break

            for job in map_api_jobs(data):
                key = job.get("job_link") or job.get("title") or ""
                if not key or key in seen:
                    continue
                seen.add(key)
                all_jobs.append(job)
            if len(all_jobs) >= limit:
                break
            has_more = (data.get("zpData") or {}).get("hasMore")
            if has_more is False:
                break
    finally:
        if target_id is not None:
            try:
                cdp.send("Target.closeTarget", {"targetId": target_id})
            except Exception:  # noqa: BLE001 - 清理失败忽略
                log.debug("关闭列表 target 失败", exc_info=True)
        with contextlib.suppress(Exception):
            cdp.close()

    if not all_jobs:
        raise BossCDPError(f"BOSS 未返回岗位（城市: {city_name or city}，关键词: {keyword}）")
    return all_jobs[:limit]


def scrape_detail(
    url: str,
    cdp_port: int | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    """打开详情页并提取 JD（交互式补抓用）。"""
    if not url:
        raise BossCDPError("详情 URL 不能为空")
    ensure_cdp_browser(cdp_port)
    cdp = CDPSession(cdp_port)
    target_id: str | None = None
    last_error: Exception | None = None
    try:
        target_id, sid = attach_existing_page(cdp, background=True)
        cdp.send("Page.navigate", {"url": url}, sid)
        for attempt in range(max(1, attempts)):
            time.sleep(2.0 if attempt == 0 else 2.5)
            cdp.eval_js("window.scrollBy(0, 400); void 0;", sid)
            value = cdp.eval_js(EXTRACT_DETAIL_JS, sid)
            try:
                extracted = json.loads(value) if isinstance(value, str) else None
            except (json.JSONDecodeError, ValueError):
                extracted = None
            if not isinstance(extracted, dict):
                continue
            try:
                fields = extract_detail_fields(extracted)
            except DetailLoginRequiredError as exc:
                raise BossCDPError(
                    "详情页被登录墙截断：登录态已不可用，请重新扫码登录后再试。"
                ) from exc
            except DetailExtractionError as exc:
                last_error = exc
                continue
            skills = [
                str(item).strip()
                for item in (extracted.get("tags") or [])
                if str(item).strip()
            ]
            return {
                "description": fields["jd"],
                "requirements": "",
                "boss_active_status": fields["boss_active_status"],
                "skills": " | ".join(skills),
                "url": url,
            }
    finally:
        if target_id is not None:
            try:
                cdp.send("Target.closeTarget", {"targetId": target_id})
            except Exception:  # noqa: BLE001 - 清理失败忽略
                log.debug("关闭详情 target 失败", exc_info=True)
        with contextlib.suppress(Exception):
            cdp.close()
    raise BossCDPError(f"未提取到岗位详情：{last_error or '页面未渲染出 JD'}")


# ============================================================
# CDP 专用浏览器管理
# ============================================================
def _browser_candidates(browser: str) -> list[str]:
    system = platform.system()
    if system == "Windows":
        candidates: list[str] = []
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            if browser == "edge":
                candidates.append(
                    ntpath.join(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe")
                )
            else:
                candidates.append(
                    ntpath.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe")
                )
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env_name)
            if not base:
                continue
            if browser == "edge":
                candidates.append(
                    ntpath.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
                )
            else:
                candidates.append(
                    ntpath.join(base, "Google", "Chrome", "Application", "chrome.exe")
                )
        return candidates
    if system == "Darwin":
        if browser == "edge":
            return ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    if browser == "edge":
        return ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"]
    return [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ]


def get_default_browser_path(browser: str = "chrome") -> str:
    candidates = _browser_candidates(browser)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else (browser if browser == "edge" else "chrome")


def browser_executable_exists(path: str) -> bool:
    if not path:
        return False
    if os.path.isabs(path):
        return os.path.exists(path)
    return shutil.which(path) is not None


def find_browser() -> tuple[str, str] | None:
    """返回可用的 (browser, executable)；Chrome 优先，其次 Edge。"""
    for browser in ("chrome", "edge"):
        path = get_default_browser_path(browser)
        if browser_executable_exists(path):
            return browser, path
    return None


def prepare_cdp_profile() -> Path:
    CDP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return CDP_DATA_DIR


def is_cdp_ready(cdp_port: int | None = None) -> bool:
    port = cdp_port or DEFAULT_CDP_PORT
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 - 任何网络异常都视为未就绪
        return False


def cdp_backend_available(cdp_port: int | None = None) -> bool:
    """CDP 是否可用：端口已就绪，或本机有可启动的 Chrome/Edge。"""
    return is_cdp_ready(cdp_port) or find_browser() is not None


def launch_cdp_browser(
    cdp_port: int | None = None, browser: str | None = None
) -> tuple[str, str]:
    port = cdp_port or DEFAULT_CDP_PORT
    chosen = find_browser()
    if chosen is None:
        raise BossCDPError(
            "未检测到 Chrome 或 Edge。请先安装 Chrome/Edge 后重试（不会回退 Chromium）。"
        )
    browser_name, executable = chosen
    if browser and browser != browser_name:
        path = get_default_browser_path(browser)
        if browser_executable_exists(path):
            browser_name, executable = browser, path
    profile = prepare_cdp_profile()
    cmd = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*",
        "--start-maximized",
    ]
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        if flags:
            kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    return browser_name, str(profile)


def wait_for_cdp(cdp_port: int | None = None, timeout: float = 25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_cdp_ready(cdp_port):
            return True
        time.sleep(0.5)
    return False


def ensure_cdp_browser(cdp_port: int | None = None) -> None:
    """确保专用 CDP 浏览器可用；未启动时自动拉起专用 profile。"""
    if is_cdp_ready(cdp_port):
        return
    launch_cdp_browser(cdp_port)
    if not wait_for_cdp(cdp_port):
        raise BossCDPError(
            f"专用 CDP 浏览器启动后端口 {cdp_port or DEFAULT_CDP_PORT} 仍不可用；"
            "请检查是否有其他程序占用该端口，或手动运行登录命令。"
        )


def normalize_profile_path(path: str) -> str:
    clean = (path or "").strip("\"'")
    if platform.system() == "Windows":
        return ntpath.normcase(ntpath.normpath(clean))
    return os.path.realpath(os.path.expanduser(clean))


def extract_user_data_dir(command: str) -> str | None:
    match = re.search(r"--user-data-dir=(\"[^\"]+\"|'[^']+'|\S+)", command or "")
    if not match:
        return None
    return match.group(1).strip("\"'")


def _iter_browser_processes() -> list[tuple[int, str]]:
    if platform.system() == "Windows":
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
        except Exception:  # noqa: BLE001 - 进程枚举失败按空处理
            return []
        if not completed.stdout.strip():
            return []
        try:
            data = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            return []
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        processes = []
        for item in data:
            try:
                processes.append((int(item.get("ProcessId")), item.get("CommandLine") or ""))
            except (TypeError, ValueError):
                continue
        return processes

    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=8
        )
    except Exception:  # noqa: BLE001 - 进程枚举失败按空处理
        return []
    processes = []
    for line in completed.stdout.splitlines():
        lower = line.lower()
        if "chrome" not in lower and "msedge" not in lower and "edge" not in lower:
            continue
        try:
            pid_text, command = line.strip().split(None, 1)
            processes.append((int(pid_text), command))
        except ValueError:
            continue
    return processes


def _terminate_process(pid: int) -> None:
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def stop_cdp_browser() -> int:
    """只关闭使用 Career Kit 专用 profile 的浏览器，不碰用户主浏览器。"""
    target = normalize_profile_path(str(CDP_DATA_DIR))
    pids = [
        pid
        for pid, command in _iter_browser_processes()
        if (path := extract_user_data_dir(command))
        and normalize_profile_path(path) == target
    ]
    for pid in pids:
        try:
            _terminate_process(pid)
        except (OSError, subprocess.SubprocessError):
            continue
    return len(pids)
