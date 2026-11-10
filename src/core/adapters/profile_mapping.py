"""当前 `CareerProfile` → Core v2 输入映射。

只读取档案字段并返回新模型，不修改原档案；缺失字段按契约兜底。
"""

from __future__ import annotations

import copy
from typing import Any

from ...models import CareerProfile
from ..artifacts.models import ProfileSnapshot, TargetSpec


def profile_snapshot(profile: CareerProfile) -> ProfileSnapshot:
    """生成档案快照（深拷贝各 section），供阶段 9 校准执行方案。"""
    who = _as_dict(getattr(profile, "who", None))
    return ProfileSnapshot(
        name=str(getattr(profile, "name", "") or who.get("name") or ""),
        who=copy.deepcopy(who),
        have=copy.deepcopy(_as_dict(getattr(profile, "have", None))),
        want=copy.deepcopy(_as_dict(getattr(profile, "want", None))),
        gap=copy.deepcopy(_as_dict(getattr(profile, "gap", None))),
        plan=copy.deepcopy(_as_dict(getattr(profile, "plan", None))),
        summary=str(getattr(profile, "summary", "") or ""),
        updated_at=str(getattr(profile, "updated_at", "") or ""),
    )


def target_spec(profile: CareerProfile) -> TargetSpec:
    """从 want/who 提取目标岗位定位；档位缺失时用「大厂/中厂」兜底。"""
    want = _as_dict(getattr(profile, "want", None))
    who = _as_dict(getattr(profile, "who", None))
    role = str(want.get("target_role") or want.get("direction") or "")
    direction = str(want.get("direction") or want.get("target_role") or "")
    return TargetSpec(
        direction=direction,
        role=role,
        city=str(want.get("city") or who.get("city") or ""),
        target_tiers=_list_of_str(want.get("target_tiers")) or ["大厂"],
        bridge_tiers=_list_of_str(want.get("bridge_tiers")) or ["中厂"],
        graduation_year=str(who.get("graduation_year") or want.get("graduation_year") or ""),
        constraints=_list_of_str(want.get("constraints")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


__all__ = ["profile_snapshot", "target_spec"]
