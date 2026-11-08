"""投递清单报告：md / html / json 三件套，100% 由代码渲染。

报告只展示已由代码筛选、打分、排序得到的 ApplicationCandidate 事实，
不调用 LLM、不补写任何岗位。HTML 所有动态内容均转义。
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
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


def render_html(report: dict[str, Any]) -> str:
    """渲染自包含 HTML 阅读版（所有动态内容转义）。"""
    counts = report.get("counts") or {}
    direction = report.get("direction") or "投递清单"
    rows = report.get("candidates") or []
    summary = (
        f"候选 {counts.get('candidates', 0)} 个，已投递 {counts.get('applied', 0)} 个，"
        f"城市 {report.get('city') or '不限'}"
    )
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta name="career-kit-summary" content="{escape(summary, quote=True)}">',
        f"<title>投递清单 — {escape(direction)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>投递清单 — {escape(direction)}</h1>",
        f'<p class="sub">生成于 {escape(str(report.get("generated_at") or ""))}。'
        "城市为硬筛选，方向/技能/学历/档位/薪资为软打分；全部候选来自已采集证据池。</p>",
    ]
    meta_bits = " · ".join(
        escape(str(value))
        for value in (report.get("city"), report.get("role"))
        if str(value or "").strip()
    )
    if meta_bits:
        parts.append(f'<p class="target">{meta_bits}</p>')

    parts.append('<div class="stats">')
    for label, value in (
        ("候选", counts.get("candidates", 0)),
        ("评分样本", counts.get("total_scored", 0)),
        ("已投递", counts.get("applied", 0)),
    ):
        parts.append(
            f'<div class="stat"><span class="stat-label">{escape(str(label))}</span>'
            f'<span class="stat-value">{escape(str(value))}</span></div>'
        )
    parts.append("</div>")

    parts.append("<h2>候选清单</h2>")
    if rows:
        parts.append(
            "<table><thead><tr><th>公司</th><th>档位</th><th>岗位</th><th>城市</th>"
            "<th>薪资</th><th>匹配</th><th>理由</th><th>缺口</th><th>链接</th>"
            "<th>状态</th></tr></thead><tbody>"
        )
        for item in rows:
            parts.append(
                "<tr><td>{company}</td><td>{tier}</td><td>{title}</td><td>{location}</td>"
                "<td>{salary}</td><td>{score}</td><td>{reasons}</td><td>{gaps}</td>"
                "<td>{link}</td><td>{status}</td></tr>".format(
                    company=escape(str(item.get("company") or "")),
                    tier=escape(str(item.get("tier") or "")),
                    title=escape(str(item.get("title") or "")),
                    location=escape(str(item.get("location") or "")),
                    salary=escape(str(item.get("salary") or "")),
                    score=escape(str(_safe_int(item.get("match_score")))),
                    reasons=escape("；".join(item.get("reasons") or [])),
                    gaps=escape("；".join(item.get("gaps") or [])),
                    link=_html_link(item.get("url") or "链接", item.get("url") or ""),
                    status=escape(
                        _STATUS_LABELS.get(str(item.get("status")), str(item.get("status") or ""))
                    ),
                )
            )
        parts.append("</tbody></table>")
    else:
        parts.append('<p class="note">没有符合条件的候选岗位。</p>')

    parts.append(
        "</main><footer>本页由代码直接渲染自 ApplicationState artifact；"
        "原始数据见同名 .json 文件。</footer></body></html>"
    )
    return "".join(parts)


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
    """写入投递清单资产目录并刷新资产 index；返回三种格式的路径。"""
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
    html_path = assets.write_asset_text(
        "applications", profile_name, f"{stem}.html", render_html(report), encoding="utf-8"
    )
    json_path = assets.write_asset_text(
        "applications",
        profile_name,
        f"{stem}.json",
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    assets.rebuild_index()
    return {"md": str(md_path), "html": str(html_path), "json": str(json_path)}


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


def _html_link(label: Any, url: Any) -> str:
    text = escape(str(label or ""))
    href = str(url or "").strip()
    if not href:
        return text
    return f'<a href="{escape(href, quote=True)}">{text}</a>'


_CSS = """
:root { --ink:#1f2430; --muted:#6b7280; --line:#e5e7eb; --bg:#f6f7fb; --card:#fff; --accent:#0f766e; }
* { box-sizing:border-box; }
body { margin:0; font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
       color:var(--ink); background:var(--bg); }
main { max-width:1180px; margin:0 auto; padding:28px 20px 12px; }
h1 { margin:0 0 8px; font-size:24px; }
h2 { margin:28px 0 10px; font-size:18px; }
.sub, .target { color:var(--muted); font-size:13px; margin:0 0 6px; }
.stats { display:grid; gap:10px; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); }
.stat { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }
.stat-label { display:block; color:var(--muted); font-size:12px; }
.stat-value { display:block; margin-top:4px; font-size:18px; font-weight:600; }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
        border-radius:10px; overflow:hidden; font-size:13px; }
th, td { padding:8px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }
th { background:#ecfdf5; color:#065f46; font-weight:600; }
tr:last-child td { border-bottom:none; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.note { color:var(--muted); font-size:13px; }
footer { max-width:1180px; margin:0 auto 30px; padding:8px 20px; color:var(--muted); font-size:12px; }
@media (max-width:640px) { main { padding:20px 14px 8px; } table { display:block; overflow-x:auto; } }
"""


__all__ = ["build_report", "render_html", "render_markdown", "save_report"]
