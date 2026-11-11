"""路线图解析与格式化——将 LLM 输出解析为结构化路线图并格式化展示。

任务 schema 与 sop/roadmap.yaml 一致：{name, description, priority}。
阶段 id 由本模块规范化（phase_N），是任务生成与阶段审计的唯一来源。
产品不规划时间：路线图不含时长字段，只定义顺序与完成标准。
"""

from __future__ import annotations

import json
from typing import Any

from ..guidance import phase_type_label
from .tool_helpers import _json_candidates


def parse_roadmap(llm_response: str) -> dict[str, Any]:
    """解析 LLM 输出为结构化路线图。

    解析策略链（原文 → markdown 围栏 → 首个平衡对象）由 tool_helpers 提供；
    全部失败时降级为 raw_roadmap，不抛异常、不产生半成品。

    Args:
        llm_response: LLM 的原始输出

    Returns:
        结构化的路线图 dict，可直接写入 profile.plan
    """
    result: dict[str, Any] | None = None
    for candidate in _json_candidates(llm_response):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            result = parsed
            break

    if result is None:
        return {
            "raw_roadmap": llm_response,
            "roadmap": {
                "strategy_summary": "（解析失败，请查看 raw_roadmap）",
                "phases": [],
            },
        }

    # 确保结构完整
    if "roadmap" not in result:
        result = {"roadmap": result}

    roadmap = result["roadmap"]
    roadmap.pop("total_duration", None)  # 产品不规划时间
    roadmap.setdefault("strategy_summary", "")
    roadmap.setdefault("phases", [])

    # 确保每个 phase 有必要字段；id 统一为 phase_N，作为任务与审计的关联键
    for idx, phase in enumerate(roadmap["phases"]):
        phase["id"] = f"phase_{idx + 1}"
        phase.setdefault("type", "learn")
        phase.setdefault("name", "")
        phase.setdefault("goal", "")
        phase.setdefault("kpi", {"metric": "", "target": "", "evidence": ""})
        phase.setdefault("resume_value", "")
        phase.setdefault("milestones", [])

        # jd 三件套（知识光谱）：
        # company/rationale 是公开常识可自由写；jd 是时效事实，有真实数据才填。
        # jd_status 默认按类型推断：intern 无标注视为待导入占位，其余无需 JD。
        phase.setdefault("company", "")
        phase.setdefault("rationale", "")
        phase.setdefault("jd", None)
        phase.setdefault("confirmed", False)
        if "jd_status" not in phase:
            phase["jd_status"] = "pending_user_import" if phase["type"] == "intern" else "not_required"

        # 通道现实：主通道 / 保底 / 转正风险 / 时间窗口 / 决策门 / 引用。
        phase.setdefault("access_paths", [])
        phase.setdefault("fallback_paths", [])
        phase.setdefault("conversion_risk", {})
        phase.setdefault("time_window", {})
        phase.setdefault("decision_gate", {})
        phase.setdefault("claims", [])

        for ms_idx, ms in enumerate(phase["milestones"]):
            ms["id"] = f"phase_{idx + 1}_ms_{ms_idx + 1}"
            ms.setdefault("name", "")
            ms.setdefault("tasks", [])
            ms.setdefault("deliverable", "")
            ms.setdefault("done_criteria", "")

            for task in ms["tasks"]:
                task.setdefault("name", "")
                task.setdefault("description", "")
                task.setdefault("priority", "medium")

    return result


def _claim_map(claims: Any) -> dict[str, dict]:
    """把 Claim 对象或字典统一成 id -> dict，供路线图渲染来源。"""
    result: dict[str, dict] = {}
    for claim in claims or []:
        if hasattr(claim, "model_dump"):
            data = claim.model_dump()
        elif isinstance(claim, dict):
            data = claim
        else:
            continue
        claim_id = str(data.get("id") or "").strip()
        if claim_id:
            result[claim_id] = data
    return result


def _path_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    channel = str(item.get("channel") or item.get("name") or "").strip()
    rationale = str(item.get("rationale") or "").strip()
    if channel and rationale:
        return f"{channel}（{rationale}）"
    return channel or rationale


def _claim_recap(claim_id: str, claims: dict[str, dict]) -> str:
    data = claims.get(claim_id)
    if not data:
        return f"{claim_id}（未找到来源）"
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    source_bits = [
        str(value).strip()
        for value in (source.get("name"), source.get("url"), source.get("date"))
        if str(value or "").strip()
    ]
    statement = str(data.get("statement") or "").strip()
    kind = str(data.get("claim_type") or "").strip()
    prefix = {"fact": "事实", "practitioner_experience": "经验", "inference": "推断"}.get(kind, kind)
    text = f"{claim_id}［{prefix}］{statement}"
    if source_bits:
        text += " — 来源：" + "，".join(source_bits)
    limitation = str(data.get("limitation") or "").strip()
    if limitation:
        text += f"（局限：{limitation}）"
    return text


def format_roadmap(roadmap_data: dict[str, Any], claims: Any = None) -> str:
    """格式化路线图为可读文本。"""
    roadmap = roadmap_data.get("roadmap", roadmap_data)
    claims_map = _claim_map(claims)
    lines = []

    strategy = roadmap.get("strategy_summary", "")

    lines.append("## 路线图")
    lines.append("")
    if strategy:
        lines.append(strategy)
        lines.append("")

    phases = roadmap.get("phases", [])
    for phase in phases:
        phase_type = phase_type_label(phase.get("type", ""))

        lines.append(f"### {phase.get('name', '')} [{phase_type}]（{phase.get('id', '')}）")
        lines.append(f"**目标**：{phase.get('goal', '')}")
        lines.append("")

        # jd 三件套展示：公司名（常识）+ 依据状态（has_jd/占位/免JD）
        company = phase.get("company", "")
        if company:
            rationale = phase.get("rationale", "")
            line = f"**目标公司**：{company}"
            if rationale:
                line += f"（{rationale}）"
            lines.append(line)

        jd_status = phase.get("jd_status", "not_required")
        confirmed = phase.get("confirmed", False)
        if jd_status == "has_jd":
            jd = phase.get("jd")
            if jd:
                if isinstance(jd, dict):
                    jd_parts = [f"{k}：{v}" for k, v in jd.items() if v]
                    lines.append(f" **JD 依据**：{'；'.join(jd_parts)[:300]}")
                else:
                    lines.append(f" **JD 依据**：{str(jd)[:300]}")
        elif jd_status == "pending_user_import":
            mark = "（已确认占位）" if confirmed else "（待用户确认）"
            lines.append(
                f"**JD 占位**{mark}——当前只有公司名，无岗位要求细节。"
                "后续自动抓取：企业适配阶段会按目标企业和你的届别补齐真实 JD；"
                "也可先用 import_jd 补充"
            )

        access_paths = [_path_text(item) for item in (phase.get("access_paths") or [])]
        access_paths = [item for item in access_paths if item]
        if access_paths:
            lines.append("**主通道**：" + "；".join(access_paths))
        fallback_paths = [_path_text(item) for item in (phase.get("fallback_paths") or [])]
        fallback_paths = [item for item in fallback_paths if item]
        if fallback_paths:
            lines.append("**保底通道**：" + "；".join(fallback_paths))

        risk = phase.get("conversion_risk")
        if isinstance(risk, dict) and (risk.get("level") or risk.get("reason")):
            level = str(risk.get("level") or "未评级").strip()
            reason = str(risk.get("reason") or "").strip()
            lines.append(f"**转正风险**：{level}" + (f"——{reason}" if reason else ""))
        elif isinstance(risk, str) and risk.strip():
            lines.append(f"**转正风险**：{risk.strip()}")

        window = phase.get("time_window")
        if isinstance(window, dict):
            window_bits = [
                str(value).strip()
                for value in (window.get("window"), window.get("deadline"), window.get("note"))
                if str(value or "").strip()
            ]
            if window_bits:
                lines.append("**时间窗口**：" + "；".join(window_bits))
        elif isinstance(window, str) and window.strip():
            lines.append(f"**时间窗口**：{window.strip()}")

        gate = phase.get("decision_gate")
        if isinstance(gate, dict):
            condition = str(gate.get("condition") or "").strip()
            action = str(gate.get("action") or "").strip()
            if condition or action:
                lines.append(
                    "**决策门**："
                    + (f"若 {condition} " if condition else "")
                    + (f"→ {action}" if action else "")
                )
        elif isinstance(gate, str) and gate.strip():
            lines.append(f"**决策门**：{gate.strip()}")

        claim_ids = [
            str(item).strip()
            for item in (phase.get("claims") or [])
            if str(item or "").strip()
        ]
        if claim_ids:
            lines.append(
                "**依据**："
                + "；".join(_claim_recap(claim_id, claims_map) for claim_id in claim_ids)
            )
        lines.append("")

        kpi = phase.get("kpi", {})
        if isinstance(kpi, dict) and kpi.get("metric"):
            lines.append(f"**KPI**：{kpi['metric']} → 目标：{kpi.get('target', '?')}")
            if kpi.get("evidence"):
                lines.append(f"**验证方式**：{kpi['evidence']}")
            lines.append("")

        resume_val = phase.get("resume_value", "")
        if resume_val:
            lines.append(f"**简历价值**：{resume_val}")
            lines.append("")

        for ms in phase.get("milestones", []):
            done_criteria = ms.get("done_criteria", "")
            header = f"**{ms.get('name', '')}**"
            if done_criteria:
                header += f"—完成标准：{done_criteria}"
            lines.append(header)

            for t in ms.get("tasks", []):
                priority_icon = {"high": "[高]", "medium": "[中]", "low": "[低]"}.get(t.get("priority", "medium"), "[中]")
                desc = f"—{t['description']}" if t.get("description") else ""
                lines.append(f"  - {priority_icon} {t.get('name', '')}{desc}")

            if ms.get("deliverable"):
                lines.append(f"   交付物：{ms['deliverable']}")
            lines.append("")

    return "\n".join(lines)
