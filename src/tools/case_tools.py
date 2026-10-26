"""案例搜寻 MCP 工具——同背景成功经验与面试要求的聚合检索。"""

from __future__ import annotations

import asyncio

from ..case_search import collect_cases, render_cases
from ..mcp_app import mcp


@mcp.tool()
async def search_cases(
    role: str,
    education: str = "",
    company: str = "",
    city: str = "",
    kind: str = "both",
    limit: int = 12,
) -> str:
    """搜寻同背景成功经验与面试要求（聚合本地知识库 + 牛客面经 + GitHub 经验帖 + 目标企业 JD）。

    何时调用：
    - analyze_gaps step 2「案例搜寻」——独立步骤，一次调用替代散抓，结果直接展示给用户
    - explore_goals / generate_roadmap 需要同背景案例佐证方向可行性时

    Args:
        role: 岗位方向（如 "AI Agent 开发"、"后端"）
        education: 学历条件，支持「双非本」「211硕」「985」「专科」等（五档四层自动归一，
            展开为搜索关键词 + 精确打分；给不出想去位就留空）
        company: 目标公司（可选，命中官方源时按面试要求口径补 JD；"字节"/"boss" 等别名可直传）
        city: 城市（可选，官方/BOSS 源生效）
        kind: "both"（默认）/ "success"（只要成功经验）/ "requirements"（只要面试要求）
        limit: 返回条数上限（默认 12）

    Returns:
        两节案例卡：同背景成功经验（学历标签/届别/来源/要点）+ 面试要求（JD 口径，boss 含薪资）。
        各源独立失败不隐身——warnings 如实上报，绝不编造。

    纪律：
    - 每条案例卡展示给用户时必须标注来源（平台/url/时间）；
    - 本工具是 analyze step 2 的必调项，不得用 fetch_company_jobs 散抓替代；
    - 共性要求沉淀为差距分析输入（match_score 校准 / red flags / 优先行动）。
    """
    result = await asyncio.to_thread(
        collect_cases, role, company, city, education, kind, limit
    )
    return render_cases(result, role, education, company)
