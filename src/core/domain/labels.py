"""采集状态与筛选原因的展示标签。"""

from __future__ import annotations

REASON_LABELS: dict[str, str] = {
    "recruit_type_mismatch": "招聘类型不符",
    "graduation_mismatch": "毕业届不符",
    "degree_insufficient": "学历不足",
    "city_mismatch": "城市不符",
    "direction_excluded": "用户排除方向",
    "direction_mismatch": "方向不匹配",
    "no_detail": "缺少岗位详情",
}

CHANNEL_LABELS: dict[str, str] = {
    "intern": "日常实习",
    "campus": "校招",
    "social": "社招",
}


def reason_label(reason: str) -> str:
    return REASON_LABELS.get(str(reason or ""), str(reason or "其他"))


def channel_label(channel: str) -> str:
    return CHANNEL_LABELS.get(str(channel or ""), str(channel or "未指定"))
