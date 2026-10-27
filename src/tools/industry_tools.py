"""行业扫盲工具——轻量行业快照，不依赖行业定制爬虫。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from ..industries.loader import IndustryError, get_industry, list_industries
from ..industry_snapshot import build_snapshot
from ..mcp_app import mcp
from .errors import error_response
from .profile import load_profile, save_profile
from .tool_helpers import _json


@mcp.tool()
async def get_industry_snapshot(
    industry: str = "internet",
    major: str = "",
    school: str = "",
    degree: str = "",
    graduation_year: str = "",
    city: str = "",
    limit: int = 12,
) -> str:
    """获取轻量行业快照（扫盲子流程）。

    何时调用：用户完全不了解行业，且明确同意先花几分钟了解时。
    不是独立产品模式，不要求简历，不替代后续目标选择/规划。

    Args:
        industry: 行业 id、名称或别名（MVP 支持 internet / 互联网 / 软件 / 计算机）
        major: 可选，用于展示“你的专业在行业中的位置”；专业不是入口
        school: 可选，当前仅记录，不用于同校过滤
        degree: 可选，当前仅记录
        graduation_year: 可选，当前仅记录
        city: 可选，招聘样本城市；空为全国
        limit: 招聘样本上限（1-40）

    Returns:
        行业地图、岗位卡、招聘样本与薪资、相关专业、来源、数据缺口、下一步。
        没有数据时如实标注，不编造数字。
    """
    try:
        pack = get_industry(industry)
    except IndustryError as exc:
        return error_response(
            "INDUSTRY_NOT_SUPPORTED",
            str(exc),
            {"available": list_industries()},
        )

    try:
        snapshot = await asyncio.to_thread(
            build_snapshot,
            pack,
            major=major,
            school=school,
            degree=degree,
            graduation_year=graduation_year,
            city=city,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 — 快照失败要可诊断，不伪造结果
        return error_response(
            "ANALYSIS_FAILED",
            f"行业快照生成失败：{exc}",
            {"industry": pack.get("id", ""), "recovery": "稍后重试，或先导入手头资料"},
        )

    profile = load_profile()
    now = datetime.now().isoformat()
    want = profile.want if isinstance(profile.want, dict) else {}
    want["industry_id"] = pack.get("id", "")
    want["scan_consent"] = True
    want["scan_completed_at"] = now
    want["scan_summary"] = snapshot.get("summary") or []
    profile.want = want
    if major:
        profile.who["major"] = (snapshot.get("major_match") or {}).get("canonical") or major
    if school:
        profile.who["school"] = school
    if degree:
        profile.who["degree"] = degree
    if graduation_year:
        profile.who["graduation_year"] = graduation_year
    if isinstance(profile.research, dict):
        profile.research["industry_snapshot"] = snapshot
    profile.touch()
    save_profile(profile)

    return _json(
        {
            **snapshot,
            "saved_to_profile": True,
            "instructions": (
                "用 3-5 分钟讲成一页认知卡：先行业地图，再 3-5 个岗位，再薪资/门槛，"
                "最后问用户想深入哪个方向。"
                "所有数字必须来自本快照并标注来源/样本数；没有数据的部分直接说未获取，"
                "不要用通用知识补具体薪资或招聘要求。"
                "用户看完后引导到目标选择/规划，不要停留在扫盲。"
            ),
        }
    )
