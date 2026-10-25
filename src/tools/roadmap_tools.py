"""路线图生成、硬校验与计划导入 MCP 工具。"""

from __future__ import annotations

import json
from datetime import datetime

from ..mcp_app import mcp
from .dashboard import render_roadmap_map as _render_roadmap_map, write_html as _write_html
from .errors import InvalidJsonError, error_response
from .methodology import build_methodology_context
from .profile import load_profile, save_plan_snapshot, save_profile
from .roadmap import format_roadmap, parse_roadmap
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def generate_roadmap() -> str:
    """基于差距分析生成分阶段职业路线图。

    返回方法论上下文。LLM 按照方法论指引，结合差距分析结果，
    设计分阶段路线图，然后调用 save_roadmap(roadmap_json) 保存。

    前置条件：差距分析已完成（save_gap_analysis 已调用）。
    后续步骤：LLM 生成路线图后调用 save_roadmap，然后调用 generate_tasks。
    """
    profile = load_profile()

    if not profile.gap:
        return error_response(
            "MISSING_DATA",
            "请先调用 analyze_gaps 完成差距分析，再生成路线图。",
            {"missing": "gap"},
        )

    ctx = build_methodology_context("roadmap", profile)

    return _json({
        "next_steps": ["save_roadmap", "generate_tasks"],
        "methodology": ctx["methodology"],
        "profile": ctx["profile"],
        "step_template": [
            {
                "step": 1,
                "name": "起点判定",
                "action": "用 roadmap.yaml 的 start_level_rubric 打分表逐维度评分（学历/实习/协作/技能/项目），"
                          "加权求总分映射档位（大厂/中厂/小厂/暂不可入），输出各维度得分 + 判定依据",
                "output": {"start_level": "档位", "dimension_scores": {"education": 0, "internship": 0, "collaboration": 0, "skill_depth": 0, "project_complexity": 0}, "rationale": "为什么是这个档位"},
                "checkpoint": True,
                "checkpoint_note": "把起点层级展示给用户确认后再进下一步",
            },
            {
                "step": 2,
                "name": "目标拆解",
                "action": "从 want/target_jd 提取目标角色与目标公司层级，计算与 start_level 的跨度，得出过渡级数",
                "output": {"target_role": "", "target_level": "大厂/中厂/小厂", "level_gap": 0, "transition_stages_needed": 0},
                "checkpoint": False,
            },
            {
                "step": 3,
                "name": "阶段序列设计",
                "action": "按起点→目标设计阶段序列（learn/project/intern/...），遵守层级连续铁律："
                          "intern 目标层级 ≤ start_level+1，跨越必须插过渡阶段。每阶段标注类型/目标/对齐层级/过渡理由",
                "output": {"phases_sequence": [{"type": "", "name": "", "target_level": "", "transition_reason": ""}]},
                "checkpoint": True,
                "checkpoint_note": "把阶段序列展示给用户确认后再逐阶段细化",
            },
            {
                "step": 4,
                "name": "逐阶段深入细化",
                "action": "对每个阶段深入展开，不是列名式走过场：KPI（量化+验证证据）、里程碑（2-3 个带完成标准）、"
                          "任务（一次坐下可完成粒度）、jd 三件套（company/rationale 常识可写，jd/jd_status 真实数据才填）",
                "output": "完整 roadmap JSON（strategy_summary + phases，符合 roadmap.yaml output_schema）",
                "checkpoint": False,
            },
            {
                "step": 5,
                "name": "审计",
                "action": "调用 career-roadmap-auditor（独立审计角色）按 roadmap.yaml audit_checklist 逐项检查完整雏形，"
                          "输出 PASS/FAIL + 修正项；FAIL 打回步骤 4 修正，重审 ≤2 轮；仍 FAIL 则明示未通过项请用户决定",
                "output": {"verdict": "PASS/FAIL", "issues": [{"checklist_id": "", "problem": "", "fix": ""}]},
                "checkpoint": False,
            },
            {
                "step": 6,
                "name": "定稿交付",
                "action": "一次性展示全流程雏形（所有阶段/目标/KPI/里程碑/顺序理由），用户确认后调用 save_roadmap(roadmap_json)",
                "output": "save_roadmap(roadmap_json)",
                "checkpoint": True,
                "checkpoint_note": "用户确认整份路线图后才定稿保存",
            },
        ],
        "instructions": (
            "请严格按照 step_template 的 6 步分步执行，禁止一步到位。\n"
            "1. 每步必须产出该步的 output 结构后再进入下一步\n"
            "2. checkpoint=true 的步骤必须先把中间产物展示给用户确认，确认后再继续\n"
            "3. 步骤 1 用 roadmap.yaml 的 start_level_rubric 打分表判定，不是直觉\n"
            "4. 步骤 5 必须调用 career-roadmap-auditor 审计，审计通过才算定稿候选\n"
            "5. 过程中需要真实岗位数据时用 fetch_company_jobs / fetch_jd_detail 获取，"
            "拿不到就 jd 占位（pending_user_import），绝不编造\n"
            "6. 最终调用 save_roadmap(roadmap_json) 保存"
        ),
    })


_LEVEL_ORDER = {"暂不可入": 0, "小厂": 1, "中厂": 2, "大厂": 3}


def _level_rank(level: str) -> int:
    """企业层级档位转数值，用于层级连续校验。未知档位返回 -1（跳过校验）。"""
    return _LEVEL_ORDER.get(level, -1)


def _check_roadmap_hard(parsed: dict, profile) -> list[str]:
    """save_roadmap 硬校验：有数据才挡，无数据放行。

    检查：起点对齐 / 层级连续 / 届别匹配 / 必填字段。
    返回问题列表（空 = 通过）。只收集问题，由 save_roadmap 决定是否拒绝。
    """
    issues: list[str] = []
    roadmap = parsed.get("roadmap", parsed)
    phases = roadmap.get("phases", [])

    # 起点层级：优先从本次路线图自带的 start_level，否则从 gap 读
    start_level = roadmap.get("start_level", "") or (profile.gap or {}).get("start_level", "")
    start_rank = _level_rank(start_level)

    # 必填字段检查（learn 外的阶段必须有 resume_value；每阶段 KPI 必须有 metric+target）
    for phase in phases:
        phase_type = phase.get("type", "learn")
        name = phase.get("name", phase.get("id", "?"))
        if phase_type != "learn" and not phase.get("resume_value"):
            issues.append(f"阶段「{name}」类型为 {phase_type}，必须有 resume_value（如何写到简历上）")
        kpi = phase.get("kpi") or {}
        if isinstance(kpi, dict) and not (kpi.get("metric") and kpi.get("target")):
            issues.append(f"阶段「{name}」的 KPI 缺少量化指标（metric）或目标值（target）——不能是'学会'这种模糊表述")

    # 层级连续：intern 阶段 target_level ≤ start_level+1（start_level 未知时跳过）
    if start_rank >= 0:
        for phase in phases:
            phase_type = phase.get("type", "learn")
            if phase_type != "intern":
                continue
            target_level = phase.get("target_level", "")
            target_rank = _level_rank(target_level)
            if target_rank < 0:
                continue
            name = phase.get("name", phase.get("id", "?"))
            if target_rank > start_rank + 1:
                issues.append(
                    f"阶段「{name}」目标层级「{target_level}」超出起点「{start_level}」+1 的连续范围——"
                    "跨越层级必须插入过渡阶段（先进可进入的中小厂攒经历）"
                )
            elif target_rank > start_rank:
                issues.append(
                    f"阶段「{name}」目标层级「{target_level}」高于起点「{start_level}」——"
                    "请确认这是有过渡铺垫的合理进阶，而非直接跳级"
                )

    # 届别匹配：阶段 graduation_year（面向届）与用户毕业届比对
    graduation_year = (profile.who or {}).get("graduation_year", "")
    for phase in phases:
        target_year = phase.get("graduation_year", "")
        if not graduation_year or not target_year:
            continue
        name = phase.get("name", phase.get("id", "?"))
        try:
            if int(target_year) < int(graduation_year):
                issues.append(
                    f"阶段「{name}」面向届 {target_year} 早于用户毕业届 {graduation_year}——"
                    "用户投不进的届别岗位不应排在路线图里"
                )
        except (TypeError, ValueError):
            continue

    return issues


@mcp.tool()
def save_roadmap(roadmap_json: str) -> str:
    """保存路线图到档案。

    Args:
        roadmap_json: 路线图的 JSON 字符串

    Schema（与 sop/roadmap.yaml 一致）:
        {
            "strategy_summary": "整体策略说明",
            "phases": [                  // 阶段列表
                {
                    "type": "learn",              // learn/project/intern/research
                    "name": "基础学习",           // 阶段名称
                    "goal": "掌握基础",           // 阶段目标
                    "kpi": {"metric": "...", "target": "...", "evidence": "..."},
                    "resume_value": "",           // project/intern/research 必填
                    "company": "XX公司",           // 目标公司名（公开常识，可直接写）
                    "rationale": "对双非友好",     // 推荐理由
                    "jd": null,                    // 具体 JD 细节——有真实数据（抓取/导入）才填
                    "jd_status": "not_required",   // has_jd / pending_user_import / not_required
                    "confirmed": false,            // 用户已确认「先占位后补JD」
                    "milestones": [               // 里程碑列表
                        {
                            "name": "Python 基础",        // 里程碑名称
                            "done_criteria": "能独立写出...", // 完成标准
                            "deliverable": "",             // 交付物
                            "tasks": [                     // 任务列表
                                {
                                    "name": "学习装饰器",      // 任务名称
                                    "description": "...",     // 可选
                                    "priority": "high"        // 可选
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    注意：
    - 不要输出任何时长类字段（duration/estimated_days 等），产品不规划时间。
    - 知识光谱纪律：公司名是常识可自由写；JD 细节必须有真实数据，拿不到就 jd 置空 +
      jd_status=pending_user_import，用户确认后 confirmed 置 true。
    - 软校验：jd 有内容但无依据 / 占位未确认的阶段会在返回值中给出「依据待确认」清单，
      不会拒绝保存——请向用户确认后再定稿。
    """
    try:
        roadmap_data = _parse_json_param(roadmap_json, "路线图")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    profile = load_profile()

    # 保存旧版本快照
    if profile.plan:
        save_plan_snapshot(source="before_roadmap")

    # 解析并写入 plan；新路线图 = 新阶段体系，历史审计记录作废
    parsed = parse_roadmap(json.dumps(roadmap_data, ensure_ascii=False))
    profile.plan = parsed
    profile.audited_phases = []
    profile.plan_saved_at = datetime.now().isoformat()
    profile.section_updated_at["plan"] = profile.plan_saved_at
    profile.touch()
    save_profile(profile)

    # 保存新版本快照
    save_plan_snapshot(source="roadmap_generated")

    # 格式化报告
    report = format_roadmap(parsed)

    # 软校验：jd 三件套约束（不拒绝保存，仅提示确认）
    warnings_list = []
    for phase in parsed.get("roadmap", parsed).get("phases", []):
        phase_type = phase.get("type", "learn")
        if phase_type == "learn":
            continue
        jd_status = phase.get("jd_status", "not_required")
        jd = phase.get("jd")
        name = phase.get("name", phase.get("id", "?"))

        if jd and jd_status != "has_jd":
            warnings_list.append(
                f"阶段「{name}」填了 JD 细节但 jd_status={jd_status}——请确认这些要求来自真实数据"
                "（抓取/导入），属实则改为 has_jd"
            )
        elif not jd and jd_status == "has_jd":
            warnings_list.append(
                f"阶段「{name}」标注 has_jd 但 jd 为空——请补上真实 JD 细节或改为占位"
            )
        elif jd_status == "pending_user_import" and not phase.get("confirmed"):
            warnings_list.append(
                f"阶段「{name}」是占位（待导入真实 JD），尚未得到用户确认——"
                "请向用户确认「先占位后补 JD」；确认后把 confirmed 置 true 再保存可消除本提示"
            )

    # 硬校验：有数据才挡，无数据放行（起点对齐/层级连续/届别匹配/必填字段）
    hard_issues = _check_roadmap_hard(parsed, profile)

    # 定稿即交付：自动生成路线图活地图 HTML（随时可重新生成）
    map_path = ""
    try:
        map_html = _render_roadmap_map(profile)
        map_path = _write_html(map_html, "career_kit_roadmap.html")
    except Exception:
        map_path = ""

    warnings_text = ""
    if warnings_list:
        warnings_text = "\n\n 依据待确认：\n" + "\n".join(f"- {w}" for w in warnings_list)

    hard_text = ""
    if hard_issues:
        hard_text = (
            "\n\n 质量硬校验（起点/层级/届别/必填）需修复：\n"
            + "\n".join(f"- {i}" for i in hard_issues)
            + "\n（已保存，但建议用 career-roadmap-auditor 审计并按修正项迭代后再定稿）"
        )

    return _json({
        "message": (
            f"路线图已保存。\n\n{report}{hard_text}{warnings_text}\n\n"
            f"路线图 HTML 已生成：{map_path}（双击即看，可随时用 export_dashboard(mode=\"roadmap\") 重新生成）\n\n"
            "接下来调用 generate_tasks 生成任务列表；生成后引导用户按路线图开始第一阶段执行"
            "（或先 detail_current_phase 细化当前阶段的打卡路线）。"
        ),
        "next_steps": ["generate_tasks"],
        "context": {
            "phase": "roadmap_saved",
            "version": profile.version,
            "jd_warnings": warnings_list,
            "hard_issues": hard_issues,
        },
    })
