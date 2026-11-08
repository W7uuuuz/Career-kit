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
import json
import mimetypes
import queue
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .assets import INDEX_FILENAME, get_assets_root, kind_assets_dir
from .core.artifacts.store import ArtifactStore
from .core.orchestrator import state_machine
from .guidance import warnings
from .models import TaskStatus
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
INDEX_FILE = WEB_DIR / "index.html"
APP_JS = WEB_DIR / "app.js"
STYLE_CSS = WEB_DIR / "style.css"


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


_SUBSCRIBERS: set[queue.Queue[str]] = set()
_SUBSCRIBERS_LOCK = threading.Lock()


def _broadcast_refresh() -> None:
    with _SUBSCRIBERS_LOCK:
        for subscriber in list(_SUBSCRIBERS):
            subscriber.put("refresh")


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
            "html": _asset_url(stem.with_suffix(".html")) if stem.with_suffix(".html").exists() else "",
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
        "report_html": _asset_url(reports.get("html", "")),
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
            "goal": phase.get("goal", ""),
            "company": phase.get("company", ""),
            "rationale": phase.get("rationale", ""),
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
            "report_html": _asset_url(research.get("report_html", "")),
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
        "assets_index": _asset_url(get_assets_root() / INDEX_FILENAME),
        "research": research_out,
        "reports": reports,
        "applications": applications,
        "alignment": alignment,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _json_response(handler: BaseHTTPRequestHandler, status: int, data: Any) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, body: bytes, ctype: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def create_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CareerKitWeb/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            if "/api/" in str(args[0] if args else ""):
                sys.stderr.write("[career-kit] %s\n" % (fmt % args))

        def _authorized(self) -> bool:
            if self.headers.get("X-CK-Token", "") == token:
                return True
            query = parse_qs(urlparse(self.path).query)
            return query.get("token", [""])[0] == token

        def _json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = INDEX_FILE.read_text(encoding="utf-8")
                html = html.replace("__CK_TOKEN__", token)
                _text_response(self, 200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/app.js":
                _text_response(self, 200, APP_JS.read_bytes(), "application/javascript; charset=utf-8")
                return
            if path == "/style.css":
                _text_response(self, 200, STYLE_CSS.read_bytes(), "text/css; charset=utf-8")
                return
            if path == "/roadmap":
                if not self._authorized():
                    _json_response(self, HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                    return
                host, port = self.server.server_address[:2]
                html = render_roadmap_map(load_profile())
                html = html.replace(
                    "__CK_API_BASE__", f"http://{host}:{port}"
                ).replace("__CK_TOKEN__", token)
                _text_response(
                    self, 200, html.encode("utf-8"), "text/html; charset=utf-8"
                )
                return
            if path == "/api/health":
                _json_response(self, 200, {"ok": True})
                return
            if path == "/api/state":
                if not self._authorized():
                    _json_response(self, HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                    return
                try:
                    state = build_state()
                except Exception as exc:  # noqa: BLE001 - 状态构建失败要返回可读 JSON
                    _json_response(
                        self,
                        500,
                        {"error": f"状态构建失败：{exc}"},
                    )
                    return
                _json_response(self, 200, state)
                return
            if path == "/api/events":
                if not self._authorized():
                    _json_response(self, HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                subscriber: queue.Queue[str] = queue.Queue()
                with _SUBSCRIBERS_LOCK:
                    _SUBSCRIBERS.add(subscriber)
                try:
                    while True:
                        try:
                            message = subscriber.get(timeout=15)
                            payload = f"data: {message}\n\n"
                        except queue.Empty:
                            payload = ": ping\n\n"
                        self.wfile.write(payload.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with _SUBSCRIBERS_LOCK:
                        _SUBSCRIBERS.discard(subscriber)
                return
            if path == "/api/asset":
                if not self._authorized():
                    _json_response(self, HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                    return
                raw = parse_qs(urlparse(self.path).query).get("path", [""])[0]
                target = Path(unquote(raw)).resolve()
                root = get_assets_root().resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    _json_response(self, HTTPStatus.FORBIDDEN, {"error": "asset outside root"})
                    return
                if not target.is_file():
                    _json_response(self, 404, {"error": "asset not found"})
                    return
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                _text_response(self, 200, target.read_bytes(), ctype)
                return
            _json_response(self, 404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/api/checkin", "/api/task", "/api/application"):
                _json_response(self, 404, {"error": "not found"})
                return
            if not self._authorized():
                _json_response(self, HTTPStatus.FORBIDDEN, {"error": "invalid token"})
                return
            try:
                body = self._json_body()
            except (ValueError, TypeError):
                _json_response(self, 400, {"error": "invalid json"})
                return

            try:
                if path == "/api/task":
                    task_id = str(body.get("task_id") or "").strip()
                    if not task_id:
                        _json_response(self, 400, {"error": "task_id required"})
                        return
                    state = update_task(task_id, body)
                elif path == "/api/application":
                    state = add_application_entry(body)
                else:
                    task_id = str(body.get("task_id") or "").strip()
                    status = str(body.get("status") or "completed")
                    amount = float(body.get("amount") or 0)
                    if not task_id:
                        _json_response(self, 400, {"error": "task_id required"})
                        return
                    if status == "pending":
                        undo_task(task_id)
                        state = build_state()
                    else:
                        with profile_lock():
                            profile, _ = do_checkin(
                                load_profile(), task_id, status=status, amount=amount
                            )
                            task = profile.get_task(task_id)
                            if task and task.status == "completed":
                                record_capability_evidence(profile, task)
                            save_profile(profile)
                        sync_warning = _run_sync("sync_execution_state")
                        state = build_state(profile)
                        if sync_warning:
                            state["sync_warning"] = sync_warning
            except ValueError as exc:
                _json_response(self, 400, {"error": str(exc)})
                return

            _broadcast_refresh()
            _json_response(self, 200, {"ok": True, "state": state})

    return Handler


def create_server(host: str = "127.0.0.1", port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    """创建服务器；端口占用时自动顺延。返回 (server, token)。"""
    token = secrets.token_urlsafe(18)
    last_error: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            server = ThreadingHTTPServer((host, candidate), create_handler(token))
            server.daemon_threads = True
            return server, token
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f"无法绑定 {host}:{port}-{port + 9}：{last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Career Kit 本地控制台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8765, help="起始端口（占用时自动顺延）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--open", action="store_true", help="自动打开浏览器（默认行为）")
    group.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        server, token = create_server(args.host, args.port)
    except OSError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1

    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/?token={token}"
    print(f"Career Kit 控制台：{url}")
    print("按 Ctrl+C 停止。数据直接写入 ~/.career-kit，与 MCP 共用。")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
