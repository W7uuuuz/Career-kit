"""投递清单报告：md / json 两件套，100% 由代码渲染。

报告只展示已由代码筛选、打分、排序得到的 ApplicationCandidate 事实，
不调用 LLM、不补写任何岗位。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ... import assets
from ..artifacts.models import ApplicationCandidate

_STATUS_LABELS = {"pending": "待投递", "applied": "已投递"}


def build_report(
    candidates: list[ApplicationCandidate],
    *,
    profile_name: str,
    direction: str,
    evidence_run_id: str = "",
    requirement_profile_id: str = "",
    city: str = "",
    role: str = "",
    total_scored: int = 0,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """把候选列表转成可渲染、可序列化的报告结构。"""
    payloads = [candidate.model_dump() for candidate in candidates]
    return {
        "type": "application_list_report",
        "profile_name": profile_name,
        "direction": direction,
        "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "city": city,
        "role": role,
        "evidence_run_id": evidence_run_id,
        "requirement_profile_id": requirement_profile_id,
        "counts": {
            "candidates": len(payloads),
            "total_scored": total_scored,
            "applied": sum(1 for item in payloads if item.get("status") == "applied"),
        },
        "candidates": payloads,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """渲染 markdown 版本。"""
    counts = report.get("counts") or {}
    lines: list[str] = [
        f"# 投递清单 — {report.get('direction') or '未命名方向'}",
        "",
        f"> 生成于 {report.get('generated_at')}。城市为硬筛选，方向/技能/学历/档位/薪资为软打分；"
        "全部候选来自已采集证据池，不使用 AI 补写岗位。",
        "",
        f"- 候选：{counts.get('candidates', 0)} 个（评分样本 {counts.get('total_scored', 0)} 条）",
        f"- 已投递：{counts.get('applied', 0)} 个",
        f"- 城市：{report.get('city') or '不限'} · 方向：{report.get('role') or '不限'}",
        "",
        "## 候选清单",
        "",
    ]
    rows = report.get("candidates") or []
    if rows:
        lines.append("| 公司 | 档位 | 岗位 | 城市 | 薪资 | 匹配 | 理由 | 缺口 | 链接 | 状态 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for item in rows:
            lines.append(
                "| {company} | {tier} | {title} | {location} | {salary} | {score} | "
                "{reasons} | {gaps} | {link} | {status} |".format(
                    company=_md_cell(item.get("company")),
                    tier=_md_cell(item.get("tier")),
                    title=_md_cell(item.get("title")),
                    location=_md_cell(item.get("location")),
                    salary=_md_cell(item.get("salary")),
                    score=_safe_int(item.get("match_score")),
                    reasons=_md_cell("；".join(item.get("reasons") or [])),
                    gaps=_md_cell("；".join(item.get("gaps") or [])),
                    link=_md_link(item.get("url") or "链接", item.get("url") or ""),
                    status=_STATUS_LABELS.get(str(item.get("status")), str(item.get("status") or "")),
                )
            )
    else:
        lines.append("没有符合条件的候选岗位。")
    lines.append("")
    return "\n".join(lines)


def save_report(
    candidates: list[ApplicationCandidate],
    profile_name: str,
    direction: str,
    *,
    evidence_run_id: str = "",
    requirement_profile_id: str = "",
    city: str = "",
    role: str = "",
    total_scored: int = 0,
    generated_at: str | None = None,
) -> dict[str, str]:
    """写入投递清单资产目录；返回 md / json 路径。"""
    report = build_report(
        candidates,
        profile_name=profile_name,
        direction=direction,
        evidence_run_id=evidence_run_id,
        requirement_profile_id=requirement_profile_id,
        city=city,
        role=role,
        total_scored=total_scored,
        generated_at=generated_at,
    )
    stem = assets.next_asset_stem(
        direction or "投递清单", kind="applications", profile_name=profile_name
    )
    md_path = assets.write_asset_text(
        "applications", profile_name, f"{stem}.md", render_markdown(report), encoding="utf-8-sig"
    )
    json_path = assets.write_asset_text(
        "applications",
        profile_name,
        f"{stem}.json",
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return {"md": str(md_path), "json": str(json_path)}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _md_link(label: Any, url: Any) -> str:
    text = _md_cell(label)
    href = str(url or "").strip()
    if not href:
        return text
    return f"[{text}]({href.replace(')', '%29')})"


__all__ = ["build_report", "render_markdown", "save_report"]
