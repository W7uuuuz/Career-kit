"""Career Kit 本地控制台：HTTP + 静态前端，读写同一份档案。

设计原则：
- 只绑定 127.0.0.1；启动时生成一次性 token，API 必须带 token。
- 前端不使用 localStorage；所有打卡写回档案，MCP 下次直接读到。
- 与 MCP 共用 `src.tools.*` 领域函数，不复制业务逻辑。

启动：
    python -m src.web --open
    career-kit-serve --open
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .assets import get_assets_root, kind_assets_dir
from .core.artifacts.store import ArtifactStore
from .core.orchestrator import state_machine
from .desktop import runtime_state_path
from .guidance import phase_type_label, warnings
from .models import TaskStatus
from .paths import LOGS_DIR
from .tools.application_tracker import (
    add_application,
    find_active_duplicate,
)
from .tools.dashboard import render_roadmap_map
from .tools.profile import (
    get_active_profile_name,
    load_profile,
    profile_lock,
    save_profile,
)
from .tools.task_manager import (
    checkin_task as do_checkin,
    record_capability_evidence,
    resolve_current_phase,
)

WEB_DIR = Path(__file__).parent / "web_ui"
# Vue 构建产物目录（运行时从静态目录提供前端：/ 与 /assets/*）
DIST_DIR = WEB_DIR / "dist"

# 日志：pythonw 分离启动时 sys.stdout/sys.stderr 为 None，uvicorn 默认
# formatter 会调用 sys.stdout.isatty() 抛 ValueError，因此必须先把日志
# 落到文件，并禁用 uvicorn 自带的 log_config。
LOG_FILE_NAME = "web.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_LOG_LOCK = threading.Lock()
_LOG_HANDLER: logging.Handler | None = None
_LOG_FILE: Path | None = None
_REDIRECT_STREAMS: list[Any] = []


def _open_redirect_stream(path: str | Path, mode: str) -> Any:
    """打开重定向流并登记，避免被垃圾回收后关闭。"""
    stream = open(path, mode, encoding="utf-8", buffering=1)  # noqa: SIM115 - 常驻重定向流
    _REDIRECT_STREAMS.append(stream)
    return stream


def _redirect_std_streams(log_file: Path) -> None:
    """sys.stdout/sys.stderr 为 None 时重定向，避免任何写入直接崩。"""
    if sys.stdout is None:
        with suppress(Exception):
            sys.stdout = _open_redirect_stream(os.devnull, "w")
    if sys.stderr is None:
        with suppress(Exception):
            sys.stderr = _open_redirect_stream(log_file, "a")


def _setup_logging() -> Path:
    """幂等建立文件日志；返回日志文件路径。

    可在 main 与 create_server 中重复调用：同一路径只挂一个
    RotatingFileHandler，并确保 stdout/stderr 不再是 None。
    """
    global _LOG_HANDLER, _LOG_FILE
    log_file = Path(LOGS_DIR) / LOG_FILE_NAME
    with _LOG_LOCK:
        if log_file != _LOG_FILE or _LOG_HANDLER is None:
            try:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.handlers.RotatingFileHandler(
                    log_file,
                    maxBytes=LOG_MAX_BYTES,
                    backupCount=LOG_BACKUP_COUNT,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter(LOG_FORMAT))
                root = logging.getLogger()
                if _LOG_HANDLER is not None:
                    root.removeHandler(_LOG_HANDLER)
                    with suppress(Exception):
                        _LOG_HANDLER.close()
                root.addHandler(handler)
                if root.level == logging.NOTSET or root.level > logging.INFO:
                    root.setLevel(logging.INFO)
                _LOG_HANDLER = handler
                _LOG_FILE = log_file
            except Exception:  # noqa: BLE001 - 日志不可写时不能让启动直接失败
                pass
    _redirect_std_streams(log_file)
    return log_file


def _reset_logging() -> None:
    """关闭并移除文件日志与重定向流（测试隔离用）。"""
    global _LOG_HANDLER, _LOG_FILE
    with _LOG_LOCK:
        handler = _LOG_HANDLER
        _LOG_HANDLER = None
        _LOG_FILE = None
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            with suppress(Exception):
                handler.close()
    while _REDIRECT_STREAMS:
        stream = _REDIRECT_STREAMS.pop()
        with suppress(Exception):
            stream.close()


def _report_startup_error(exc: Exception, detached: bool) -> None:
    """启动失败时落日志；分离启动的 Windows 进程再弹窗提示日志路径。"""
    log_file = Path(LOGS_DIR) / LOG_FILE_NAME
    message = f"Career Kit 启动失败：{exc}\n\n日志：{log_file}"
    if not detached:
        with suppress(Exception):
            print(message, file=sys.stderr)
        return
    if sys.platform != "win32":
        return
    if os.environ.get("CAREER_KIT_NO_DIALOG") == "1":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Career Kit 启动失败", 0x10)
    except Exception:  # noqa: BLE001 - 弹窗失败不影响退出码
        pass



# ---------------------------------------------------------------------------
# 状态构建
# ---------------------------------------------------------------------------


def _task_payload(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "desc": task.description,
        "status": task.status,
        "priority": task.priority,
        "milestone_id": task.milestone_id,
        "checkin_mode": task.checkin_mode or "once",
        "checkin_goal": task.checkin_goal,
        "checkin_progress": task.checkin_progress,
        "how_to": list(task.how_to or []),
        "resources": list(task.resources or []),
        "done_criteria": task.done_criteria or "",
    }


def _asset_url(path: str | Path) -> str:
    """把资产绝对路径转成受 token 保护的本地 URL。"""
    if not path:
        return ""
    return "/api/asset?path=" + quote(str(path), safe="")


# SSE 订阅者挂在 app.state 上；这里只保留集合锁，兼容线程池里触发的广播
_SUBSCRIBERS_LOCK = threading.Lock()

# 浏览器会话租约：页面每 20 秒续期；异常关闭时 90 秒后回收。
# 全部页面关闭后留 5 秒缓冲，避免刷新/前进后退误杀服务。
SESSION_TTL_SECONDS = 90.0
SESSION_EXIT_GRACE_SECONDS = 5.0
SESSION_STARTUP_GRACE_SECONDS = 120.0


class SessionRegistry:
    """记录打开的页面会话，决定「最后一个页面关闭后退出」。"""

    def __init__(self) -> None:
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ever_opened = False
        self._empty_since: float | None = None

    def open(self, session_id: str, now: float | None = None) -> None:
        if not session_id:
            return
        current = time.monotonic() if now is None else now
        with self._lock:
            self._sessions[session_id] = current
            self._ever_opened = True
            self._empty_since = None

    def close(self, session_id: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._sessions.pop(session_id, None)
            if not self._sessions:
                self._empty_since = current

    def prune(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        with self._lock:
            stale = [
                session_id
                for session_id, seen in self._sessions.items()
                if current - seen > SESSION_TTL_SECONDS
            ]
            for session_id in stale:
                self._sessions.pop(session_id, None)
            if not self._sessions and self._empty_since is None:
                self._empty_since = current

    def active(self) -> int:
        with self._lock:
            return len(self._sessions)

    def ever_opened(self) -> bool:
        with self._lock:
            return self._ever_opened

    def should_exit(self, started_at: float, now: float) -> bool:
        """无活跃页面且超过缓冲时间时返回 True。"""
        with self._lock:
            if self._sessions:
                return False
            if self._ever_opened:
                since = self._empty_since if self._empty_since is not None else now
                return now - since >= SESSION_EXIT_GRACE_SECONDS
            return now - started_at >= SESSION_STARTUP_GRACE_SECONDS


def _broadcast_refresh(app: FastAPI) -> None:
    """写操作完成后通知所有 SSE 连接（可从线程池线程调用）。"""
    loop = getattr(app.state, "loop", None)
    with _SUBSCRIBERS_LOCK:
        subscribers = list(getattr(app.state, "subscribers", ()))
    for subscriber in subscribers:
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(subscriber.put_nowait, "refresh")
        else:
            with suppress(Exception):
                subscriber.put_nowait("refresh")


def _run_sync(fn_name: str) -> str:
    """控制台写操作后刷新 Core v2 artifact；失败不阻断，返回 warning 文本。"""
    try:
        from .core import sync as core_sync

        getattr(core_sync, fn_name)(get_active_profile_name())
    except Exception as exc:  # noqa: BLE001 - 同步失败不应让控制台写操作失败
        return f"Core v2 同步失败（{fn_name}）：{exc}"
    return ""


def _collect_reports(profile_name: str) -> list[dict[str, Any]]:
    """列出调研报告（用于控制台筛选）。"""
    directory = kind_assets_dir("research", profile_name)
    reports: list[dict[str, Any]] = []
    for json_path in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        stem = json_path.with_suffix("")
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        failed = [
            str(s.get("source") or "未知源")
            for s in (data.get("source_status") or [])
            if isinstance(s, dict) and s.get("status") == "failed"
        ]
        reports.append({
            "direction": data.get("direction") or stem.name,
            "generated_at": data.get("generated_at", ""),
            "counts": counts,
            "failed_sources": failed,
            "md": _asset_url(stem.with_suffix(".md")) if stem.with_suffix(".md").exists() else "",
            "json": _asset_url(json_path),
        })
    return reports


def update_task(task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """编辑任务字段（控制台写操作）。"""
    with profile_lock():
        profile = load_profile()
        task = profile.get_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        if "name" in fields:
            name = str(fields["name"] or "").strip()
            if not name:
                raise ValueError("任务名不能为空")
            task.name = name
        if "description" in fields:
            task.description = str(fields["description"] or "")
        if "priority" in fields and fields["priority"] in ("high", "medium", "low"):
            task.priority = str(fields["priority"])
        if "how_to" in fields:
            task.how_to = [str(x) for x in (fields["how_to"] or []) if str(x).strip()]
        if "done_criteria" in fields:
            task.done_criteria = str(fields["done_criteria"] or "")
        if "resources" in fields and isinstance(fields["resources"], list):
            task.resources = [r for r in fields["resources"] if isinstance(r, dict)]
        if "checkin_mode" in fields and fields["checkin_mode"] in ("once", "daily", "percent"):
            task.checkin_mode = str(fields["checkin_mode"])
        if "checkin_goal" in fields:
            task.checkin_goal = float(fields["checkin_goal"] or 0)
        profile.touch()
        save_profile(profile)
        sync_warning = _run_sync("sync_execution_state")
        state = build_state(profile)
        if sync_warning:
            state["sync_warning"] = sync_warning
        return state


def add_application_entry(data: dict[str, Any]) -> dict[str, Any]:
    """新增投递记录（控制台写操作）。"""
    company = str(data.get("company") or "").strip()
    role = str(data.get("role") or "").strip()
    if not company:
        raise ValueError("公司名称不能为空")
    with profile_lock():
        profile = load_profile()
        if find_active_duplicate(profile, company, role):
            raise ValueError("已有同公司同岗位的活跃投递记录")
        add_application(
            profile,
            company=company,
            role=role,
            status=str(data.get("status") or "applied"),
            channel=str(data.get("channel") or ""),
            notes=str(data.get("notes") or ""),
        )
        profile.touch()
        save_profile(profile)
        sync_warning = _run_sync("sync_application_state")
        state = build_state(profile)
        if sync_warning:
            state["sync_warning"] = sync_warning
        return state


def undo_task(task_id: str) -> None:
    """把任务恢复为待办（本地控制台的「撤销」）。"""
    with profile_lock():
        profile = load_profile()
        task = profile.get_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        # 删除最近一条打卡与对应能力证据，避免周检视/能力证据继续计入
        for idx in range(len(profile.checkins) - 1, -1, -1):
            if profile.checkins[idx].task_id == task_id:
                del profile.checkins[idx]
                break
        evidence = (profile.have or {}).get("capability_evidence")
        if isinstance(evidence, list):
            for idx in range(len(evidence) - 1, -1, -1):
                item = evidence[idx]
                if isinstance(item, dict) and item.get("task") == task.name:
                    del evidence[idx]
                    break
        task.status = TaskStatus.PENDING
        task.started_at = None
        task.completed_at = None
        task.checkin_progress = 0
        profile.touch()
        save_profile(profile)
        sync_warning = _run_sync("sync_execution_state")
        if sync_warning:
            sys.stderr.write(sync_warning + "\n")


def _matches_alignment_stage(data: Any, stage: str) -> bool:
    if not isinstance(data, dict):
        return False
    meta = data.get("meta")
    return isinstance(meta, dict) and meta.get("stage") == stage


def _resolve_alignment_artifact(
    store: ArtifactStore, profile_name: str, stage: str, artifact_id: str
) -> dict[str, Any] | None:
    """按 core_state 的 id 读取 artifact，缺失时回退 latest；阶段不符视为缺失。"""
    if artifact_id:
        try:
            data = store.load(artifact_id)
            if _matches_alignment_stage(data, stage):
                return data
        except Exception:
            pass
    try:
        data = store.latest(profile_name, stage)
    except Exception:
        return None
    return data if _matches_alignment_stage(data, stage) else None


def _company_pool_alignment(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    counts = artifact.get("counts") if isinstance(artifact.get("counts"), dict) else {}
    companies = [c for c in artifact.get("companies") or [] if isinstance(c, dict)]
    selected = [c for c in companies if c.get("status") != "excluded"]
    return {
        "id": str(meta.get("id") or ""),
        "counts": dict(counts),
        "scrapable": [
            str(c.get("name") or c.get("id") or "") for c in selected if c.get("scrapable")
        ],
        "not_scrapable": [
            str(c.get("name") or c.get("id") or "") for c in selected if not c.get("scrapable")
        ],
    }


def _evidence_alignment(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    counts = artifact.get("counts") if isinstance(artifact.get("counts"), dict) else {}
    confidence = artifact.get("confidence") if isinstance(artifact.get("confidence"), dict) else {}
    reports = artifact.get("report_paths") if isinstance(artifact.get("report_paths"), dict) else {}
    return {
        "id": str(meta.get("id") or ""),
        "counts": dict(counts),
        "confidence": dict(confidence),
        "report_md": _asset_url(reports.get("md", "")),
        "index": _asset_url(reports.get("json", "")),
    }


def _requirement_alignment(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    high_frequency = artifact.get("high_frequency")
    hard_requirements = artifact.get("hard_requirements")
    return {
        "id": str(meta.get("id") or ""),
        "high_frequency_count": len(high_frequency) if isinstance(high_frequency, list) else 0,
        "hard_requirement_count": (
            len(hard_requirements) if isinstance(hard_requirements, list) else 0
        ),
        "confidence_jd": str(artifact.get("confidence_jd") or ""),
        "confidence_interview": str(artifact.get("confidence_interview") or ""),
    }


def _execution_plan_alignment(artifact: dict[str, Any]) -> dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    roadmap = artifact.get("roadmap") if isinstance(artifact.get("roadmap"), dict) else {}
    phases = roadmap.get("phases")
    return {
        "id": str(meta.get("id") or ""),
        "applied": bool(artifact.get("applied")),
        "strategy_summary": str(artifact.get("strategy_summary") or ""),
        "phase_count": len(phases) if isinstance(phases, list) else 0,
        "diff_summary": str(artifact.get("diff_summary") or ""),
    }


def _empty_alignment(stage: str = "") -> dict[str, Any]:
    return {
        "stage": stage,
        "company_pool": None,
        "evidence": None,
        "requirement": None,
        "execution_plan": None,
        "next_tool": "",
    }


def _build_alignment(profile: Any) -> dict[str, Any]:
    """汇总 Core v2 企业适配状态；任何一步失败都退化为空值，不拖垮整个 state。"""
    core_state = getattr(profile, "core_state", {})
    if not isinstance(core_state, dict):
        core_state = {}
    result = _empty_alignment(str(core_state.get("stage") or ""))
    profile_name = get_active_profile_name()

    try:
        result["next_tool"] = str(state_machine.next_action(profile_name).get("next_tool") or "")
    except Exception:
        result["next_tool"] = ""

    builders = (
        (
            "company_pool",
            state_machine.STAGE_COMPANY_POOL,
            "company_pool_id",
            _company_pool_alignment,
        ),
        ("evidence", state_machine.STAGE_EVIDENCE, "evidence_run_id", _evidence_alignment),
        (
            "requirement",
            state_machine.STAGE_REQUIREMENT,
            "requirement_profile_id",
            _requirement_alignment,
        ),
        (
            "execution_plan",
            state_machine.STAGE_EXECUTION_PLAN,
            "execution_plan_id",
            _execution_plan_alignment,
        ),
    )
    try:
        store = ArtifactStore()
    except Exception:
        return result
    for key, stage, id_key, builder in builders:
        try:
            artifact = _resolve_alignment_artifact(
                store, profile_name, stage, str(core_state.get(id_key) or "")
            )
            result[key] = builder(artifact) if artifact is not None else None
        except Exception:
            result[key] = None
    return result


def build_state(profile: Any | None = None) -> dict[str, Any]:
    """把档案整理成前端需要的只读快照。"""
    profile = profile or load_profile()
    plan = profile.plan if isinstance(profile.plan, dict) else {}
    roadmap = plan.get("roadmap", plan)
    raw_phases = roadmap.get("phases") if isinstance(roadmap, dict) else []
    # 损坏的路线图（phases 不是列表 / 元素不是对象）不能让整个控制台崩掉
    phases = (
        [p for p in raw_phases if isinstance(p, dict)]
        if isinstance(raw_phases, list)
        else []
    )

    phase_ids = [str(p.get("id") or f"phase_{i + 1}") for i, p in enumerate(phases)]
    try:
        current = resolve_current_phase(profile)
    except Exception:  # noqa: BLE001 - 损坏数据退化为无当前阶段
        current = None
    current_phase_id = current["phase_id"] if current else None
    if current_phase_id is None and phase_ids:
        current_phase_id = phase_ids[-1]

    phases_out: list[dict[str, Any]] = []
    total_done = 0
    total_tasks = 0
    for idx, phase in enumerate(phases):
        phase_id = phase_ids[idx]
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        done = sum(1 for t in phase_tasks if t.status in ("completed", "skipped"))
        total_done += done
        total_tasks += len(phase_tasks)
        raw_milestones = phase.get("milestones")
        milestones = (
            [ms for ms in raw_milestones if isinstance(ms, dict)]
            if isinstance(raw_milestones, list)
            else []
        )
        ms_names = {
            ms.get("id"): ms.get("name", "")
            for ms in milestones
        }
        milestone_tasks = []
        for ms in milestones:
            raw_task_defs = ms.get("tasks")
            task_defs = raw_task_defs if isinstance(raw_task_defs, list) else []
            for t in task_defs:
                if isinstance(t, dict):
                    milestone_tasks.append({
                        "name": t.get("name", ""),
                        "desc": t.get("description", ""),
                        "priority": t.get("priority", "medium"),
                        "done_criteria": t.get("done_criteria", ""),
                    })
        phases_out.append({
            "id": phase_id,
            "name": phase.get("name", phase_id),
            "type": phase.get("type", "learn"),
            "type_label": phase_type_label(phase.get("type", "learn")),
            "goal": phase.get("goal", ""),
            "company": phase.get("company", ""),
            "rationale": phase.get("rationale", ""),
            "target_level": phase.get("target_level", ""),
            "resume_value": phase.get("resume_value", ""),
            "kpi": phase.get("kpi") if isinstance(phase.get("kpi"), dict) else {},
            "access_paths": [
                item for item in (phase.get("access_paths") or []) if isinstance(item, dict)
            ],
            "fallback_paths": [
                item for item in (phase.get("fallback_paths") or []) if isinstance(item, dict)
            ],
            "conversion_risk": (
                phase.get("conversion_risk")
                if isinstance(phase.get("conversion_risk"), dict)
                else {}
            ),
            "time_window": (
                phase.get("time_window") if isinstance(phase.get("time_window"), dict) else {}
            ),
            "decision_gate": (
                phase.get("decision_gate")
                if isinstance(phase.get("decision_gate"), dict)
                else {}
            ),
            "jd_status": phase.get("jd_status", ""),
            "condition": phase.get("condition", ""),
            "is_current": phase_id == current_phase_id,
            "done": done,
            "total": len(phase_tasks),
            "milestone_names": ms_names,
            "milestone_tasks": milestone_tasks,
            "tasks": [_task_payload(t) for t in phase_tasks],
        })

    research = profile.research if isinstance(profile.research, dict) else {}
    research_out = {}
    if research.get("report_md"):
        failed = [
            s for s in (research.get("source_status") or [])
            if isinstance(s, dict) and s.get("status") == "failed"
        ]
        research_out = {
            "generated_at": research.get("generated_at", ""),
            "counts": research.get("counts") or {},
            "report_md": _asset_url(research.get("report_md", "")),
            "report_json": _asset_url(research.get("report_json", "")),
            "failed_sources": [str(s.get("source") or "未知源") for s in failed],
        }

    reports = _collect_reports(get_active_profile_name())

    try:
        alignment = _build_alignment(profile)
    except Exception:
        alignment = _empty_alignment()

    applications = []
    for app in (profile.applications or [])[-10:]:
        applications.append({
            "id": app.id,
            "company": app.company,
            "role": app.role,
            "status": app.status,
            "channel": app.channel,
            "applied_at": app.applied_at,
        })

    return {
        "profile": get_active_profile_name(),
        "start_level": (profile.gap or {}).get("start_level", ""),
        "strategy": (roadmap.get("strategy_summary", "") if isinstance(roadmap, dict) else ""),
        "phases": phases_out,
        "total_done": total_done,
        "total_tasks": total_tasks,
        "all_complete": bool(profile.tasks) and all(
            t.status in ("completed", "skipped") for t in profile.tasks
        ),
        "warnings": warnings(profile),
        "research": research_out,
        "reports": reports,
        "applications": applications,
        "alignment": alignment,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


_STATIC_BUILD_HINT = (
    "前端尚未构建：未找到 src/web_ui/dist/index.html。\n"
    "请在仓库根目录构建 Vue 前端（产物输出到 src/web_ui/dist），"
    "或参考 docs/install.md 的本地控制台说明。"
)


def _check_token(request: Request) -> JSONResponse | None:
    """API token 校验：支持 X-CK-Token 头或 ?token= 查询参数。"""
    expected = request.app.state.token
    if request.headers.get("X-CK-Token", "") == expected:
        return None
    if request.query_params.get("token", "") == expected:
        return None
    return JSONResponse(status_code=403, content={"error": "invalid token"})


async def _json_body(request: Request) -> tuple[dict[str, Any], JSONResponse | None]:
    try:
        raw = await request.body()
        data = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}, JSONResponse(status_code=400, content={"error": "invalid json"})
    return (data if isinstance(data, dict) else {}), None


def _do_checkin(body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id required")
    status = str(body.get("status") or "completed")
    amount = float(body.get("amount") or 0)
    if status == "pending":
        undo_task(task_id)
        return build_state()
    with profile_lock():
        profile, _ = do_checkin(load_profile(), task_id, status=status, amount=amount)
        task = profile.get_task(task_id)
        if task and task.status == "completed":
            record_capability_evidence(profile, task)
        save_profile(profile)
    sync_warning = _run_sync("sync_execution_state")
    state = build_state(profile)
    if sync_warning:
        state["sync_warning"] = sync_warning
    return state


def _do_task(body: dict[str, Any]) -> dict[str, Any]:
    task_id = str(body.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("task_id required")
    return update_task(task_id, body)


def _static_file(relative: str) -> Response:
    """从 dist 目录读取静态文件；越界与缺失统一按 404，未构建返回 503。"""
    root = DIST_DIR
    if not root.is_dir():
        return PlainTextResponse(_STATIC_BUILD_HINT, status_code=503)
    root_resolved = root.resolve()
    target = (root_resolved / relative).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not found"})
    if not target.is_file():
        return JSONResponse(status_code=404, content={"error": "not found"})
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(content=target.read_bytes(), media_type=ctype)


async def _watch_sessions(app: FastAPI) -> None:
    """回收过期会话；最后一个页面关闭后请求 uvicorn 优雅退出。"""
    while True:
        await asyncio.sleep(1.0)
        registry: SessionRegistry = app.state.sessions
        registry.prune()
        if not app.state.exit_when_idle:
            continue
        if registry.should_exit(app.state.started_at, time.monotonic()):
            app.state.shutting_down = True
            server = getattr(app.state, "uvicorn_server", None)
            if server is not None:
                server.should_exit = True
            return


def create_app(token: str, exit_when_idle: bool = False) -> FastAPI:
    """构建 FastAPI 应用；token、SSE 订阅者与会话注册表挂在 app.state 上。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.loop = asyncio.get_running_loop()
        app.state.started_at = time.monotonic()
        watchdog = asyncio.create_task(_watch_sessions(app))
        try:
            yield
        finally:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog

    app = FastAPI(
        title="Career Kit 职业地图",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.token = token
    app.state.subscribers = set()
    app.state.loop = None
    app.state.started_at = time.monotonic()
    app.state.exit_when_idle = exit_when_idle
    app.state.shutting_down = False
    app.state.sessions = SessionRegistry()
    app.state.uvicorn_server = None

    @app.get("/api/health")
    def api_health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/state")
    def api_state(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        try:
            return build_state()
        except Exception as exc:  # noqa: BLE001 - 状态构建失败要返回可读 JSON
            return JSONResponse(
                status_code=500, content={"error": f"状态构建失败：{exc}"}
            )

    @app.post("/api/session/open")
    async def api_session_open(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        body, error = await _json_body(request)
        if error is not None:
            return error
        session_id = str(body.get("id") or "").strip()
        if not session_id:
            return JSONResponse(status_code=400, content={"error": "session id required"})
        request.app.state.sessions.open(session_id)
        return {"ok": True}

    @app.post("/api/session/ping")
    async def api_session_ping(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        body, error = await _json_body(request)
        if error is not None:
            return error
        session_id = str(body.get("id") or "").strip()
        if not session_id:
            return JSONResponse(status_code=400, content={"error": "session id required"})
        request.app.state.sessions.open(session_id)
        return {"ok": True}

    @app.post("/api/session/close")
    async def api_session_close(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        session_id = str(request.query_params.get("id") or "").strip()
        if not session_id:
            body, error = await _json_body(request)
            if error is not None:
                return error
            session_id = str(body.get("id") or "").strip()
        request.app.state.sessions.close(session_id)
        return {"ok": True}

    @app.post("/api/shutdown")
    def api_shutdown(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        server = getattr(request.app.state, "uvicorn_server", None)
        if server is None:
            return JSONResponse(status_code=503, content={"error": "shutdown unavailable"})
        request.app.state.shutting_down = True
        server.should_exit = True
        return {"ok": True}

    @app.get("/api/events")
    async def api_events(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        subscriber: asyncio.Queue[str] = asyncio.Queue()
        with _SUBSCRIBERS_LOCK:
            request.app.state.subscribers.add(subscriber)

        async def stream() -> Any:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        message = await asyncio.wait_for(subscriber.get(), timeout=15)
                    except TimeoutError:
                        yield ": ping\n\n"
                    else:
                        yield f"data: {message}\n\n"
            finally:
                with _SUBSCRIBERS_LOCK:
                    request.app.state.subscribers.discard(subscriber)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    @app.get("/api/asset")
    def api_asset(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        target = Path(request.query_params.get("path", "")).resolve()
        root = get_assets_root().resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return JSONResponse(
                status_code=403, content={"error": "asset outside root"}
            )
        if not target.is_file():
            return JSONResponse(status_code=404, content={"error": "asset not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return Response(content=target.read_bytes(), media_type=ctype)

    @app.get("/roadmap")
    def roadmap(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        base = f"{request.url.scheme}://{request.url.netloc}"
        html = render_roadmap_map(load_profile())
        html = html.replace("__CK_API_BASE__", base).replace("__CK_TOKEN__", token)
        return Response(content=html, media_type="text/html; charset=utf-8")

    @app.get("/")
    @app.get("/index.html")
    def index() -> Any:
        path = DIST_DIR / "index.html"
        if not path.is_file():
            return PlainTextResponse(_STATIC_BUILD_HINT, status_code=503)
        html = path.read_text(encoding="utf-8").replace("__CK_TOKEN__", token)
        return Response(content=html, media_type="text/html; charset=utf-8")

    @app.get("/assets/{asset_path:path}")
    def assets(asset_path: str) -> Any:
        return _static_file(f"assets/{asset_path}")

    @app.post("/api/checkin")
    async def api_checkin(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        body, error = await _json_body(request)
        if error is not None:
            return error
        try:
            state = await run_in_threadpool(_do_checkin, body)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        _broadcast_refresh(request.app)
        return {"ok": True, "state": state}

    @app.post("/api/task")
    async def api_task(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        body, error = await _json_body(request)
        if error is not None:
            return error
        try:
            state = await run_in_threadpool(_do_task, body)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        _broadcast_refresh(request.app)
        return {"ok": True, "state": state}

    @app.post("/api/application")
    async def api_application(request: Request) -> Any:
        denied = _check_token(request)
        if denied is not None:
            return denied
        body, error = await _json_body(request)
        if error is not None:
            return error
        try:
            state = await run_in_threadpool(add_application_entry, body)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        _broadcast_refresh(request.app)
        return {"ok": True, "state": state}

    return app


class UvicornServer:
    """把 uvicorn 包装成 http.server 的调用方式，保持 create_server 契约。

    - serve_forever() 可在后台线程运行；shutdown() 只置退出标记；
    - server_address 暴露真实 (host, port)，port=0 时是系统分配的端口；
    - 自己先 bind 拿到端口，再把 socket 交给 uvicorn，避免端口选择竞态。
    """

    def __init__(self, app: FastAPI, host: str, port: int) -> None:
        family, socktype, proto, _, address = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )[0]
        self._sock = socket.socket(family, socktype, proto)
        # Windows 上 SO_REUSEADDR 会允许重复绑定同一端口，导致「占用顺延」失效
        if sys.platform != "win32":
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(address)
            # 先 listen：测试/调用方在后台线程真正进入 uvicorn 前就可能连接，
            # 已 listen 的 socket 会先进入 backlog，避免 Linux 上偶发 Connection refused。
            self._sock.listen(128)
        except OSError:
            self._sock.close()
            raise
        self.server_address = self._sock.getsockname()[:2]
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=str(self.server_address[0]),
                port=int(self.server_address[1]),
                # 禁用 uvicorn 自带 log_config：pythonw 下 sys.stdout 为 None，
                # 默认 formatter 调用 isatty() 会抛 ValueError。日志统一走文件。
                log_config=None,
                log_level="warning",
                access_log=False,
            )
        )
        app.state.uvicorn_server = self._server
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def serve_forever(self) -> None:
        self._thread = threading.current_thread()
        try:
            self._server.run(sockets=[self._sock])
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        self._server.should_exit = True
        if self._thread is not None and self._thread is not threading.current_thread():
            self._stopped.wait(timeout=5)

    def server_close(self) -> None:
        with suppress(OSError):
            self._sock.close()


def create_server(
    host: str = "127.0.0.1", port: int = 8765, exit_when_idle: bool = False
) -> tuple[UvicornServer, str]:
    """创建服务器；端口占用时自动顺延。返回 (server, token)。"""
    # 直接调用 create_server（不经过 main）时也要先建立日志，
    # 否则 detached 进程里 uvicorn 任何 stderr 写入都可能失败。
    _setup_logging()
    token = secrets.token_urlsafe(18)
    app = create_app(token, exit_when_idle=exit_when_idle)
    last_error: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            return UvicornServer(app, host, candidate), token
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f"无法绑定 {host}:{port}-{port + 9}：{last_error}")


def _live_instance_url() -> str:
    """返回已在运行的控制台地址；进程已退出或文件损坏时返回空串。"""
    state_file = runtime_state_path()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    url = str(data.get("url") or "")
    if not url:
        return ""
    base = url.split("?", 1)[0].rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=1.0) as response:
            return url if response.status == 200 else ""
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Career Kit 本地职业地图")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="起始端口（占用时自动顺延）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--open", action="store_true", help="自动打开浏览器（默认行为）")
    group.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument(
        "--exit-when-idle",
        action="store_true",
        help="最后一个页面关闭后自动退出（桌面快捷方式默认开启）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # 先记录是否分离启动（重定向后 stdout/stderr 就不再是 None 了）
    detached = sys.stdout is None or sys.stderr is None
    log_file = _setup_logging()
    log = logging.getLogger("career_kit.web")
    args = build_parser().parse_args(argv)

    existing = _live_instance_url()
    if existing:
        log.info("复用已运行实例：%s", existing.split("?", 1)[0])
        print(f"Career Kit 已在运行：{existing}")
        if not args.no_open:
            webbrowser.open(existing)
        return 0

    try:
        server, token = create_server(
            args.host, args.port, exit_when_idle=args.exit_when_idle
        )
    except Exception as exc:  # noqa: BLE001 - 启动失败要落日志、给退出码、可弹窗
        logging.getLogger("career_kit.web").exception("启动失败")
        _report_startup_error(exc, detached)
        return 1

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/?token={token}"
    log.info(
        "启动成功：http://%s:%s/（日志 %s，数据 %s）",
        host,
        port,
        log_file,
        os.environ.get("CAREER_KIT_DATA_DIR") or "~/.career-kit",
    )
    state_file = runtime_state_path()
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {"pid": os.getpid(), "url": url, "started_at": time.time()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    print(f"Career Kit 职业地图：{url}")
    print("关闭页面后会自动停止；数据直接写入 ~/.career-kit，与 MCP 共用。")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("控制台已停止")
        with suppress(OSError):
            state_file.unlink()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
