"""任务执行、洞察调整与进度产出 MCP 工具。"""

from __future__ import annotations

from datetime import datetime

from ..assets import INDEX_FILENAME, get_assets_root, profile_display_name
from ..core.progress import STAGE_EXECUTING, STAGE_EXECUTION, resolve_progress
from ..guidance import MAINTENANCE_CLOSING, guide_for, is_legacy
from ..mcp_app import mcp
from .dashboard import (
    render_progress_html as _render_progress_html,
    render_roadmap_map as _render_roadmap_map,
    write_html as _write_html,
)
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import get_active_profile_name, load_profile, save_profile
from .resource_catalog import select_resources, validate_resources
from .session_tools import _has_goal, _summarize_dict
from .tool_helpers import _json, _parse_json_param

_FINISHED_TASK_STATUSES = ("completed", "skipped")


def _sync_failure_warning(label: str, exc: Exception) -> str:
    """sync 失败不阻断主工具，但要在返回内容里留痕，方便排查。"""
    return f"Core v2 同步失败（{label}）：{exc}"


BASELINE_EXECUTION_NOTE = (
    "已按基线执行，企业适配已记录跳过；后续可随时补企业适配"
    "（select_target_companies → collect_company_evidence → analyze_company_requirements → "
    "save_requirement_profile → plan_execution_alignment → save_execution_alignment）。"
)


def _mark_enterprise_alignment_skipped(profile) -> bool:
    """企业适配未完成但用户选择先按基线执行时，写入可审计的跳过事实。

    只在状态机尚未进入执行阶段时记录；已经进入执行链路不重复改写时间戳。
    """
    progress = resolve_progress(profile)
    if str(progress.get("stage") or "") in (STAGE_EXECUTION, STAGE_EXECUTING):
        return False
    guidance = dict(getattr(profile, "guidance", None) or {})
    guidance["enterprise_alignment_skipped_at"] = datetime.now().isoformat()
    profile.guidance = guidance
    save_profile(profile)
    return True


def _roadmap_phase_id(phase: dict, index: int) -> str:
    return str(phase.get("id") or f"phase_{index + 1}")


def _expected_task_keys(profile, phase: dict, phase_id: str) -> list[tuple[str, str]]:
    """列出该阶段应生成的任务身份（milestone_id, name），口径与任务重建一致。"""
    current_detail = profile.plan.get("current_detail") or {}
    detail_phase_id = str(current_detail.get("phase_id") or "")
    detail_tasks = [
        item
        for item in (current_detail.get("tasks") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if detail_phase_id == phase_id and detail_tasks:
        return [
            (str(item.get("milestone_id") or ""), str(item["name"]).strip())
            for item in detail_tasks
        ]

    keys: list[tuple[str, str]] = []
    for ms_index, milestone in enumerate(phase.get("milestones") or []):
        if not isinstance(milestone, dict):
            continue
        milestone_id = str(milestone.get("id") or f"{phase_id}_ms_{ms_index + 1}")
        valid = [
            item
            for item in (milestone.get("tasks") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        if valid:
            keys.extend((milestone_id, str(item["name"]).strip()) for item in valid)
        else:
            keys.append((milestone_id, str(milestone.get("name") or f"里程碑 {ms_index + 1}")))
    return keys


def _next_phase_to_generate(profile, phases: list[dict]) -> str:
    """按路线图顺序找要生成任务的阶段。

    与 resolve_current_phase 的差别：执行版路线图复用 phase_id 时，历史
    completed/skipped 任务会让整段看起来「已完成」；这里把路线图里尚未生成的
    任务定义也算作未完成，避免新执行版第一阶段被跳过。
    """
    phase_ids = [_roadmap_phase_id(phase, index) for index, phase in enumerate(phases)]
    tasks_by_phase: dict[str, list] = {phase_id: [] for phase_id in phase_ids}
    for task in profile.tasks:
        if task.phase_id in tasks_by_phase:
            tasks_by_phase[task.phase_id].append(task)

    for phase_id in phase_ids:
        if any(task.status not in _FINISHED_TASK_STATUSES for task in tasks_by_phase[phase_id]):
            return phase_id

    for phase_id, phase in zip(phase_ids, phases, strict=True):
        generated = {(task.milestone_id, task.name) for task in tasks_by_phase[phase_id]}
        if any(key not in generated for key in _expected_task_keys(profile, phase, phase_id)):
            return phase_id

    for phase_id in phase_ids:
        if not tasks_by_phase[phase_id]:
            return phase_id
    return ""


@mcp.tool()
def generate_tasks() -> str:
    """从路线图生成当前阶段的任务列表。

    何时调用：在 save_roadmap 之后调用，将路线图转化为可执行的任务。
    前置条件：档案中已有路线图（plan.roadmap）。
    后续步骤：调用 get_next_tasks 查看当前阶段的下一步任务。

    只生成当前阶段（第一个有未完成任务的阶段；全部完成后取下一个尚未
    生成任务的阶段），后续阶段保留里程碑形态，避免出现一大堆空壳任务。
    重建按「阶段 + 里程碑 + 任务名」复用旧任务 ID 与打卡进度。
    """
    from .task_manager import (
        create_tasks_from_roadmap,
        format_task_list,
        record_capability_evidence,
    )

    profile = load_profile()

    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    if not phases:
        return error_response(
            "MISSING_DATA",
            "档案中没有路线图，请先调用 generate_roadmap。",
            {"section": "plan"},
        )

    baseline_skipped = _mark_enterprise_alignment_skipped(profile)
    skip_note = f"{BASELINE_EXECUTION_NOTE}\n" if baseline_skipped else ""

    phase_rows = [phase for phase in phases if isinstance(phase, dict)]
    phase_ids = [_roadmap_phase_id(phase, index) for index, phase in enumerate(phase_rows)]
    target_phase_id = _next_phase_to_generate(profile, phase_rows)

    if not target_phase_id:
        return _json({
            "message": (
                f"{skip_note}"
                "所有阶段的任务都已生成并完成——没有新的当前阶段可生成。\n"
                f"{MAINTENANCE_CLOSING}\n\n"
                f"{guide_for(profile)}"
            ),
            "next_steps": ["get_progress", "get_weekly_review"],
            "context": {
                "phase": "all_phases_generated",
                "task_count": 0,
                "enterprise_alignment_skipped": baseline_skipped,
            },
        })

    target_phase = next(
        (
            phase
            for index, phase in enumerate(phase_rows)
            if _roadmap_phase_id(phase, index) == target_phase_id
        ),
        {},
    )
    target_name = target_phase.get("name") or target_phase_id

    # 同一任务（phase + milestone + name）复用旧 ID 与打卡进度；
    # 只替换当前阶段，其他阶段（含已完成阶段）原样保留。
    old_tasks = list(profile.tasks)
    kept_other = [
        t for t in old_tasks
        if t.phase_id != target_phase_id and t.phase_id in phase_ids
    ]
    tasks = create_tasks_from_roadmap(profile, only_phase_ids={target_phase_id})
    new_ids = {t.id for t in tasks}
    # 历史 completed/skipped 任务是用户真实完成过的证据：不论其 phase_id 是否
    # 还在新路线图里（应用执行版可能删除整个阶段），都必须完整保留。
    kept_finished = [
        t for t in old_tasks
        if t.status in _FINISHED_TASK_STATUSES and t.id not in new_ids
    ]

    profile.tasks = []
    kept_ids: set[str] = set()
    for task in kept_other + kept_finished:
        if task.id in kept_ids:
            continue
        kept_ids.add(task.id)
        profile.add_task(task)
    for task in tasks:
        profile.add_task(task)

    final_ids = {t.id for t in profile.tasks}
    preserved = sum(
        1 for t in old_tasks
        if t.id in final_ids and t.status in ("completed", "skipped", "in_progress")
    )

    # 重建时保留的 completed 任务沉淀为能力证据；record_capability_evidence
    # 按 task + completed_at 去重，重复调用不会重复追加。
    for task in profile.tasks:
        if task.status == "completed":
            record_capability_evidence(profile, task)

    save_profile(profile)

    # Core v2 同步：任务/打卡状态落 ExecutionState artifact（失败不阻断，但要留痕）
    sync_warning = ""
    try:
        from ..core.sync import sync_execution_state

        sync_execution_state(get_active_profile_name())
    except Exception as exc:  # noqa: BLE001 - sync 失败不阻断主工具
        sync_warning = _sync_failure_warning("sync_execution_state", exc)

    # 任务生成后自动刷新路线图 HTML：避免用户打开旧快照看到「没有可打卡任务」（P1-4）
    map_path = ""
    map_error = ""
    try:
        map_html = _render_roadmap_map(profile)
        map_path = _write_html(map_html, kind="roadmap")
    except Exception as exc:  # noqa: BLE001 - 交付失败如实告知
        map_error = str(exc)

    migrated_note = (
        f"已保留 {preserved} 个任务的打卡状态。\n" if preserved else ""
    )
    map_note = (
        f"路线图 HTML 已同步刷新，现在可以打卡：{map_path}\n"
        if map_path
        else f"路线图 HTML 刷新失败：{map_error}——可稍后用 export_dashboard(mode=\"roadmap\") 重试。\n"
    )
    sync_note = f"{sync_warning}\n" if sync_warning else ""
    return _json({
        "message": (
            f"{skip_note}"
            f"{migrated_note}已为当前阶段「{target_name}」生成 {len(tasks)} 个任务"
            "（后续阶段保留里程碑，不生成空壳任务）。\n"
            f"{map_note}{sync_note}"
            "下一步：调用 get_next_tasks 查看执行任务；"
            "或调用 detail_current_phase 生成当前阶段的详细路线（含按天/按比例打卡点）。\n\n"
            f"{guide_for(profile)}"
        ),
        "tasks": format_task_list(tasks, "当前阶段任务"),
        "next_steps": ["get_next_tasks", "detail_current_phase"],
        "context": {
            "phase": "tasks_generated",
            "phase_id": target_phase_id,
            "phase_name": target_name,
            "task_count": len(tasks),
            "enterprise_alignment_skipped": baseline_skipped,
            **({"sync_warning": sync_warning} if sync_warning else {}),
        },
    })


@mcp.tool()
def detail_current_phase() -> str:
    """生成当前阶段的详细路线（执行期细化）。

    何时调用：用户想进入执行、需要把当前阶段拆成可打卡的颗粒度时调用。
    只细化当前阶段（第一个有未完成任务的阶段），不生成后续阶段。

    返回方法论上下文。LLM 按照 detailed_route 方法论指引，结合真实岗位数据
    （fetch_company_jobs / fetch_jd_detail）设计当前阶段的打卡任务，
    然后调用 save_current_detail(detail_json) 保存。

    前置条件：路线图已保存（save_roadmap）。任务尚未生成时以第一段为当前阶段。
    后续步骤：LLM 设计后调用 save_current_detail，再 generate_tasks 生成/合并任务。
    """
    from .task_manager import resolve_current_phase

    profile = load_profile()

    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    if not phases:
        return error_response(
            "MISSING_DATA",
            "档案里还没有路线图——先 generate_roadmap → save_roadmap，再细化当前阶段。",
            {"missing": "plan.roadmap"},
        )

    baseline_skipped = _mark_enterprise_alignment_skipped(profile)
    skip_note = f"{BASELINE_EXECUTION_NOTE}\n" if baseline_skipped else ""

    current = resolve_current_phase(profile)
    if current is None:
        return (
            f"{skip_note}所有阶段的任务都已完成。\n{MAINTENANCE_CLOSING}"
        )
    view = {
        "phase_id": current["phase_id"],
        "phase_name": current["phase_name"],
        "next_tasks": current["open_tasks"][:5],
        "done": current["done"],
        "total": current["total"],
    }

    # 当前阶段的路线图信息
    phase = next((p for p in phases if p.get("id") == view["phase_id"]), None) or {}

    ctx = build_methodology_context("detailed_route", profile, compact=True)

    phase_text = f"{view['phase_name']} {phase.get('goal', '')}"
    priority_tags: list[str] = []
    phase_type = str(phase.get("type") or "")
    if phase_type in ("project", "intern"):
        priority_tags += ["open-source", "collaboration"]
    if phase_type == "intern":
        priority_tags += ["application", "interview"]
    if "前端" in phase_text or "react" in phase_text.lower():
        priority_tags += ["frontend"]
    if "后端" in phase_text or "agent" in phase_text.lower():
        priority_tags += ["backend", "python"]
    resource_tags = ["algorithm", "八股"] + priority_tags

    return _json({
        "methodology": ctx["methodology"],
        "profile": ctx["profile"],
        "resource_catalog": select_resources(
            resource_tags, limit=14, priority_tags=priority_tags
        ),
        "baseline_execution_note": BASELINE_EXECUTION_NOTE if baseline_skipped else "",
        "enterprise_alignment_skipped": baseline_skipped,
        "current_phase": {
            "phase_id": view["phase_id"],
            "phase_name": view["phase_name"],
            "goal": phase.get("goal", ""),
            "company": phase.get("company", ""),
            "kpi": phase.get("kpi", {}),
            "milestones": phase.get("milestones", []),
            "jd_status": phase.get("jd_status", "not_required"),
        },
        "instructions": (
            "请按照 detailed_route 方法论，只细化当前阶段「{phase_name}」：\n"
            "1. 若该阶段是 intern（实习）且有目标公司，先用 fetch_company_jobs / fetch_jd_detail "
            "抓真实岗位数据，把要求细节细化到任务描述，不停留在占位\n"
            "2. 每个任务必须带执行 playbook：\n"
            "   - how_to：3-5 条具体做法（先想什么、怎么写、错了怎么办）\n"
            "   - resources：从下面 resource_catalog 选，字段为 label + url；"
            "没有收录时用 label + search 兜底，禁止编造 URL\n"
            "   - done_criteria：怎么算完成（可验证，不是「刷了题」）\n"
            "   - checkin_mode（once/daily/percent）与 checkin_goal（daily=天数，percent=比例）\n"
            "3. 任务 5-15 个，粒度「一次坐下来可完成」；不要把一个里程碑原样当任务\n"
            "4. 调用 save_current_detail(detail_json) 保存，然后重新 generate_tasks 合并打卡点；"
            "向用户展示时直接给资源链接和做法，不要只说「去刷题」"
        ).format(phase_name=view["phase_name"]),
    })


@mcp.tool()
def save_current_detail(detail_json: str) -> str:
    """保存当前阶段的详细路线。

    Args:
        detail_json: 详细路线的 JSON 字符串

    Schema（与 sop/detailed_route.yaml 一致）:
        {
            "phase_id": "phase_1",
            "tasks": [
                {
                    "name": "LeetCode 热题 100：数组与字符串 5 题",
                    "description": "...",
                    "how_to": ["先想 10 分钟", "再写代码", "错题隔天重做"],
                    "resources": [
                        {"label": "LeetCode 热题 100",
                         "url": "https://leetcode.cn/problem-list/2cktkvj/"}
                    ],
                    "done_criteria": "独立写出 5 题并通过，错题已记录",
                    "priority": "high",
                    "checkin_mode": "daily",
                    "checkin_goal": 5
                }
            ]
        }
    """
    try:
        detail = _parse_json_param(detail_json, "当前阶段详细路线")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    # 执行 playbook 质量建议（不阻断保存）：任务要能独立执行，而不是只有标题
    advisories: list[str] = []
    for i, task in enumerate(detail.get("tasks") or [], 1):
        if not isinstance(task, dict):
            advisories.append(f"tasks[{i}] 不是对象，已按原样保存")
            continue
        name = str(task.get("name") or f"任务 {i}")
        if not task.get("name"):
            advisories.append(f"tasks[{i}] 缺 name，生成任务时会被丢弃")
        if not task.get("how_to"):
            advisories.append(f"「{name}」缺 how_to（怎么做）")
        if not task.get("done_criteria"):
            advisories.append(f"「{name}」缺 done_criteria（怎么算完成）")
        mode = str(task.get("checkin_mode") or "once")
        goal = float(task.get("checkin_goal") or 0)
        if mode not in ("once", "daily", "percent"):
            advisories.append(f"「{name}」checkin_mode「{mode}」无效，应为 once/daily/percent")
        elif mode == "daily" and goal < 1:
            advisories.append(f"「{name}」daily 需要 checkin_goal >= 1（目标天数）")
        elif mode == "percent" and not (0 < goal <= 100):
            advisories.append(f"「{name}」percent 需要 0 < checkin_goal <= 100")
        for warning in validate_resources(task.get("resources") or []):
            advisories.append(f"「{name}」{warning}")

    profile = load_profile()
    roadmap = profile.plan.get("roadmap", profile.plan) if isinstance(profile.plan, dict) else {}
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    phase_ids = [
        p.get("id") or f"phase_{i + 1}" for i, p in enumerate(phases) if isinstance(p, dict)
    ]
    target_phase = str(detail.get("phase_id") or "").strip()
    if not target_phase:
        return error_response(
            "INVALID_PARAM",
            "detail_json 缺 phase_id——详细路线必须指明所属阶段（如 phase_1）。",
            {
                "existing_phase_ids": phase_ids,
                "hint": "phase_id 取 detail_current_phase 返回的当前阶段 id",
            },
        )
    if not phase_ids:
        return error_response(
            "MISSING_DATA",
            "档案里还没有路线图——没有阶段可挂详细路线，先 generate_roadmap → save_roadmap。",
            {
                "hint": (
                    "先生成并保存路线图，再对具体阶段调用 detail_current_phase / "
                    "save_current_detail"
                ),
            },
        )
    if target_phase not in phase_ids:
        return error_response(
            "MISSING_DATA",
            f"phase_id「{target_phase}」不在当前路线图里——没有对应规划却保存详细路线"
            "会产生孤儿 detail（随后 generate_tasks 会报「没有路线图」）。",
            {
                "existing_phase_ids": phase_ids,
                "hint": "改用列表中存在的 phase_id；如需新阶段先 save_roadmap 更新路线图",
            },
        )

    profile.plan.setdefault("current_detail", {})
    profile.plan["current_detail"] = detail
    profile.touch()
    save_profile(profile)

    tasks_n = len(detail.get("tasks", []))
    advisory_text = ""
    if advisories:
        advisory_text = "\n\n执行 playbook 建议（不阻断保存，请按需补齐）：\n" + "\n".join(
            f"- {a}" for a in advisories
        )
    return _json({
        "message": (
            f"当前阶段详细路线已保存（{tasks_n} 个任务）。{advisory_text}\n\n"
            "请重新调用 generate_tasks，将 playbook（how_to/resources/done_criteria）"
            "与打卡点（checkin_mode/checkin_goal）合并进任务列表，"
            "然后用 get_next_tasks 开始执行。"
        ),
        "next_steps": ["generate_tasks"],
        "context": {
            "phase": "detail_saved",
            "task_count": tasks_n,
            "advisories": advisories,
        },
    })


@mcp.tool()
def get_next_tasks() -> str:
    """获取当前阶段的下一步任务。

    何时调用：用户想知道「现在该做什么」时调用。
    返回当前阶段（第一个有未完成任务的阶段）的接下来几个任务和阶段进度。
    产品不规划时间——顺序归产品，时间归用户。
    """
    from .task_manager import (
        current_phase_view,
        format_progress_overview,
        format_task_playbook,
    )

    profile = load_profile()

    if not profile.tasks:
        return _json({
            "message": "暂无任务。建议先 detail_current_phase 细化当前阶段，再 generate_tasks；"
                       "不想细化也可直接生成粗任务。",
            "next_steps": ["detail_current_phase", "generate_tasks"],
            "context": {"phase": "no_tasks"},
        })

    view = current_phase_view(profile)

    lines = []

    # 全流程概览（BUG-016）：所有阶段 + 完成状态 + 当前定位，让用户有全局地图
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    if phases:
        overview = []
        for idx, phase in enumerate(phases):
            phase_id = phase.get("id") or f"phase_{idx + 1}"
            phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
            done = sum(
                1 for t in phase_tasks
                if t.status in ("completed", "skipped")
            )
            total = len(phase_tasks)
            pct = int(done / total * 100) if total else 0
            marker = "[当前]" if view and view["phase_id"] == phase_id else ("" if done == total else "·")
            overview.append(f"{marker} {phase.get('name', phase_id)}（{done}/{total}，{pct}%）")
        lines.append("## 全流程")
        lines.append("\n".join(f"  {o}" for o in overview))
        lines.append("")

    if view is None:
        lines.append("所有阶段已完成！")
        lines.append(MAINTENANCE_CLOSING)
    elif view["total"] == 0:
        lines.append(f"## 当前阶段：{view['phase_name']}（任务尚未生成）")
        lines.append("")
        lines.append("下一步：调用 generate_tasks 为这个阶段生成任务，再开始执行。")
    else:
        pct = int(view["done"] / view["total"] * 100) if view["total"] else 0
        lines.append(f"## 当前阶段：{view['phase_name']}（{view['done']}/{view['total']}，{pct}%）")
        lines.append("")
        lines.append("### 接下来做")
        for t in view["next_tasks"]:
            icon = {"high": "[高]", "medium": "[中]", "low": "[低]"}.get(t.priority, "[中]")
            status_mark = "[进行中]" if t.status == "in_progress" else icon
            desc = f"—{t.description}" if t.description else ""
            lines.append(f"- {status_mark} **{t.name}** (ID: {t.id}){desc}")
            lines += format_task_playbook(t)
        lines.append("")

    lines.append(format_progress_overview(profile))
    lines.append("---")
    lines.append("下一步：完成任务后调用 checkin_task 打卡。")
    lines.append("节奏由用户掌握：快了可以加深或推进下一项，慢了随时调整顺序。")
    lines.append("已投递的公司可用 record_application 登记，周检视会带出求职漏斗。")

    return "\n".join(lines)


@mcp.tool()
def checkin_task(task_id: str, status: str = "completed", notes: str = "", amount: float = 0) -> str:
    """打卡任务。

    何时调用：用户完成或跳过某个任务时调用。
    完成的任务会沉淀为能力证据写入档案。

    Args:
        task_id: 任务 ID（从 get_next_tasks 获取）
        status: 打卡状态（completed 或 skipped）
        notes: 备注（可选）
        amount: 打卡进度（可选）——daily 传 1 表示今天打卡（同日幂等），
            传 >1 表示目标天数；percent 传目标百分比（绝对值，如 60 表示 60%）
    """
    from .insight import completed_phase_ids
    from .task_manager import (
        checkin_task as do_checkin,
        format_progress_overview,
        record_capability_evidence,
    )

    allowed_statuses = ("completed", "skipped")
    if status not in allowed_statuses:
        return error_response(
            "INVALID_PARAM",
            f"status 必须是 completed 或 skipped，收到的是「{status}」",
            {"received": status, "allowed": list(allowed_statuses)},
        )

    profile = load_profile()

    try:
        profile, checkin = do_checkin(profile, task_id, status, notes, amount)
    except ValueError as e:
        return error_response("MISSING_DATA", str(e), {"task_id": task_id})

    task = profile.get_task(task_id)

    # 能力证据沉淀：只有任务真正完成才写，部分打卡不污染证据
    if task and task.status == "completed":
        record_capability_evidence(profile, task, notes)

    # 阶段完成检测（排除已审计过的阶段）
    newly_completed = [pid for pid in completed_phase_ids(profile) if pid not in profile.audited_phases]

    # 阶段 id → 用户可读的阶段名（提示里不能露 phase_1 这种内部 id）
    _roadmap_phases = profile.plan.get("roadmap", profile.plan).get("phases", [])
    _phase_names = {p.get("id"): p.get("name", p.get("id")) for p in _roadmap_phases}

    lines = []
    lines.append(f"已打卡：{task.name if task else task_id}")
    if status == "skipped":
        lines[0] = f"已跳过：{task.name if task else task_id}"
    lines.append("")

    # 打卡点进度提示（BUG-004）：daily/percent 未完成时展示累计进度
    if status == "completed" and task and task.status != "completed":
        mode = task.checkin_mode or "once"
        if mode == "daily":
            lines.append(
                f"今日已打卡（累计 {int(task.checkin_progress)}/{int(task.checkin_goal)} 天）——"
                "达到目标天数即完成本任务。"
            )
            lines.append("")
        elif mode == "percent":
            lines.append(
                f"进度更新至 {task.checkin_progress:.0f}%（目标 {task.checkin_goal:.0f}%）——"
                "达到目标比例即完成本任务。"
            )
            lines.append("")

    if newly_completed:
        _name = _phase_names.get(newly_completed[0], newly_completed[0])
        lines.append(f"恭喜！你完成了阶段「{_name}」的全部任务。")
        lines.append("建议调用 trigger_insight(trigger_type=\"stage_audit\") 进行阶段审计。")
        lines.append("")

    if status == "completed" and task and task.status == "completed":
        lines.append("如果完成得轻松，可以考虑加深难度或直接推进下一项——由你和用户在对话中决定。")

    save_profile(profile)

    # Core v2 同步：打卡后刷新 ExecutionState artifact（失败不阻断，但要留痕）
    try:
        from ..core.sync import sync_execution_state

        sync_execution_state(get_active_profile_name())
    except Exception as exc:  # noqa: BLE001 - sync 失败不阻断主工具
        lines.append("")
        lines.append(_sync_failure_warning("sync_execution_state", exc))

    lines.append("")
    lines.append(format_progress_overview(profile))

    return "\n".join(lines)


@mcp.tool()
def trigger_insight(trigger_type: str = "stage_audit", event_description: str = "") -> str:
    """触发洞察检查。

    何时调用：
    - 用户完成阶段后（trigger_type="stage_audit"）
    - 用户报告事件时（trigger_type="event"，如拿到面试、目标变更）

    工作流程：
    1. 调用 trigger_insight 获取分析 prompt
    2. LLM 根据 prompt 分析用户进度
    3. LLM 生成洞察 JSON
    4. 调用 apply_insight(insight_json) 应用结果

    Args:
        trigger_type: 触发类型（stage_audit / event）
        event_description: 事件描述（当 trigger_type 为 event 时必填）

    Returns:
        包含分析 prompt 和使用说明的字典
    """
    from .insight import VALID_TRIGGER_TYPES, build_insight_prompt

    if trigger_type not in VALID_TRIGGER_TYPES:
        return error_response(
            "INVALID_PARAM",
            f"trigger_type 必须是 stage_audit/event，收到的是「{trigger_type}」",
            {"received": trigger_type, "allowed": list(VALID_TRIGGER_TYPES)},
        )

    profile = load_profile()

    if not profile.tasks and trigger_type == "stage_audit":
        return _json({
            "message": "暂无任务。建议先 detail_current_phase 细化当前阶段，再 generate_tasks。",
            "next_steps": ["detail_current_phase", "generate_tasks"],
            "context": {"phase": "no_tasks"},
        })
    # event 型不需要任务存在：面试/offer 等事件可能发生在建任务之前，
    # 漏斗链接（record_application 软提示）也会引导到这里，不能拒绝。

    # 构建 prompt
    prompt = build_insight_prompt(profile, trigger_type, event_description)

    return _json({
        "message": "洞察分析任务已准备。请根据以下 prompt 进行分析，然后调用 apply_insight 应用结果。",
        "prompt": prompt,
        "output_format": {
            "trigger_type": trigger_type,
            "status": "on_track|behind|ahead|need_adjustment",
            "summary": "进度总结",
            "insights": ["洞察1", "洞察2"],
            "adjustment_needed": True,
            "adjustment_reason": "调整原因",
            "changes": [{"type": "add_task|remove_task|modify_task", "task_id": "task_001", "details": {}}],
            "user_message": "给用户的消息"
        },
        "next_steps": ["apply_insight"],
        "context": {"phase": "insight_ready", "trigger_type": trigger_type},
    })


@mcp.tool()
def apply_insight(insight_json: str) -> str:
    """应用洞察分析结果到档案。

    何时调用：在 trigger_insight 之后，LLM 分析完成后调用。

    Args:
        insight_json: LLM 返回的洞察分析 JSON

    Schema:
        {
            "trigger_type": "stage_audit",  // 回传触发类型：stage_audit/event
            "status": "on_track",        // 状态：on_track/behind/ahead/need_adjustment
            "summary": "进度正常",        // 进度总结
            "insights": [                // 洞察列表
                "学习速度超预期",
                "可以加深难度"
            ],
            "adjustment_needed": false,  // 是否需要调整
            "adjustment_type": "auto",   // 调整类型：auto/manual
            "adjustment_reason": "",     // 调整原因
            "changes": [                 // 调整列表（产品不规划时间，无压缩时长类调整）
                {
                    "type": "add_task",       // 类型：add_task/remove_task/modify_task
                    "task_id": "task_001",    // 任务 ID（add_task 时省略）
                    "details": {              // 详情
                        "name": "新任务名"
                    }
                }
            ],
            "user_message": "给用户的消息"
        }
    """
    from .insight import (
        apply_adjustment,
        format_insight_report,
    )

    profile = load_profile()

    try:
        insight_result = _parse_json_param(insight_json, "洞察分析")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    # stage_audit 落库：审过的 phase 写入 audited_phases，防止重复提示与「永远未审计」
    audit_note = ""
    trigger_type = str(insight_result.get("trigger_type") or "").strip()
    if trigger_type == "stage_audit":
        phase_id = _resolve_audited_phase(profile, insight_result)
        if phase_id and phase_id not in profile.audited_phases:
            profile.audited_phases.append(phase_id)
            audit_note = f"（阶段 {phase_id} 已标记为完成审计）"

    # 应用调整
    if insight_result.get("adjustment_needed"):
        profile, adjustment = apply_adjustment(profile, insight_result)
        save_profile(profile)

        return _json({
            "message": (
                "已应用调整。下一步：调用 get_progress 查看整体进度，"
                f"或 get_next_tasks 继续执行。{audit_note}"
            ),
            "next_steps": ["get_progress", "get_next_tasks"],
            "report": format_insight_report(insight_result),
            "adjustment": adjustment.model_dump(),
            "context": {"phase": "adjustment_applied", "audited_phase": phase_id if trigger_type == "stage_audit" else None},
        })
    else:
        save_profile(profile)
        return _json({
            "message": f"无需调整。下一步：调用 get_next_tasks 继续执行。{audit_note}",
            "next_steps": ["get_next_tasks"],
            "report": format_insight_report(insight_result),
            "context": {"phase": "insight_complete", "audited_phase": phase_id if trigger_type == "stage_audit" else None},
        })


def _resolve_audited_phase(profile, insight_result: dict) -> str:
    """从洞察结果/当前任务推断刚完成审计的阶段 id。"""
    roadmap = profile.plan.get("roadmap", profile.plan) if isinstance(profile.plan, dict) else {}
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    phase_ids = [p.get("id") for p in phases if isinstance(p, dict) and p.get("id")]

    reported = insight_result.get("phase_id") or insight_result.get("phase")
    if isinstance(reported, str) and reported in phase_ids:
        return reported

    # 未上报时取「已全部完成」的阶段里最新的一个（审计完成阶段是 stage_audit 的语义）
    for phase in reversed(phases):
        pid = phase.get("id") or ""
        if not pid or pid in profile.audited_phases:
            continue
        phase_tasks = [t for t in profile.tasks if t.phase_id == pid]
        if phase_tasks and all(
            t.status in ("completed", "skipped") for t in phase_tasks
        ):
            return pid
    return ""


@mcp.tool()
def get_progress() -> str:
    """获取进度概览。

    何时调用：用户想查看整体进度时调用。
    返回任务统计、打卡记录、调整历史。
    """
    from .application_tracker import (
        format_application_list,
        format_funnel_report,
    )
    from .task_manager import format_progress_overview

    profile = load_profile()

    if not profile.tasks and not profile.applications:
        return _json({
            "message": "暂无任务与投递记录。建议先 detail_current_phase 细化当前阶段，再 generate_tasks。",
            "next_steps": ["detail_current_phase", "generate_tasks"],
            "context": {"phase": "no_tasks"},
        })

    # 求职漏斗（存在投递记录时展示）
    lines = [format_progress_overview(profile)]
    if profile.applications:
        lines.append(format_funnel_report(profile))
        lines.append(format_application_list(profile, limit=10))
        lines.append("")

    # 调整历史
    if profile.adjustments:
        lines.append("## 调整历史")
        for adj in profile.adjustments[-5:]:
            lines.append(f"- {adj.timestamp[:10]}：{adj.reason}")
        lines.append("")

    all_finished = bool(profile.tasks) and all(
        t.status in _FINISHED_TASK_STATUSES for t in profile.tasks
    )
    if all_finished:
        lines.append(MAINTENANCE_CLOSING)
        lines.append("")

    lines.append("下一步：继续执行用 get_next_tasks；需要分享进度用 export_dashboard。")
    return "\n".join(lines)


@mcp.tool()
def get_weekly_review(days: int = 7) -> str:
    """周检视——周期性事实复盘（打卡/阶段/求职漏斗）。

    何时调用：
    - 用户想回顾一段时间表现（「给我做个周报/最近怎么样」）
    - 用户隔了很久回来（get_workflow_status 会提示）
    - 阶段审计前想先看事实

    原则：只陈列事实与规则化建议，不设时限、不催促。
    事件数字（如距上次打卡 N 天）是事实陈述，不是超期判定。

    Args:
        days: 回看天数（1-90，默认 7；月度复盘传 30）
    """
    if isinstance(days, bool) or not isinstance(days, int) or not (1 <= days <= 90):
        return error_response(
            "INVALID_PARAM",
            f"days 越界：必须是 1-90 的整数，收到 {days!r}（默认 7，月度复盘传 30）。",
            {"min": 1, "max": 90, "received": days if isinstance(days, (int, float, str)) else None},
        )
    from .review import format_weekly_review, summarize_period

    if not isinstance(days, int) or days < 1 or days > 90:
        days = min(max(int(days) if isinstance(days, (int, float)) else 7, 1), 90)

    profile = load_profile()

    if not profile.checkins and not profile.applications and not profile.tasks:
        return _json({
            "message": (
                "档案还没有执行或投递记录——先开始第一阶段任务（get_next_tasks），"
                "做了几步后周检视才有事实可看。"
            ),
            "next_steps": ["get_next_tasks"],
            "context": {"phase": "nothing_to_review"},
        })

    profile.last_review_at = datetime.now().isoformat()
    save_profile(profile)

    facts = summarize_period(profile, days=days)
    review = format_weekly_review(profile, facts)
    fit = _plan_fit_result("weekly_review")
    fit_lines = _plan_fit_lines(fit)
    if fit_lines:
        review = review + "\n\n" + "\n".join(fit_lines)

    # Core v2 同步：周检视事实 + 计划失配结果落 ReviewReport artifact（失败不阻断，但要留痕）
    sync_warning = ""
    try:
        from ..core.sync import sync_review

        sync_review(get_active_profile_name(), plan_fit=fit, weekly_facts=facts)
    except Exception as exc:  # noqa: BLE001 - sync 失败不阻断主工具
        sync_warning = _sync_failure_warning("sync_review", exc)

    follow_up = (
        "认可就继续 get_next_tasks；想调整随时说，"
        "或用 trigger_insight 触发一次正式审计。"
        if facts["suggestions"]
        else "数据都健康——继续 get_next_tasks 即可。"
    )

    warning_note = f"\n\n{sync_warning}" if sync_warning else ""
    return f"{review}{warning_note}\n\n下一步：{follow_up}"


def _plan_fit_result(trigger: str) -> dict:
    """只读计划失配检测；失败不拖垮状态/周检视。"""
    try:
        from ..core.plan_fit import check_plan_fit as _fit

        return _fit(get_active_profile_name(), trigger)
    except Exception:  # noqa: BLE001 - 检测失败只跳过，不影响主流程
        return {}


def _plan_fit_lines(fit: dict) -> list[str]:
    """把检测结果渲染成用户可见事实 + 建议询问话术。"""
    status = str(fit.get("status") or "").strip()
    if status in ("", "aligned", "incomplete_chain"):
        return []
    lines = ["### 计划失配检测", f"- 状态：{status}"]
    signals = fit.get("signals")
    if isinstance(signals, list):
        for item in signals:
            if not isinstance(item, dict):
                continue
            severity = str(item.get("severity") or "info")
            message = str(item.get("message") or "").strip()
            if message:
                lines.append(f"- [{severity}] {message}")
    question = str(fit.get("question_for_user") or "").strip()
    if question:
        lines.append(f"- 建议询问用户：{question}")
    next_tool = str(fit.get("next_tool") or "").strip()
    if next_tool:
        lines.append(f"- 用户同意后可调用：{next_tool}")
    return lines


def _review_nudge_hint() -> str:
    """回访提示：距上次打卡/检视较久时建议周检视（事实陈述，不催促）。"""
    from .review import days_since_last_checkin

    profile = load_profile()
    days_since = days_since_last_checkin(profile)
    if days_since is None:
        return ""  # 从未打卡：还在起步阶段，不提示

    last_review = profile.last_review_at
    try:
        review_dt = datetime.fromisoformat(last_review) if last_review else None
    except ValueError:
        review_dt = None
    now = datetime.now()
    review_stale = review_dt is None or (now - review_dt).days >= 7

    if days_since >= 7 and review_stale:
        return (
            f"距上次打卡已 {days_since} 天（事实陈述，不设时限）。"
            "建议调用 get_weekly_review 做一次周检视，看完事实再决定继续、调整或休息。"
        )
    if review_stale and days_since < 7:
        return "距上次周检视已超过 7 天，可用 get_weekly_review 快速回顾。"
    return ""


_STAGE_NAMES = (
    "职业档案构建",
    "目标岗位定位",
    "市场基线调研",
    "能力差距诊断",
    "培养方案规划",
    "目标企业筛选",
    "岗位与面经采集",
    "企业需求分析",
    "执行方案校准",
    "任务执行与打卡",
    "求职投递管理",
    "周期复盘与计划调整",
)

_STAGE_NEXT_TOOLS = (
    "finalize_profile",
    "explore_goals / intake(section=\"want\")",
    "gather_research_data",
    "analyze_gaps",
    "generate_roadmap",
    "select_target_companies",
    "collect_company_evidence",
    "analyze_company_requirements",
    "plan_execution_alignment",
    "get_next_tasks",
    "build_application_list / record_application",
    "get_weekly_review",
)

_CORE_STAGE_INDEX = {
    "profile": 1,
    "target": 2,
    "market_baseline": 3,
    "gap": 4,
    "baseline_plan": 5,
    "company_pool": 6,
    "evidence": 7,
    "requirement": 8,
    "execution_plan": 9,
    "execution": 10,
    "executing": 10,
    "applications": 11,
    "review": 12,
}


def _backfill_core_state(profile):
    """旧档案补齐：core_state 缺 key 且档案已有对应数据时补一次 sync。

    只补缺失 key，已有 key 不重建；任何 sync 失败都静默跳过，不影响状态报告。
    返回补齐后重新加载的档案（无补齐时返回原对象）。
    """
    try:
        from ..core import sync as core_sync
    except Exception:  # noqa: BLE001 - 导入失败视为无旧档案可补
        return profile

    state = profile.core_state if isinstance(profile.core_state, dict) else {}
    research = profile.research if isinstance(profile.research, dict) else {}
    plan = profile.plan if isinstance(profile.plan, dict) else {}
    roadmap = plan.get("roadmap")
    # 新流程档案（有 guidance）在 finalize 前不能补 ProfileSnapshot，
    # 否则状态报告会把「未 finalize」误判为阶段 1 已完成（BUG #12-13）。
    profile_ready = (
        bool(profile.summary)
        or is_legacy(profile)
        or not (profile.guidance or {})
    )
    # 目标确认是 TargetSpec 的唯一门禁：只有用户确认（或旧档案兜底）才允许
    # 补 TargetSpec；未确认时也不能因为已有调研数据而推进市场基线。
    goal_ready = (
        bool((profile.want or {}).get("user_confirmed"))
        or bool((profile.guidance or {}).get("goal_confirmed_at"))
        or is_legacy(profile)
    )
    checks = (
        (
            core_sync.KEY_PROFILE,
            bool(profile.who or profile.have or profile.want or profile.summary)
            and profile_ready,
            core_sync.sync_profile,
        ),
        (
            core_sync.KEY_TARGET,
            bool(profile.want) and goal_ready,
            core_sync.sync_target,
        ),
        (
            core_sync.KEY_MARKET_BASELINE,
            goal_ready
            and bool(
                research.get("report_md")
                or research.get("jd_samples")
                or research.get("cases")
            ),
            core_sync.sync_market_baseline,
        ),
        (core_sync.KEY_GAP, bool(profile.gap), core_sync.sync_gap),
        (
            core_sync.KEY_BASELINE_PLAN,
            bool(isinstance(roadmap, dict) and roadmap),
            core_sync.sync_baseline_plan,
        ),
        (core_sync.KEY_EXECUTION, bool(profile.tasks), core_sync.sync_execution_state),
        (
            core_sync.KEY_APPLICATIONS,
            bool(profile.applications),
            core_sync.sync_application_state,
        ),
    )

    changed = False
    for key, has_data, sync_fn in checks:
        if not has_data or state.get(key):
            continue
        try:
            sync_fn(get_active_profile_name())
            changed = True
        except Exception:  # noqa: BLE001 - 补齐失败不影响主流程
            continue
    return load_profile() if changed else profile


def _core_next_step_text(action: dict) -> str:
    """把状态机输出转成「下一步」单行文案，保证与 [GUIDE] 同源。"""
    tool = str((action or {}).get("next_tool") or "")
    reason = str((action or {}).get("reason") or "")
    return f"{tool}（{reason}）" if reason else tool


def _stage_position(profile, core_action: dict) -> tuple[int, str, str]:
    """根据状态机输出（缺失时回退 core_state）给出 12 阶段位置与下一步。"""
    stage = str((core_action or {}).get("stage") or "")
    index = _CORE_STAGE_INDEX.get(stage)
    next_tool = str((core_action or {}).get("next_tool") or "")

    if index is None:
        # 状态机不可用时按 core_state 指针退化推导，避免整份报告缺阶段信息
        try:
            from ..core import sync as core_sync
        except Exception:  # noqa: BLE001 - 无核心模块时按建档起点处理
            return 1, _STAGE_NAMES[0], _STAGE_NEXT_TOOLS[0]
        state = profile.core_state if isinstance(profile.core_state, dict) else {}
        # 完整 12 阶段 key：不能只遍历前 5 个再硬编码跳到执行阶段，
        # 否则投递/复盘阶段永远显示不出来。
        keys = (
            core_sync.KEY_PROFILE,
            core_sync.KEY_TARGET,
            core_sync.KEY_MARKET_BASELINE,
            core_sync.KEY_GAP,
            core_sync.KEY_BASELINE_PLAN,
            "company_pool_id",
            "evidence_run_id",
            "requirement_profile_id",
            "execution_plan_id",
            core_sync.KEY_EXECUTION,
            core_sync.KEY_APPLICATIONS,
            core_sync.KEY_REVIEW,
        )
        for position, key in enumerate(keys, start=1):
            if not state.get(key):
                return position, _STAGE_NAMES[position - 1], _STAGE_NEXT_TOOLS[position - 1]
        index = len(keys)

    if not next_tool and index == 10:
        next_tool = "get_next_tasks"
    return index, _STAGE_NAMES[index - 1], next_tool


@mcp.tool()
def get_workflow_status() -> str:
    """获取当前工作流状态和下一步建议。

    何时调用：
    - 用户开始对话时，了解当前进度
    - LLM 不确定下一步该做什么时
    - 需要查看整体状态时

    Returns:
        包含当前阶段、已完成步骤、下一步建议的字典
    """
    # 旧档案补齐：缺 key 且已有数据时补一次 sync（只补缺失，不重建）
    profile = _backfill_core_state(load_profile())

    # Core v2 状态机（只读）：12 阶段位置与企业适配建议
    core_v2: dict = {}
    try:
        from ..core.orchestrator.state_machine import next_action as _core_next

        core_v2 = _core_next(get_active_profile_name())
    except Exception:  # noqa: BLE001 - 状态推导失败不能拖垮整份状态报告
        core_v2 = {}

    # 目标变更检测（BUG-010）：want 是用户真实目标，变更要强告警；
    # target_jd 可能被示例/误导入污染，降级为「可核查提示」并附摘要，不再逼用户重分析
    goal_change_alert = ""
    plan_saved_at = profile.plan_saved_at
    if profile.plan.get("roadmap") and plan_saved_at:
        want_at = profile.section_updated_at.get("want", "")
        if want_at and want_at > plan_saved_at:
            goal_change_alert = (
                "检测到用户目标（want）在路线图生成之后发生了变更。\n"
                "旧路线图可能已不适用，建议重新调用 analyze_gaps 进行分析。\n\n"
            )
        else:
            jd_at = profile.section_updated_at.get("target_jd", "")
            if jd_at and jd_at > plan_saved_at and profile.target_jd:
                jd_summary = _summarize_dict(profile.target_jd)
                goal_change_alert = (
                    f"检测到 target_jd 在路线图之后更新（{jd_summary}）。\n"
                    "若这是真实的新目标 JD，建议重新 analyze_gaps；\n"
                    "若为误导入（如示例文本），可忽略本提示，或请 LLM 用 import_jd 覆盖为真实 JD。\n\n"
                )

    # 确定当前阶段
    phase = "not_started"
    completed_steps = []
    next_step = "start_session"

    # 换 JD 后旧分析失效（gap_stale_at）：最高优先级，强制重新分析——
    # 防止基于旧 JD 分析直接规划（用户以为已经按新 JD 分析过）
    if profile.gap and profile.gap_stale_at:
        phase = "analysis"
        next_step = "analyze_gaps（目标 JD 已更新，旧差距分析已过期，必须重新分析后才可重新规划）"

    if profile.who or profile.have or profile.want:
        phase = "profile_building"
        completed_steps.append("start_session")

        if profile.who:
            completed_steps.append("intake(who)")
        if profile.have:
            completed_steps.append("intake(have)")
        if profile.want:
            completed_steps.append("intake(want)")

        if not profile.summary:
            next_step = "finalize_profile"
        else:
            completed_steps.append("finalize_profile")

    # 换 JD 后旧分析失效（gap_stale_at）：最高优先级——常规阶段推进的
    # next_step 一律改回重新分析，防止用户跳过分析直接规划/执行
    stale_gap = bool(profile.gap and profile.gap_stale_at)
    stale_step = (
        "analyze_gaps（目标 JD 已更新，旧差距分析已过期，必须重新分析后才可重新规划）"
    )

    if profile.summary:
        phase = "analysis"
        has_research = bool((profile.research or {}).get("report_md"))
        if has_research:
            # 已完成步骤从实际产物推导，不依赖会话内事件（P1-3）
            for done in ("research_market", "gather_research_data"):
                if done not in completed_steps:
                    completed_steps.append(done)
        if stale_gap:
            next_step = stale_step
        elif not profile.gap:
            if _has_goal(profile):
                if not has_research:
                    # 调研是独立一步（软引导，不硬挡）：报告是一切分析的地基
                    phase = "research"
                    next_step = (
                        "research_market（推荐先做：真实市场是分析的地基）；"
                        "也可直接 analyze_gaps"
                    )
                else:
                    next_step = "analyze_gaps"
            else:
                next_step = "explore_goals（尚无明确目标——先用三轴定位选定方向，再 analyze_gaps）"
        else:
            completed_steps.append("analyze_gaps")

    if profile.gap:
        phase = "planning"
        if stale_gap:
            next_step = stale_step
        elif not profile.plan.get("roadmap"):
            next_step = "generate_roadmap"
        else:
            completed_steps.append("generate_roadmap")

    if profile.plan.get("roadmap"):
        phase = "execution_prep"
        if stale_gap:
            next_step = stale_step
        elif not profile.tasks:
            next_step = (
                "detail_current_phase（建议先细化当前阶段，再 generate_tasks）；"
                "不想细化也可直接 generate_tasks"
            )
        else:
            completed_steps.append("generate_tasks")

    if profile.tasks:
        phase = "execution"
        finished_status = ("completed", "skipped")
        all_finished = all(t.status in finished_status for t in profile.tasks)

        if all_finished:
            roadmap = profile.plan.get("roadmap", profile.plan)
            roadmap_phases = (
                [p for p in roadmap.get("phases", []) if isinstance(p, dict)]
                if isinstance(roadmap, dict)
                else []
            )
            pending_phase = _next_phase_to_generate(profile, roadmap_phases) if roadmap_phases else ""
            # 全部任务完成不等于「目标达成」：core_v2 可能还需要为新阶段生成任务。
            if pending_phase or core_v2.get("next_tool") == "generate_tasks":
                phase = "execution_prep"
                if pending_phase:
                    pending_name = next(
                        (
                            p.get("name") or pending_phase
                            for idx, p in enumerate(roadmap_phases)
                            if _roadmap_phase_id(p, idx) == pending_phase
                        ),
                        pending_phase,
                    )
                    next_step = (
                        f"generate_tasks（当前任务已完成，路线图还有新阶段"
                        f"「{pending_name}」待生成）"
                    )
                else:
                    next_step = "generate_tasks（core v2 需要为新阶段生成任务）"
            else:
                phase = "completed"
                next_step = "所有任务已完成——进入持续维护：继续投递、面试复盘与周期检视"
        elif stale_gap:
            next_step = stale_step
        else:
            next_step = "get_next_tasks"

    # Core v2 企业适配：路线图已存在时，按 artifact 状态给出执行前的校准路径。
    # 只做只读推导；不改变旧工作流，不自动改写档案。
    if profile.plan.get("roadmap") and core_v2.get("next_tool") and not profile.tasks and not stale_gap:
        next_step = (
            f"{core_v2['next_tool']}（企业适配：{core_v2.get('reason', '')}）"
        )

    fit = _plan_fit_result("manual") if profile.plan.get("roadmap") else {}
    # 执行中（已有任务）时，企业适配/上游采集只是可选提示，不能覆盖主下一步。
    if (
        fit.get("status") in ("major_drift", "stale_evidence")
        and fit.get("next_tool")
        and not stale_gap
        and not profile.tasks
    ):
        next_step = (
            f"{fit['next_tool']}（计划失配：{fit.get('recommended_action', '')}）"
        )

    # 唯一事实源：core_v2（resolve_progress）有结论时，**下一步**只跟它走——
    # 已有 tasks 也不能把阶段 6-9 的企业适配覆盖成 get_next_tasks。
    if core_v2.get("next_tool"):
        next_step = _core_next_step_text(core_v2)

    # 构建状态报告
    total_tasks = len(profile.tasks)
    completed_tasks = sum(1 for t in profile.tasks if t.status == "completed")
    stage_index, stage_name, stage_next = _stage_position(profile, core_v2)

    lines = [guide_for(profile), ""]
    lines.append(f"## 当前阶段（12 步）：{stage_index}/12 {stage_name}")
    if stage_next:
        lines.append(f"- 该阶段下一步：{stage_next}")
    lines.append(f"## 当前状态：{phase}（内部状态，不给用户复述）")
    lines.append(f"**当前档案**：{profile_display_name(get_active_profile_name())}")
    lines.append("")
    if goal_change_alert:
        lines.append(goal_change_alert.rstrip())
        lines.append("")
    review_nudge = _review_nudge_hint() if phase in ("execution", "execution_prep") else ""
    if review_nudge:
        lines.append(f"**回顾提示**：{review_nudge}")
        lines.append("")
    lines.append(f"**下一步**：{next_step}")
    lines.append("")
    lines.append("### 已完成步骤")
    for step in completed_steps:
        lines.append(f"-  {step}")
    lines.append("")
    lines.append("### 任务统计")
    lines.append(f"- 总计：{total_tasks} 个")
    lines.append(f"- 已完成：{completed_tasks} 个")
    lines.append("")
    research = profile.research or {}
    if research.get("report_md"):
        counts = research.get("counts") or {}
        lines.append("### 市场调研（来源真实）")
        lines.append(
            f"- 生成于 {research.get('generated_at', '')} · "
            f"岗位样本 {counts.get('jd_samples', 0)} 条 · 案例 {counts.get('cases', 0)} 条"
        )
        report_html = research.get("report_html") or research.get("report_md") or ""
        lines.append(f"- 报告：{report_html}")
        lines.append(f"- 资产总览：{research.get('index') or (get_assets_root() / INDEX_FILENAME)}")
        lines.append("")
    if profile.plan.get("roadmap") and core_v2:
        lines.append("### 企业适配（Core v2）")
        lines.append(f"- 阶段：{core_v2.get('stage', '')}")
        if core_v2.get("next_tool"):
            lines.append(f"- 下一步：{core_v2['next_tool']}（{core_v2.get('reason', '')}）")
        artifact_ids = core_v2.get("artifact_ids") or {}
        stored = [f"{key}={value}" for key, value in artifact_ids.items() if value]
        if stored:
            lines.append("- 已落库：" + "、".join(stored))
        lines.append("- 说明：企业适配推荐执行；用户选择先按基线执行时会记录跳过事实，后续可补。")
        lines.append("")
    fit_lines = _plan_fit_lines(fit)
    if fit_lines:
        lines.extend(fit_lines)
        lines.append("")
    lines.append("### 工作流指南")
    lines.append("- 建档：start_session → intake(who/have/want) → finalize_profile；无目标用 explore_goals 选方向")
    lines.append("- 调研（建议在分析前）：research_market → gather_research_data → 报告落盘 ~/CareerKit（真实 JD + 同学历经历，带来源）")
    lines.append("- 分析：explore_goals（无目标时）→ analyze_gaps（直接引用调研数据）→ save_gap_analysis")
    lines.append("- 规划：generate_roadmap（按 step_template 分步：起点判定→目标拆解→阶段序列→逐阶段细化→审计→定稿）→ save_roadmap")
    lines.append("- 企业适配（推荐；可先按基线执行并记录跳过）：select_target_companies → collect_company_evidence → analyze_company_requirements → save_requirement_profile → plan_execution_alignment → save_execution_alignment")
    lines.append("- 执行：detail_current_phase（建议先细化当前阶段）→ save_current_detail → generate_tasks → get_next_tasks → checkin_task → trigger_insight(stage_audit/event) → apply_insight")
    lines.append("- 产出：export_dashboard 生成阶段进度仪表盘")
    lines.append("- 投递：build_application_list 批量生成投递清单；投递/面试/offer 进展用 record_application 登记")
    lines.append("- 复盘：get_weekly_review 做周检视；计划失配用 check_plan_fit")
    lines.append("")
    if phase == "completed":
        lines.append(MAINTENANCE_CLOSING)
        lines.append("")
    lines.append("节奏原则：顺序归产品，时间归用户——不为任务设定时限。")

    return "\n".join(lines)


@mcp.tool()
def export_dashboard(mode: str = "progress") -> str:
    """生成自包含 HTML（双击即可在浏览器查看，无需服务器）。

    Args:
        mode: 视图模式
            - "progress"（默认）：阶段进度仪表盘——总体/阶段进度、当前任务、能力证据、调整历史
            - "roadmap"：职业地图——完整路线图（阶段/KPI/里程碑/任务/完成标准/简历价值/
              目标公司/推荐理由/JD 依据与占位徽标）+ 每阶段执行进度 + 当前阶段高亮；
              执行中随时重新生成，永远是「最新地图」

    何时调用：
    - 用户想直观查看整体进度时调用（progress）
    - 用户想要可携带的路线图全貌时调用（roadmap）；save_roadmap 定稿时也会自动生成一份
    """
    profile = load_profile()

    if mode == "roadmap":
        roadmap = profile.plan.get("roadmap", profile.plan) if isinstance(profile.plan, dict) else {}
        phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
        if not phases:
            return error_response(
                "MISSING_DATA",
                "档案里还没有路线图——没有规划却导出「职业地图」只会生成 0 阶段 0 任务的空壳，已拒绝。",
                {
                    "hint": "先走 generate_roadmap → save_roadmap 生成路线图；"
                            "查看进度可用 export_dashboard(mode=\"progress\")",
                },
            )
        html = _render_roadmap_map(profile)
        out_path = _write_html(html, kind="roadmap")
        index_hint = f"{get_assets_root() / INDEX_FILENAME}"
        return (
            f"职业地图已生成：{out_path}\n\n"
            "用浏览器打开即可查看。打卡有两种方式：\n"
            "- 推荐：运行 career-kit-serve --open，从控制台打开「职业地图」——直接写档案，刷新不丢；\n"
            "- 离线：直接双击 HTML，打卡存在浏览器 localStorage；移动目录、换浏览器或清缓存会丢，"
            "可用「下载打卡 JSON」备份，或「复制打卡指令」回传对话。\n"
            "- 顶部 tab 切换阶段；打卡后需回传时由 LLM 调用 checkin_task 同步到档案。\n"
            f"资产总览：双击 {index_hint}（调研报告/路线图/仪表盘都在里面）。\n"
            "下一步：用户回传打卡数据后调用 checkin_task 同步到档案。"
        )

    if mode != "progress":
        return error_response(
            "INVALID_PARAM",
            f"mode 必须是 progress/roadmap，收到的是「{mode}」",
            {"received": mode, "allowed": ["progress", "roadmap"]},
        )

    html = _render_progress_html(profile)
    out_path = _write_html(html, kind="progress")
    index_hint = f"{get_assets_root() / INDEX_FILENAME}"

    return (
        f"仪表盘已生成：{out_path}\n\n"
        "用浏览器打开即可查看。数据为生成时刻的快照，进度更新后可重新导出。\n"
        f"资产总览：双击 {index_hint}（调研报告/路线图/仪表盘都在里面）。\n"
        "如需日程表，请直接在对话中为用户编写 markdown/HTML 日程文档（时间由用户自己填）。\n"
        "下一步：继续执行用 get_next_tasks，更新进度后用 export_dashboard 重新导出。"
    )
