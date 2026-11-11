"""证据池报告：md / json 两件套，100% 由代码渲染。

报告只展示已落库的 EvidenceRun 事实（样本统计、来源状态、JD/面经表、
置信度、数据缺口），不调用 LLM、不补写任何未采集内容。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ... import assets
from ..artifacts.models import EvidenceRun

_STATUS_LABELS = {"ok": "正常", "failed": "失败", "empty": "无结果"}
_CONFIDENCE_LABELS = {"low": "低", "medium": "中", "high": "高"}
_DETAIL_LABELS = {"ok": "完整", "missing": "缺失", "failed": "补抓失败"}


def build_report(evidence: EvidenceRun, *, generated_at: str | None = None) -> dict[str, Any]:
    """把 EvidenceRun 转成可渲染、可序列化的报告结构。"""
    direction = evidence.target_spec.direction or evidence.target_spec.role or "证据池"
    statuses = [dict(item) for item in evidence.meta.source_status if isinstance(item, dict)]
    source_ok = sum(1 for item in statuses if item.get("status") == "ok")
    source_fail = sum(1 for item in statuses if item.get("status") == "failed")
    source_empty = sum(1 for item in statuses if item.get("status") == "empty")
    counts = {
        **evidence.counts,
        "jd_samples": len(evidence.jd_items),
        "cases": len(evidence.interview_items),
        "source_ok": source_ok,
        "source_fail": source_fail,
        "source_empty": source_empty,
    }
    return {
        "type": "evidence_report",
        "artifact_id": evidence.meta.id,
        "profile_name": evidence.meta.profile_name,
        "direction": direction,
        "generated_at": generated_at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": evidence.target_spec.model_dump(),
        "company_pool_id": evidence.company_pool_id,
        "counts": counts,
        "confidence": dict(evidence.confidence),
        "source_status": statuses,
        "gaps": list(evidence.gaps),
        "jd_samples": [item.model_dump() for item in evidence.jd_items],
        "cases": [item.model_dump() for item in evidence.interview_items],
    }


def render_markdown(report: dict[str, Any]) -> str:
    """渲染 markdown 版本。"""
    counts = report.get("counts") or {}
    confidence = report.get("confidence") or {}
    target = report.get("target") or {}
    lines: list[str] = [
        f"# 岗位与面经证据池 — {report.get('direction') or '未命名方向'}",
        "",
        f"> 生成于 {report.get('generated_at')}。全部数据来自实时抓取与本地知识库，"
        "未获取的内容如实标注，不使用 AI 补写。",
        "",
    ]
    target_bits = [
        str(value)
        for value in (target.get("direction"), target.get("role"), target.get("city"))
        if str(value or "").strip()
    ]
    if target_bits:
        lines.append("方向：" + " · ".join(target_bits))
        lines.append("")

    lines.append("## 样本统计")
    lines.append("")
    lines.append(f"- JD：{counts.get('jd_samples', 0)} 条（置信度 {_confidence_text(confidence.get('jd'))}）")
    lines.append(
        f"- 面经：{counts.get('cases', 0)} 条"
        f"（置信度 {_confidence_text(confidence.get('interview'))}）"
    )
    lines.append(f"- 请求企业：{counts.get('companies_requested', 0)} 家")
    lines.append(f"- 抓取成功企业：{counts.get('companies_fetched', 0)} 家")
    lines.append(f"- 原始 JD：{counts.get('raw_jobs', 0)} 条；保留：{counts.get('kept_jobs', 0)} 条")
    lines.append(
        f"- 城市剔除：{counts.get('dropped_city', 0)} 条；无详情剔除："
        f"{counts.get('dropped_no_detail', 0)} 条；城市未知：{counts.get('unknown_city', 0)} 条"
    )
    lines.append(
        f"- 复用历史样本：JD {counts.get('reused_jd', 0)} 条 / "
        f"面经 {counts.get('reused_interviews', 0)} 条；其中池外复用 "
        f"{counts.get('reused_outside_pool', 0)} 条"
    )
    lines.append(
        f"- 岗位相关性剔除：{counts.get('dropped_irrelevant', 0)} 条"
    )
    lines.append("")

    lines.extend(["## 来源状态", ""])
    statuses = report.get("source_status") or []
    if statuses:
        lines.append("| 来源 | 范围 | 状态 | 条数 | 耗时（秒） | 错误 |")
        lines.append("|---|---|---|---|---|---|")
        for item in statuses:
            lines.append(
                "| {source} | {scope} | {status} | {count} | {elapsed} | {error} |".format(
                    source=_md_cell(item.get("source")),
                    scope="面经" if item.get("scope") == "cases" else "JD",
                    status=_STATUS_LABELS.get(str(item.get("status")), str(item.get("status") or "")),
                    count=_safe_int(item.get("count")),
                    elapsed=item.get("elapsed", 0),
                    error=_md_cell(item.get("error") or ""),
                )
            )
    else:
        lines.append("本次没有调用任何抓取源。")
    lines.append("")

    lines.extend(["## 岗位 JD", ""])
    jd_items = report.get("jd_samples") or []
    if jd_items:
        lines.append("| ID | 公司 | 岗位 | 地点 | 薪资 | 来源 | 详情 | 摘要 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for item in jd_items:
            lines.append(
                "| {id} | {company} | {title} | {location} | {salary} | {source} | {detail} | {summary} |".format(
                    id=_md_cell(item.get("id")),
                    company=_md_cell(item.get("company")),
                    title=_md_cell(item.get("title")),
                    location=_md_cell(item.get("location")),
                    salary=_md_cell(item.get("salary")),
                    source=_md_link(item.get("source") or "来源", item.get("url") or ""),
                    detail=_DETAIL_LABELS.get(str(item.get("detail_status")), str(item.get("detail_status") or "")),
                    summary=_md_cell(_clip(item.get("summary") or item.get("description") or "")),
                )
            )
    else:
        lines.append("未采集到岗位 JD。")
    lines.append("")

    lines.extend(["## 面经", ""])
    cases = report.get("cases") or []
    if cases:
        lines.append("| ID | 公司 | 标题 | 学历 | 届别 | 来源 | 要点 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in cases:
            lines.append(
                "| {id} | {company} | {title} | {education} | {year} | {source} | {highlights} |".format(
                    id=_md_cell(item.get("id")),
                    company=_md_cell(item.get("company") or "通用"),
                    title=_md_cell(item.get("title")),
                    education=_md_cell(item.get("education_tag")),
                    year=_md_cell(item.get("year")),
                    source=_md_link(item.get("source") or "来源", item.get("url") or ""),
                    highlights=_md_cell("；".join(item.get("highlights") or [])),
                )
            )
    else:
        lines.append("未采集到面经。")
    lines.append("")

    lines.extend(["## 数据缺口", ""])
    gaps = report.get("gaps") or []
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("本次采集没有产生缺口记录。")
    lines.append("")
    return "\n".join(lines)


def save_report(
    evidence: EvidenceRun, profile_name: str, *, generated_at: str | None = None
) -> dict[str, str]:
    """写入证据池资产目录；返回 md / json 路径。"""
    report = build_report(evidence, generated_at=generated_at)
    stem = assets.next_asset_stem(
        str(report.get("direction") or "证据池"), kind="evidence", profile_name=profile_name
    )
    md_path = assets.write_asset_text(
        "evidence", profile_name, f"{stem}.md", render_markdown(report), encoding="utf-8-sig"
    )
    json_path = assets.write_asset_text(
        "evidence",
        profile_name,
        f"{stem}.json",
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return {"md": str(md_path), "json": str(json_path)}


def _confidence_text(value: Any) -> str:
    return _CONFIDENCE_LABELS.get(str(value), str(value or "未知"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clip(text: Any, limit: int = 160) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit] + "…"


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _md_link(label: Any, url: Any) -> str:
    text = _md_cell(label)
    href = str(url or "").strip()
    if not href:
        return text
    return f"[{text}]({href.replace(')', '%29')})"


__all__ = ["build_report", "render_markdown", "save_report"]
