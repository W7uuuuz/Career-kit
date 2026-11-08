"""计划失配检测 MCP 工具——只读档案与 artifact，不写档案、不改计划。"""

from __future__ import annotations

from ..core import plan_fit as _plan_fit
from ..mcp_app import mcp
from .errors import error_response
from .profile import get_active_profile_name
from .tool_helpers import _json


@mcp.tool()
def check_plan_fit(trigger: str = "manual") -> str:
    """检测旧计划是否仍适合新证据（只读检测器，不修改档案）。

    何时调用：
    - 证据池刷新后：trigger="evidence_refresh"；
    - 完成一个里程碑后：trigger="milestone"；
    - 周检视时：trigger="weekly_review"；
    - 用户主动问「计划还合适吗」：trigger="manual"。

    工作方式：读取当前档案与最新 CompanyPool / EvidenceRun /
    RequirementProfile / ExecutionPlan，返回确定性信号（证据新鲜度、链路一致性、
    要求覆盖率、任务匹配、漏斗样本）。不写档案、不改计划、不调用 LLM。

    Args:
        trigger: 触发场景，可选 manual / evidence_refresh / milestone / weekly_review。

    Returns:
        JSON 字符串：
        - status: aligned / minor_drift / major_drift / stale_evidence / incomplete_chain
        - signals: 每条含 code / severity / message / evidence_ids / task_ids
        - recommended_action / next_tool: 建议动作与下一步工具
        - question_for_user: 可直接问用户的一句话（aligned 时为空）

    使用纪律：
    - status=major_drift 时，必须把 question_for_user 的意思转问用户，
      不要替用户决定；
    - 用户同意后才调用 next_tool 指向的采集/校准工具；
    - 不要根据 signals 自行改写计划，也不要制造焦虑；只陈述事实与证据。
    """
    profile_name = get_active_profile_name()
    try:
        result = _plan_fit.check_plan_fit(profile_name, trigger)
    except Exception as exc:  # noqa: BLE001 —— 只读检测失败要转成可读错误
        return error_response("PLAN_FIT_FAILED", f"计划失配检测失败：{exc}")

    # Core v2 同步：计划失配检测结果落 ReviewReport artifact（失败不阻断）
    try:
        from ..core.sync import sync_review

        sync_review(profile_name, plan_fit=result)
    except Exception:  # noqa: BLE001 - sync 失败不阻断主工具
        pass

    return _json(result)


__all__ = ["check_plan_fit"]
