"""多档案管理 MCP 工具。"""

from __future__ import annotations

from ..mcp_app import mcp
from .errors import error_response
from .profile import (
    delete_profile as do_delete_profile,
    get_active_profile_name,
    list_profiles as do_list_profiles,
    list_trash as do_list_trash,
    load_profile,
    profile_exists,
    restore_profile as do_restore_profile,
    set_active_profile_name,
    validate_profile_name,
)
from .session_tools import _summarize_dict


@mcp.tool()
def list_profiles() -> str:
    """列出所有职业档案，标记当前使用中的档案。

    何时调用：用户想查看/选择/切换档案，或想知道当前在用哪份档案时。
    多档案场景：一份电脑多人使用、一个人多份规划（转行前后）、测试备份等。

    Returns:
        每个档案：名称、是否当前使用、身份、目标、版本、更新时间。
    """
    profiles = do_list_profiles()

    if not profiles:
        return (
            "当前还没有任何档案。\n\n"
            "开始第一步：调用 start_session 开始建档。"
        )

    active = get_active_profile_name()
    lines = ["【职业档案列表】\n"]
    for p in profiles:
        mark = "[当前使用]" if p["is_active"] else "—"
        person = p.get("person") or "（未填身份）"
        target = p.get("target") or "（未设目标）"
        has_plan = "有路线图" if p.get("has_plan") else ""
        lines.append(
            f"- **{p['name']}** {mark}\n"
            f"  身份：{person}\n"
            f"  目标：{target}\n"
            f"  版本 v{p.get('version', 0)} · 更新于 {p.get('updated_at', '?')[:10]} {has_plan}"
        )
        lines.append("")

    lines.append("---")
    lines.append(f"当前使用：{active}")
    lines.append("切换档案：switch_profile(profile_name=\"<档案名>\")")
    lines.append("删除档案：delete_profile(profile_name=\"<档案名>\")（当前使用的档案不可删除）")
    return "\n".join(lines)


@mcp.tool()
def switch_profile(profile_name: str) -> str:
    """切换当前使用的档案。

    何时调用：用户有多份档案，想切换到另一份继续规划时。
    切换后，所有建档/分析/规划/任务工具都操作新档案。

    Args:
        profile_name: 目标档案名（用 list_profiles 查看可用档案）

    Returns:
        切换结果 + 新档案的当前状态摘要。
    """
    # 先校验名称与存在性，全部通过才写入 active——失败路径不污染当前状态
    try:
        validate_profile_name(profile_name)
    except ValueError as e:
        return error_response("INVALID_PROFILE", str(e), {"profile_name": profile_name})
    if not profile_exists(profile_name):
        available = ", ".join(p["name"] for p in do_list_profiles()) or "无"
        return error_response(
            "PROFILE_NOT_FOUND",
            f"档案「{profile_name}」不存在。",
            {"available": available, "hint": "先调用 list_profiles 查看可用档案"},
        )

    set_active_profile_name(profile_name)
    profile = load_profile(profile_name)

    # 未 finalize 的档案 summary 为空，实时从 sections 生成摘要
    summary = profile.summary
    if not summary:
        parts = []
        if profile.who:
            parts.append(f"身份：{_summarize_dict(profile.who)}")
        if profile.have:
            parts.append(f"现状：{_summarize_dict(profile.have)}")
        if profile.want:
            parts.append(f"目标：{_summarize_dict(profile.want)}")
        summary = "；".join(parts) if parts else "（档案为空，尚未建档）"

    return (
        f"已切换到档案「{profile_name}」。\n\n"
        f"档案摘要：{summary}\n\n"
        f"下一步：调用 get_workflow_status 查看该档案进度。"
    )


@mcp.tool()
def delete_profile(profile_name: str, confirm: str = "") -> str:
    """删除一份职业档案——移入回收站，可恢复。

    何时调用：用户确认要废弃某份档案时。删除是回收站式的：档案移入
    本地回收站目录（trash/），可用 list_trash 查看、restore_profile 恢复，
    不会真正丢失数据。

    Args:
        profile_name: 要删除的档案名（用 list_profiles 查看可用档案）
        confirm: 必须显式传 "true" 才会执行；其他值只返回确认提示不删除

    Returns:
        删除结果 + 回收站位置 + 恢复指引。
    """
    if confirm != "true":
        return (
            f"即将删除档案「{profile_name}」——这是不可逆的用户决策，"
            "请先与用户确认（展示该档案的身份/目标/更新时间），确认后重试：\n"
            'delete_profile(profile_name="<档案名>", confirm="true")\n\n'
            "说明：删除是回收站式的，档案会移入本地回收站（trash/），"
            "恢复可用 restore_profile(profile_name=\"<档案名>\")。"
        )

    if profile_name == get_active_profile_name():
        return error_response(
            "PROFILE_IN_USE",
            f"档案「{profile_name}」是当前使用中的档案，不能直接删除（否则会话会失去档案上下文）。",
            {
                "hint": "先用 switch_profile(profile_name=\"<其他档案名>\") 或新建档案后再删除；"
                        "刚删除的内容在回收站可用 restore_profile 找回"
            },
        )

    if not profile_exists(profile_name):
        return error_response(
            "PROFILE_NOT_FOUND",
            f"档案「{profile_name}」不存在。",
            {"hint": "先调用 list_profiles 查看可用档案"},
        )

    try:
        target_path = do_delete_profile(profile_name)
    except ValueError as e:
        return error_response("INVALID_PROFILE", str(e), {"profile_name": profile_name})

    if target_path is None:
        return error_response("PROFILE_NOT_FOUND", f"档案「{profile_name}」不存在。", {})

    remaining = do_list_profiles()
    remain_text = "、".join(p["name"] for p in remaining) or "无（仓库为空）"
    return (
        f"已删除档案「{profile_name}」（移入回收站，可恢复）。\n\n"
        f"回收站位置：{target_path}\n"
        f"剩余档案：{remain_text}\n"
        f"当前使用：{get_active_profile_name()}\n\n"
        "下一步：需要找回时调用 restore_profile(profile_name=\"<档案名>\")。"
    )


@mcp.tool()
def list_trash() -> str:
    """列出回收站中的档案（已删除、可恢复项）。

    何时调用：用户想知道删了哪些档案、能否恢复时。
    恢复：restore_profile(profile_name=\"<档案名>\")。
    """
    items = do_list_trash()

    if not items:
        return "回收站为空——还没有删除过任何档案。"

    lines = ["【回收站】已删除档案（可恢复）：\n"]
    for item in items:
        lines.append(
            f"- **{item['profile_name']}**（文件：{item['file']}，删除于 {item['deleted_at'][:19]}）"
        )
    lines.append("")
    lines.append("恢复：restore_profile(profile_name=\"<档案名>\")")
    lines.append("注意：目标位置已存在同名档案时拒绝恢复（防覆盖新数据）。")
    return "\n".join(lines)


@mcp.tool()
def restore_profile(profile_name: str) -> str:
    """从回收站恢复档案。

    何时调用：用户删除档案后又想找回时。恢复的是回收站中最新一份备份；
    目标位置已存在同名档案时拒绝恢复（防覆盖新数据）。

    Args:
        profile_name: 要恢复的档案名（用 list_trash 查看可恢复项）

    Returns:
        恢复结果 + 档案摘要。
    """
    try:
        validate_profile_name(profile_name)
    except ValueError as e:
        return error_response("INVALID_PROFILE", str(e), {"profile_name": profile_name})
    try:
        target_path = do_restore_profile(profile_name)
    except ValueError as e:
        return error_response("INVALID_PROFILE", str(e), {"profile_name": profile_name})

    if target_path is None:
        return error_response(
            "PROFILE_NOT_FOUND",
            f"回收站中没有档案「{profile_name}」。",
            {"hint": "先调用 list_trash 查看可恢复项"},
        )

    profile = load_profile(profile_name)
    parts = []
    if profile.who:
        parts.append(f"身份：{_summarize_dict(profile.who)}")
    if profile.have:
        parts.append(f"现状：{_summarize_dict(profile.have)}")
    if profile.want:
        parts.append(f"目标：{_summarize_dict(profile.want)}")
    summary = "；".join(parts) if parts else "（档案为空）"

    return (
        f"已恢复档案「{profile_name}」。\n\n"
        f"档案摘要：{summary}\n\n"
        "下一步：用 switch_profile(profile_name=\"<档案名>\") 切换到该档案继续规划。"
    )
