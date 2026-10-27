"""任务执行、洞察调整与进度产出 MCP 工具。"""

from __future__ import annotations

from datetime import datetime

from ..assets import INDEX_FILENAME, get_assets_root
from ..mcp_app import mcp
from .dashboard import (
    render_progress_html as _render_progress_html,
    render_roadmap_map as _render_roadmap_map,
    write_html as _write_html,
)
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import get_active_profile_name, load_profile, save_profile
from .session_tools import _has_goal, _summarize_dict
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def generate_tasks() -> str:
    """从路线图生成任务列表。

    何时调用：在 save_roadmap 之后调用，将路线图转化为可执行的任务。
    前置条件：档案中已有路线图（plan.roadmap）。
    后续步骤：调用 get_next_tasks 查看当前阶段的下一步任务。

    注意：重建会清空旧任务列表；已完成的进度会自动沉淀为能力证据写入档案，不会丢失。
    """
    from .task_manager import (
        collect_completed_evidence,
        create_tasks_from_roadmap,
        format_task_list,
    )

    profile = load_profile()

    if not profile.plan.get("roadmap") and not profile.plan.get("phases"):
        return error_response(
            "MISSING_DATA",
            "档案中没有路线图，请先调用 generate_roadmap。",
            {"section": "plan"},
        )

    # 重建前：把已完成/已跳过的进度沉淀为能力证据（目标变了，努力不白费）
    evidence = collect_completed_evidence(profile)
    if evidence:
        have_evidence = profile.have.setdefault("capability_evidence", [])
        if isinstance(have_evidence, list):
            have_evidence.extend(evidence)

    # 清空旧任务并从路线图生成
    profile.tasks = []
    tasks = create_tasks_from_roadmap(profile)

    for task in tasks:
        profile.add_task(task)

    save_profile(profile)

    migrated_note = (
        f"已将 {len(evidence)} 条历史完成记录沉淀为能力证据。\n" if evidence else ""
    )
    return _json({
        "message": (
            f"{migrated_note}已从路线图生成 {len(tasks)} 个任务。\n"
            "下一步：调用 get_next_tasks 查看当前阶段的执行任务，开始第一阶段；"
            "或调用 detail_current_phase 生成当前阶段的详细路线（含按天/按比例打卡点）。"
        ),
        "tasks": format_task_list(tasks, "生成的任务"),
        "next_steps": ["get_next_tasks", "detail_current_phase"],
        "context": {"phase": "tasks_generated", "task_count": len(tasks)},
    })


@mcp.tool()
def detail_current_phase() -> str:
    """生成当前阶段的详细路线（执行期细化）。

    何时调用：用户想进入执行、需要把当前阶段拆成可打卡的颗粒度时调用。
    只细化当前阶段（第一个有未完成任务的阶段），不生成后续阶段。

    返回方法论上下文。LLM 按照 detailed_route 方法论指引，结合真实岗位数据
    （fetch_company_jobs / fetch_jd_detail）设计当前阶段的打卡任务，
    然后调用 save_current_detail(detail_json) 保存。

    前置条件：路线图与任务已生成（generate_tasks 已调用）。
    后续步骤：LLM 设计后调用 save_current_detail，然后重新 generate_tasks 合并打卡点。
    """
    from .task_manager import current_phase_view

    profile = load_profile()

    if not profile.tasks:
        return error_response(
            "MISSING_DATA",
            "请先调用 generate_tasks 生成任务，再细化当前阶段。",
            {"missing": "tasks"},
        )

    view = current_phase_view(profile)
    if view is None:
        return (
            "所有阶段的任务都已完成——没有需要细化的当前阶段。\n"
            "建议回顾目标，规划下一步方向。"
        )

    # 当前阶段的路线图信息
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", [])
    phase = next((p for p in phases if p.get("id") == view["phase_id"]), None) or {}

    ctx = build_methodology_context("detailed_route", profile, compact=True)

    return _json({
        "methodology": ctx["methodology"],
        "profile": ctx["profile"],
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
            "2. 把里程碑任务拆成可打卡的详细任务：每个任务带 checkin_mode "
            "（once/daily/percent）与 checkin_goal（daily=天数，percent=比例）\n"
            "3. 任务 5-15 个，粒度「一次坐下来可完成」\n"
            "4. 调用 save_current_detail(detail_json) 保存，然后重新 generate_tasks 合并打卡点"
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
                    "name": "每天刷 5 题 LeetCode",
                    "description": "...",
                    "priority": "high",
                    "checkin_mode": "daily",
                    "checkin_goal": 30
                }
            ]
        }
    """
    try:
        detail = _parse_json_param(detail_json, "当前阶段详细路线")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

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
    return _json({
        "message": (
            f"当前阶段详细路线已保存（{tasks_n} 个任务）。\n"
            "请重新调用 generate_tasks，将打卡点（checkin_mode/checkin_goal）合并进任务列表，"
            "然后用 get_next_tasks 开始执行。"
        ),
        "next_steps": ["generate_tasks"],
        "context": {"phase": "detail_saved", "task_count": tasks_n},
    })


@mcp.tool()
def get_next_tasks() -> str:
    """获取当前阶段的下一步任务。

    何时调用：用户想知道「现在该做什么」时调用。
    返回当前阶段（第一个有未完成任务的阶段）的接下来几个任务和阶段进度。
    产品不规划时间——顺序归产品，时间归用户。
    """
    from .task_manager import current_phase_view, format_progress_overview

    profile = load_profile()

    if not profile.tasks:
        return _json({
            "message": "暂无任务。请先调用 generate_tasks 从路线图生成任务。",
            "next_steps": ["generate_tasks"],
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
        lines.append("所有阶段已完成！建议回顾目标，规划下一步方向。")
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
        amount: 本次打卡量（可选）——daily 打卡传 1（当天完成），
            percent 打卡传本次完成比例（如完成 20% 传 20）
    """
    from .insight import completed_phase_ids
    from .task_manager import (
        checkin_task as do_checkin,
        format_progress_overview,
        record_capability_evidence,
    )

    profile = load_profile()

    try:
        profile, checkin = do_checkin(profile, task_id, status, notes, amount)
    except ValueError as e:
        return error_response("MISSING_DATA", str(e), {"task_id": task_id})

    task = profile.get_task(task_id)

    # 能力证据沉淀
    if status == "completed" and task:
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
            "INVALID_SECTION",
            f"trigger_type 必须是 stage_audit/event，收到的是「{trigger_type}」",
            {"received": trigger_type, "valid": list(VALID_TRIGGER_TYPES)},
        )

    profile = load_profile()

    if not profile.tasks and trigger_type == "stage_audit":
        return _json({
            "message": "暂无任务，请先调用 generate_tasks。",
            "next_steps": ["generate_tasks"],
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
            "message": "暂无任务与投递记录。请先调用 generate_tasks 从路线图生成任务。",
            "next_steps": ["generate_tasks"],
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

    follow_up = (
        "认可就继续 get_next_tasks；想调整随时说，"
        "或用 trigger_insight 触发一次正式审计。"
        if facts["suggestions"]
        else "数据都健康——继续 get_next_tasks 即可。"
    )

    return f"{review}\n\n下一步：{follow_up}"


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
    profile = load_profile()

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
        if stale_gap:
            next_step = stale_step
        elif not profile.gap:
            if _has_goal(profile):
                if not (profile.research or {}).get("report_md"):
                    # 调研是独立一步（软引导，不硬挡）：报告是一切分析的地基
                    phase = "research"
                    next_step = (
                        "research_market（推荐先做：真实市场是分析的地基，约半分钟）；"
                        "也可直接 analyze_gaps"
                    )
                else:
                    completed_steps.append("research_market")
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
            next_step = "generate_tasks"
        else:
            completed_steps.append("generate_tasks")

    if profile.tasks:
        phase = "execution"
        finished_status = ("completed", "skipped")
        all_finished = all(t.status in finished_status for t in profile.tasks)

        if all_finished:
            phase = "completed"
            next_step = "目标达成！可回顾目标，规划下一步。"
        elif stale_gap:
            next_step = stale_step
        else:
            next_step = "get_next_tasks"

    # 构建状态报告
    total_tasks = len(profile.tasks)
    completed_tasks = sum(1 for t in profile.tasks if t.status == "completed")

    lines = []
    lines.append(f"## 当前状态：{phase}")
    lines.append(f"**当前档案**：{get_active_profile_name()}")
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
    lines.append("### 工作流指南")
    lines.append("- 建档：start_session → intake(who/have/want) → finalize_profile；无目标用 explore_goals 选方向")
    lines.append("- 调研（建议在分析前）：research_market → gather_research_data → 报告落盘 ~/CareerKit（真实 JD + 同学历经历，带来源）")
    lines.append("- 分析：explore_goals（无目标时）→ analyze_gaps（直接引用调研数据）→ save_gap_analysis")
    lines.append("- 规划：generate_roadmap（按 step_template 分步：起点判定→目标拆解→阶段序列→逐阶段细化→审计→定稿）→ save_roadmap → generate_tasks")
    lines.append("- 执行：generate_tasks → detail_current_phase（可选，按当前阶段细化打卡点）→ get_next_tasks → checkin_task → trigger_insight(stage_audit/event) → apply_insight")
    lines.append("- 产出：export_dashboard 生成阶段进度仪表盘")
    lines.append("- 复盘：get_weekly_review 做周检视；投递/面试/offer 进展用 record_application 登记")
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
            "用浏览器打开即可查看。这是一个可交互打卡应用：\n"
            "- 勾选任务即打卡，进度实时更新，状态保存在浏览器（localStorage）\n"
            "- 顶部 tab 切换阶段；「导出打卡数据」可复制打卡指令回传，由你同步到档案\n"
            "重新生成时已打卡记录不会丢失。\n"
            f"资产总览：双击 {index_hint}（调研报告/路线图/仪表盘都在里面）。\n"
            "下一步：用户回传打卡数据后调用 checkin_task 同步到档案。"
        )

    if mode != "progress":
        return error_response(
            "INVALID_MODE",
            f"mode 必须是 progress/roadmap，收到的是「{mode}」",
            {"received": mode, "valid": ["progress", "roadmap"]},
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
