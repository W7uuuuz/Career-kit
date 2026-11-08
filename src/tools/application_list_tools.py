"""投递清单 MCP 工具：用证据池批量筛选、打分并落盘投递候选。"""

from __future__ import annotations

from ..core.application_list import (
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP,
    MissingEvidenceError,
    run as _run,
)
from ..mcp_app import mcp
from .errors import error_response
from .profile import get_active_profile_name
from .tool_helpers import _json


@mcp.tool()
def build_application_list(
    city: str = "",
    role: str = "",
    top: int = DEFAULT_TOP,
    min_score: int = DEFAULT_MIN_SCORE,
    include_applied: bool = False,
) -> str:
    """从证据池生成投递清单：城市硬筛，方向/技能/学历/档位/薪资软打分。

    何时调用：已采集证据池（collect_company_evidence）之后，准备批量投递时。
    本工具只使用 EvidenceRun 中的真实 JD，不编造岗位；数字与排序由代码计算。
    已投递（company + title 与档案投递记录匹配）默认不重复推荐。

    Args:
        city: 目标城市（空串使用证据池/档案中的目标城市）；城市是硬筛选，
            location 含目标城市或「远程/全国/不限」的岗位保留。
        role: 目标方向（空串使用证据池/档案中的目标岗位）；按分词命中 title/summary 软打分。
        top: 最多返回多少个候选（默认 30）。
        min_score: 最低匹配分（0-100），低于该分数的候选不返回。
        include_applied: 是否把已投递岗位也纳入清单（状态标记为 applied）。

    Returns:
        JSON 字符串：候选数量、top 列表、报告路径与下一步；
        每个候选带公司、档位、岗位、城市、薪资、链接、匹配分、命中理由、缺口、状态。
    """
    profile_name = get_active_profile_name()
    try:
        payload = _run(
            profile_name,
            city=city,
            role=role,
            top=top,
            min_score=min_score,
            include_applied=include_applied,
        )
    except MissingEvidenceError as exc:
        return error_response(
            "MISSING_DATA",
            str(exc),
            {"profile_name": profile_name, "next_tool": "collect_company_evidence"},
        )
    return _json(payload)


__all__ = ["build_application_list"]
