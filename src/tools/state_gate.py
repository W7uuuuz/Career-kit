"""统一工具状态门禁（Phase 3a）。

门禁只消费 ``core.state.resolve_state`` 的唯一快照：工具不在
``StateSnapshot.allowed_tools`` 时返回 ``INVALID_STATE``，不执行业务逻辑。
工具→状态允许关系只在 ``core.state._ALLOWED_TOOLS`` 维护，本模块不另写映射。
"""

from __future__ import annotations

from typing import Any

from ..core.state import READ_ONLY_TOOLS, StateSnapshot, resolve_state
from .errors import error_response

# 数据事实录入/获取工具：只写档案或拉取外部事实，不推进阶段，故不参与状态门禁。
UNGATED_TOOLS = frozenset(
    {
        "intake",
        "parse_resume",
        "import_jd",
        "import_jd_file",
        "gather_research_data",
        "fetch_company_jobs",
        "fetch_jd_detail",
        "boss_login",
        "search_cases",
        "search_knowledge",
        "research_market",
    }
)


def require_state(profile: Any, tool: str) -> StateSnapshot | str:
    """校验工具是否允许在当前状态调用。

    Returns:
        允许时返回 ``StateSnapshot``；不允许时返回 ``INVALID_STATE`` JSON 字符串。
    """
    snapshot = resolve_state(profile)

    if tool in READ_ONLY_TOOLS or tool in UNGATED_TOOLS:
        return snapshot
    if tool in snapshot.allowed_tools:
        return snapshot

    return error_response(
        "INVALID_STATE",
        f"当前状态 {snapshot.state.value} 不允许调用 {tool}；"
        f"下一步应调用 {snapshot.next_tool}。",
        {
            "state": snapshot.state.value,
            "tool": tool,
            "allowed_tools": sorted(snapshot.allowed_tools),
            "next_tool": snapshot.next_tool,
        },
    )


__all__ = ["READ_ONLY_TOOLS", "UNGATED_TOOLS", "require_state"]
