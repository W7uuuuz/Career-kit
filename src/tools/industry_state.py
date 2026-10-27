"""行业状态变更的共享语义——扫盲和 intake 必须一致。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def industry_of(want: dict[str, Any] | None) -> str:
    """从 want 中取出当前行业标识（id 优先，兼容旧 industry 字段）。"""
    data = want or {}
    return str(data.get("industry_id") or data.get("industry") or "").strip()


def mark_industry_change(
    profile: Any,
    old_industry: str,
    new_industry: str,
) -> bool:
    """行业真的变化时标记旧差距分析过期；首次选择行业不标记。

    扫盲快照和 intake 都走这里，避免两条写入路径语义漂移。
    """
    old = str(old_industry or "").strip()
    new = str(new_industry or "").strip()
    if not old or not new or old == new:
        return False
    profile.gap_stale_at = datetime.now().isoformat()
    return True
