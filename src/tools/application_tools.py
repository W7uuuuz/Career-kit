"""求职漏斗 MCP 工具——投递记录的写入与状态流转。"""

from __future__ import annotations

from ..mcp_app import mcp
from .application_tracker import (
    _STATUS_LABELS,
    VALID_STATUSES,
    add_application,
    application_summary,
    find_active_duplicate,
    format_funnel_report,
    funnel_stats,
    update_application_status,
)
from .errors import error_response
from .profile import get_active_profile_name, load_profile, save_profile
from .tool_helpers import _json


@mcp.tool()
def record_application(
    company: str = "",
    role: str = "",
    status: str = "applied",
    channel: str = "",
    source: str = "",
    notes: str = "",
    application_id: str = "",
    allow_duplicate: bool = False,
) -> str:
    """记录或更新求职投递进展（求职漏斗）。

    何时调用：
    - 用户报告「投了某家公司」→ 不传 application_id 新建记录（company 必填）
    - 用户报告进展变动（进面试/挂了/拿 offer）→ 传 application_id 更新状态（company 可省略）

    数据纪律：
    - 只记录用户口述的真实事实，禁止编造投递记录或代替用户「估计」状态
    - 同公司+同岗位且有活跃（未拒绝/未撤回）记录时拒绝重复新建，
      需更新请传返回值中的 application_id
    - 转化率基于事件历史，「面试后被拒」仍计入面试数

    Args:
        company: 公司名称（新建时必填；更新时可省略，与记录不符时以记录为准）
        role: 岗位名称
        status: 当前状态（applied/screening/interview/offer/rejected/withdrawn）
        channel: 投递渠道（boss/官网/内推/其他）
        source: JD 来源（URL 或文件名，可选）
        notes: 备注（可选，如面试反馈、拒信原因）
        application_id: 更新目标（app_NNN）；为空时新建记录
    """
    if status not in VALID_STATUSES:
        return error_response(
            "INVALID_PARAM",
            f"非法状态「{status}」，必须是 {sorted(VALID_STATUSES)} 之一",
            {"received": status, "allowed": sorted(VALID_STATUSES)},
        )

    profile = load_profile()
    company_mismatch_note = ""
    changed = False

    if application_id:
        app = profile.get_application(application_id)
        if not app:
            return error_response(
                "MISSING_DATA",
                f"投递记录 {application_id} 不存在。完整清单见 get_progress。",
                {"application_id": application_id, "total": len(profile.applications)},
            )
        if company.strip() and company.strip() != app.company:
            company_mismatch_note = (
                f"（入参 company「{company.strip()}」与记录「{app.company}」不符，"
                "已按记录为准；若确属另一次投递请不传 application_id）"
            )
        changed = update_application_status(profile, app, status, notes)
        if not changed:
            msg = f"{app.company}·{app.role or '该岗位'} 当前已是「{_STATUS_LABELS[status]}」，状态未变化。"
        else:
            msg = f"{app.company}·{app.role or '该岗位'} 状态已更新为「{_STATUS_LABELS[status]}」。"
        msg += company_mismatch_note
    else:
        if not company.strip():
            return error_response(
                "INVALID_PARAM",
                "company 不能为空——新建投递记录时必须填写公司名，或对已有记录传入 application_id。",
                {"field": "company", "allowed": ["非空公司名称"]},
            )
        dup = find_active_duplicate(profile, company, role)
        if dup and not allow_duplicate:
            # 重复投递可能是真实事实（不同渠道/批次），不直接拒绝：
            # 把既有记录交回，由 LLM 询问用户是更新还是新建。
            return _json({
                "duplicate": True,
                "message": (
                    f"已存在 {dup.company}·{dup.role or '同岗位'} 的活跃投递记录"
                    f"（{dup.id}，状态 {_STATUS_LABELS.get(dup.status, dup.status)}）。\n"
                    f"先问用户：更新这条记录，还是确实是一次独立投递？\n"
                    f"- 更新：record_application(application_id=\"{dup.id}\", ...)\n"
                    f"- 独立投递：record_application(..., allow_duplicate=True)"
                ),
                "existing_application_id": dup.id,
                "next_steps": ["record_application"],
            })
        app = add_application(profile, company, role, status, channel, source, notes)
        changed = True
        msg = f"已记录投递：{app.company}（{app.role or '岗位未填'}）· {_STATUS_LABELS[app.status]}"
        if dup and allow_duplicate:
            msg += f"（用户确认独立投递，另有既有记录 {dup.id}）"

    save_profile(profile)

    # Core v2 同步：只有新建或状态真正变化才落 ApplicationState artifact；
    # 状态未变化不重复写；失败不阻断主工具，但要把 warning 带回给调用方。
    sync_warning = ""
    if changed:
        try:
            from ..core.sync import sync_application_state

            sync_application_state(get_active_profile_name())
        except Exception as exc:  # noqa: BLE001 - sync 失败不阻断主工具
            sync_warning = f"Core v2 同步失败（sync_application_state）：{exc}"
        try:
            from ..core.application_list import mark_candidate_status

            mark_candidate_status(
                get_active_profile_name(), app.company, app.role, "applied"
            )
        except Exception as exc:  # noqa: BLE001 - 清单更新失败不阻断投递登记
            note = f"投递清单状态更新失败：{exc}"
            sync_warning = f"{sync_warning}；{note}" if sync_warning else note

    # 事件联动（软提示）：面试/offer 是重大事件，建议触发洞察；拒绝提示复盘
    next_steps = ["get_progress"]
    lines = [msg, ""]
    if status == "interview":
        role_label = app.role or "该岗位"
        lines.append(
            f"进入面试是重大事件——建议调用 trigger_insight(trigger_type='event', "
            f"event_description='进入「{app.company}/{role_label}」面试')，评估是否需要加面试冲刺阶段。"
        )
        next_steps = ["trigger_insight", "get_progress"]
    elif status == "offer":
        role_label = app.role or "该岗位"
        lines.append(
            f"拿到 offer 是重大事件——建议调用 trigger_insight(trigger_type='event', "
            f"event_description='拿到「{app.company}/{role_label}」offer')，评估目标是否需要升级。"
        )
        next_steps = ["trigger_insight", "get_progress"]
    elif status == "rejected":
        lines.append(
            "被拒只说明单次匹配失败，不是能力判决——可在 notes 里记下原因，"
            "多次被拒后用 get_progress 看漏斗，定位问题在简历还是面试。"
        )

    stats = funnel_stats(profile)
    if sync_warning:
        lines += [sync_warning, ""]
    lines += [format_funnel_report(profile), ""]

    context = {"phase": "application_recorded", "funnel": stats}
    if sync_warning:
        context["sync_warning"] = sync_warning
    return _json({
        "message": "\n".join(lines),
        "application": application_summary(app),
        "next_app_id_hint": application_id or app.id,
        "next_steps": next_steps,
        "context": context,
    })


@mcp.tool()
def delete_application(application_id: str) -> str:
    """删除一条投递记录（录错、重复录入时使用，不可恢复）。

    何时调用：仅当用户明确要求删除某条投递记录（如记错了公司/岗位、重复录入）。
    正常的状态变迁（被拒/撤回/放养）不要删除——漏斗统计依赖完整历史。

    Args:
        application_id: 目标记录 ID（app_NNN）
    """
    application_id = str(application_id or "").strip()
    if not application_id:
        return error_response(
            "INVALID_PARAM",
            "application_id 不能为空——请传要删除的记录 ID（app_NNN）。",
            {"field": "application_id"},
        )

    profile = load_profile()
    app = profile.get_application(application_id)
    if not app:
        return error_response(
            "MISSING_DATA",
            f"投递记录 {application_id} 不存在，未删除任何数据。完整清单见 get_progress。",
            {"application_id": application_id, "total": len(profile.applications)},
        )

    deleted_summary = application_summary(app)
    profile.applications = [a for a in profile.applications if a.id != application_id]
    profile.touch()
    save_profile(profile)

    # Core v2 同步：删除后刷新 ApplicationState artifact（失败不阻断，但要留痕）。
    # 即使删空也要调用：sync 层负责处理空状态。
    sync_warning = ""
    try:
        from ..core.sync import sync_application_state

        sync_application_state(get_active_profile_name())
    except Exception as exc:  # noqa: BLE001 - sync 失败不阻断主工具
        sync_warning = f"Core v2 同步失败（sync_application_state）：{exc}"
    try:
        from ..core.application_list import mark_candidate_status

        mark_candidate_status(
            get_active_profile_name(), app.company, app.role, "pending"
        )
    except Exception as exc:  # noqa: BLE001 - 清单更新失败不阻断删除
        note = f"投递清单状态更新失败：{exc}"
        sync_warning = f"{sync_warning}；{note}" if sync_warning else note

    message = (
        f"已删除投递记录：{app.company}·{app.role or '岗位未填'}（{application_id}）。\n"
        "删除不可恢复；若这条其实是「被拒/撤回」，建议以后用 record_application 更新"
        "状态而不是删除，避免漏斗统计失真。"
    )
    if sync_warning:
        message += f"\n{sync_warning}"
    context = {"phase": "application_deleted", "funnel": funnel_stats(profile)}
    if sync_warning:
        context["sync_warning"] = sync_warning
    return _json({
        "message": message,
        "deleted": deleted_summary,
        "next_steps": ["get_progress"],
        "context": context,
    })
