"""招聘通道路由：按用户要投的岗位类型选择来源参数。

旧实现把完整岗位名（含斜杠/括号/「日常实习」）整体当关键词传给官方源，
且默认走社招库，导致实习目标大面积「未找到相关岗位」。这里把通道选择
收敛成唯一入口：能服务该 job_kind 的源才查询，不能服务的源标记 skipped。
"""

from __future__ import annotations

import re
from typing import Any

from ..scrapers import loader

# 固定只服务单一通道的源（没有 scope/portal 参数，但语义明确）。
_FIXED_CHANNELS: dict[str, dict[str, dict[str, Any]]] = {
    "shixiseng": {"intern": {}},
    "alibaba_social": {"social": {}},
}


def route_params(slug: str, job_kind: str) -> tuple[str, dict[str, Any]]:
    """返回 (状态, 参数)。

    - ok：该源可服务目标通道，参数已就绪；
    - skip：该源不服务目标通道（不是失败）；
    - unknown：源未声明通道能力，按原样查询，不额外注入参数。
    """
    kind = str(job_kind or "").strip().lower()
    if not kind:
        return "unknown", {}
    fixed = _FIXED_CHANNELS.get(slug)
    if fixed is not None:
        return ("ok", dict(fixed[kind])) if kind in fixed else ("skip", {})

    params = _scraper_params(slug)
    if not params:
        return "unknown", {}

    if "scope" in params:
        if kind in {"intern", "campus", "social"}:
            return "ok", {"scope": kind}
        return "skip", {}

    if "portal" in params:
        # campus 门户通常同时包含校招与实习；具体岗位由资格谓词再筛。
        if kind in {"campus", "intern"}:
            return "ok", {"portal": "campus"}
        if kind == "social":
            return "ok", {"portal": "experienced"}
        return "skip", {}

    return "unknown", {}


def supported_channels(slug: str) -> list[str]:
    """给文档/控制台展示：该源声明支持哪些通道。"""
    fixed = _FIXED_CHANNELS.get(slug)
    if fixed is not None:
        return sorted(fixed)
    params = _scraper_params(slug)
    if "scope" in params:
        return ["campus", "intern", "social"]
    if "portal" in params:
        return ["campus", "intern", "social"]
    return []


def primary_keyword(role: str, fallback: str = "") -> str:
    """从完整岗位名里取一个最可能命中的搜索词，避免整串传入。"""
    from ..core.domain.eligibility import direction_terms

    text = str(role or fallback or "").strip()
    if not text:
        return ""
    # 短且干净的方向名（如「AI Agent 开发」）整体搜索命中率更高，保持原样；
    # 含斜杠/括号/招聘类型的长标题才拆词，避免官方源整串匹配失败。
    if (
        len(text) <= 12
        and not re.search(r"[/|()（）]", text)
        and "实习" not in text
        and "校招" not in text
        and "社招" not in text
    ):
        return text
    terms = direction_terms(text)
    return terms[0] if terms else text


def _scraper_params(slug: str) -> dict[str, Any]:
    try:
        return loader.scraper_params(slug)
    except Exception:  # noqa: BLE001 - 能力发现失败时按未知处理
        return {}

