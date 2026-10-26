"""路线图生成、硬校验与计划导入 MCP 工具。"""

from __future__ import annotations

import json
import re
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
                          "任务（一次坐下可完成粒度）、jd 三件套（company/rationale 常识可写，jd/jd_status 真实数据才填——"
                          "优先引用档案 research 里的调研 JD 样本与来源，不再重复抓取）",
                "output": "完整 roadmap JSON（strategy_summary + phases，符合 roadmap.yaml output_schema）",
                "checkpoint": False,
            },
            {
                "step": 5,
                "name": "审计落库",
                "action": "调用 career-roadmap-auditor（独立审计角色）按 roadmap.yaml audit_checklist 逐项检查完整雏形，"
                          "输出 PASS/FAIL + 修正项；无论结果如何立即调用 save_roadmap_audit(audit_json) 落库"
                          "（落库记录被 save_roadmap 用于定稿校验：FAIL 未复审 = 保存被拒）；"
                          "FAIL 打回步骤 4 修正，重审 ≤2 轮；仍 FAIL 则明示未通过项，"
                          "用户确认剩余风险后可 save_roadmap(force=true) 带问题定稿",
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
            "步骤预告（提高心理预期）：第一轮回复先向用户报完整菜单——"
            "「路线图分 6 步：① 起点判定 ② 目标拆解 ③ 阶段序列 ④ 逐阶段细化 "
            "⑤ 审计 ⑥ 定稿交付」——报完再动手，禁止无预告直接执行。\n"
            "播报纪律：每个工具调用前用一句话告诉用户这步在干什么——全程禁止静默连调工具。\n"
            "请严格按照 step_template 的 6 步分步执行，禁止一步到位。\n"
            "1. 每步必须产出该步的 output 结构后再进入下一步；"
            "表格/清单必须带「为什么」（拆分的依据：真实 JD 要求/差距结果/层级跨度），只给结论不给理由不完整\n"
            "2. checkpoint=true 的步骤必须先把中间产物展示给用户确认，确认后再继续\n"
            "3. 步骤 1 用 roadmap.yaml 的 start_level_rubric 打分表判定，不是直觉\n"
            "4. 步骤 5 必须调用 career-roadmap-auditor 审计并调用 save_roadmap_audit 落库，"
            "审计通过才算定稿候选（audit FAIL 未复审时 save_roadmap 会拒绝保存）\n"
            "5. 过程中需要真实岗位数据时用 search_cases / fetch_company_jobs / fetch_jd_detail 获取，"
            "拿不到就 jd 占位（pending_user_import），绝不编造\n"
            "6. 最终调用 save_roadmap(roadmap_json) 保存；定稿产物除结构化数据外还有一份"
            "路线图 HTML 活地图，交付时要向用户说明它的用途与用法（结构总览+勾选打卡，浏览器本地存进度）"
        ),
    })


_LEVEL_ORDER = {"暂不可入": 0, "小厂": 1, "中厂": 2, "大厂": 3}


def _level_rank(level: str) -> int:
    """企业层级档位转数值，用于层级连续校验。未知档位返回 -1（跳过校验）。"""
    return _LEVEL_ORDER.get(level, -1)


def _check_roadmap_hard(parsed: dict, profile) -> list[str]:
    """save_roadmap 硬校验：有数据才挡，无数据放行。

    检查：起点对齐 / 层级连续（支持每阶段 start_level_after 升级起点）/
    届别匹配 / 必填字段。合规的「起点+1」不再报警——只有 >+1 才算跳级。
    返回问题列表（空 = 通过）。只收集问题，由 save_roadmap 决定是否拒绝。
    """
    issues: list[str] = []
    roadmap = parsed.get("roadmap", parsed)
    phases = roadmap.get("phases", [])

    # 起点层级：优先从本次路线图自带的 start_level，否则从 gap 读
    start_level = roadmap.get("start_level", "") or (profile.gap or {}).get("start_level", "")
    running_rank = _level_rank(start_level)
    running_name = start_level

    # 必填字段检查（learn 外的阶段必须有 resume_value；每阶段 KPI 必须有 metric+target）
    for phase in phases:
        phase_type = phase.get("type", "learn")
        name = phase.get("name", phase.get("id", "?"))
        if phase_type != "learn" and not phase.get("resume_value"):
            issues.append(f"阶段「{name}」类型为 {phase_type}，必须有 resume_value（如何写到简历上）")
        kpi = phase.get("kpi") or {}
        if isinstance(kpi, dict) and not (kpi.get("metric") and kpi.get("target")):
            issues.append(f"阶段「{name}」的 KPI 缺少量化指标（metric）或目标值（target）——不能是「学会」这种模糊表述")

    # 层级连续（按「进入该阶段时的起点」滚动计算）：
    # 阶段可带 start_level_after（复评后升级），后续阶段按升级后的起点算，
    # 可以表达「学习中厂 → 中厂实习 → 复评升级 → 冲大厂」这类分阶段爬升路线。
    # 规则：intern 目标 ≤ 当前起点+1 直接放行；> +1 才判定跳级。
    if running_rank >= 0:
        for phase in phases:
            phase_type = phase.get("type", "learn")
            name = phase.get("name", phase.get("id", "?"))
            after = str(phase.get("start_level_after", "")).strip()
            if after and _level_rank(after) >= 0:
                running_rank = _level_rank(after)
                running_name = after
            if phase_type != "intern":
                continue
            target_level = phase.get("target_level", "")
            target_rank = _level_rank(target_level)
            if target_rank < 0:
                continue
            if target_rank > running_rank + 1:
                issues.append(
                    f"阶段「{name}」目标层级「{target_level}」超出该阶段起点「{running_name}」+1 的连续范围——"
                    "跨越层级必须插入过渡阶段（先进可进入的中小厂攒经历），"
                    "或在该阶段前显式声明升级复评（阶段字段 start_level_after）"
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

    issues.extend(_roadmap_lint_issues(phases))

    return issues


# BUG-011 roadmap lint 词典
_UMBRELLA_WORDS = ("专题", "批量", "全部", "汇总", "一批", "若干项")
_TIME_WORDS = ("每周", "每天", "每日", "一周内", "一天内", "半月内", "24小时", "24 小时", "月内", "日内")
_COUNT_RE = re.compile(r"\d+")


def _roadmap_lint_issues(phases: list) -> list[str]:
    """可执行性 lint（硬校验组成部分）：

    1. 禁伞形任务名（「按五类专题刷题」这类打卡不了的描述）
    2. 禁时间节奏词（产品不规划时间——节奏由用户自定义，不写进路线图）
    """
    issues: list[str] = []

    def _scan(phase_name: str, text: str, label: str) -> None:
        text = str(text or "")
        for w in _UMBRELLA_WORDS:
            if w in text:
                issues.append(
                    f"阶段「{phase_name}」{label}「{text}」是伞形描述——无法打卡，"
                    "请拆成一次坐下可完成的具体动作（例：「完成并发编程第 1 章 3 道题」）"
                )
                break
        for w in _TIME_WORDS:
            if w in text:
                issues.append(
                    f"阶段「{phase_name}」{label}「{text}」含时间词「{w}」——"
                    "产品不规划时间（学习单元不排期），请去掉时间约束，改用完成标准描述"
                )
                break

    for phase in phases:
        phase_name = phase.get("name", phase.get("id", "?"))

        for milestone in phase.get("milestones", []) or []:
            if not isinstance(milestone, dict):
                continue
            _scan(phase_name, milestone.get("name", ""), f"里程碑「{milestone.get('name', '')}」")
            for task in milestone.get("tasks", []) or []:
                if isinstance(task, dict):
                    _scan(phase_name, task.get("name", ""), "任务")
    return issues


def _collect_soft_reports(parsed: dict, profile) -> list[str]:
    """软提示（不拒绝保存）：层级/届别字段缺失、复评升级依赖等审计清单覆盖面。"""
    reports: list[str] = []
    roadmap = parsed.get("roadmap", parsed)
    phases = roadmap.get("phases", [])
    if phases and not any(p.get("target_level") for p in phases if isinstance(p, dict)):
        reports.append(
            "整份路线图的阶段均未声明 target_level——层级连续校验被静默跳过，"
            "请为每个阶段补 target_level（大厂/中厂/小厂/暂不可入）"
        )
    if phases and not any(p.get("graduation_year") for p in phases if isinstance(p, dict)):
        grad = (profile.who or {}).get("graduation_year", "")
        if grad:
            reports.append(
                f"各阶段均未声明 graduation_year（用户毕业届 {grad}）——"
                "届别匹配校验被静默跳过，请为投递阶段补面向届"
            )
    if any(str(p.get("start_level_after") or "").strip() for p in phases if isinstance(p, dict)):
        reports.append(
            "检测到 start_level_after（复评升级）：保存后会同步更新档案起点层级，"
            "后续校验与审计按升级后的起点计算"
        )
    if any(str(p.get("condition") or "").strip() for p in phases if isinstance(p, dict)):
        reports.append(
            "阶段带 condition（分支/备用路径）：这是受支持的表达方式——"
            "复评不达标走备用阶段的场景用 condition 写明触发条件，不再是缺陷"
        )

    # BUG-011：数字型 KPI 与任务计数闭合（软提示——机械对账只做「有没有数字」）
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        kpi = phase.get("kpi")
        target = str((kpi or {}).get("target", "")) if isinstance(kpi, dict) else ""
        if not _COUNT_RE.search(target):
            continue
        phase_name = phase.get("name", phase.get("id", "?"))
        task_names = [
            str(t.get("name", ""))
            for m in phase.get("milestones", []) or [] if isinstance(m, dict)
            for t in m.get("tasks", []) or [] if isinstance(t, dict)
        ]
        if task_names and not any(_COUNT_RE.search(n) for n in task_names):
            reports.append(
                f"阶段「{phase_name}」KPI 目标「{target}」是量化数字，但该阶段任务名都不带计数——"
                "KPI 无法在任务层面累积（例：150 题需要拆成带题量的任务），验收会落空"
            )
    return reports


@mcp.tool()
def save_roadmap(roadmap_json: str, force: bool = False) -> str:
    """保存路线图到档案。

    先校验后落盘：硬校验（起点/层级连续/届别/必填）或上一轮审计 FAIL 时
    不保存，按问题清单修正后重试；确认剩余风险后可显式传 force=true 带问题定稿。

    Args:
        roadmap_json: 路线图的 JSON 字符串
        force: 显式带问题保存（硬校验问题或审计 FAIL 时仍定稿，返回值会列明已接受的风险）

    Schema（与 sop/roadmap.yaml 一致）:
        {
            "strategy_summary": "整体策略说明",
            "start_level": "小厂",          // 可选：本次路线图使用的起点档位
            "phases": [                  // 阶段列表
                {
                    "type": "learn",              // learn/project/intern/research
                    "name": "基础学习",           // 阶段名称
                    "goal": "掌握基础",           // 阶段目标
                    "kpi": {"metric": "...", "target": "...", "evidence": "..."},
                    "resume_value": "",           // project/intern/research 必填
                    "target_level": "中厂",       // 本阶段目标层级（大厂/中厂/小厂/暂不可入），投递实习阶段必填
                    "start_level_after": "",      // 可选：复评升级后的起点档位（如 learn 阶段复评达标，后续阶段起点升为中厂）
                    "graduation_year": "",        // 可选：该阶段面向的毕业届（校招/实习阶段建议标注）
                    "condition": "",              // 可选：分支/备用路径说明（如「复评不达标则延长本阶段，改投中厂」）
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
    - 层级连续规则：intern 目标 ≤ 该阶段起点+1 直接合规（不再报警）；> +1 判跳级，
      必须插过渡阶段，或用 start_level_after 表达复评升级后的爬升。
    - 软校验：jd 有内容但无依据 / 占位未确认的阶段会在返回值中给出「依据待确认」清单，
      不会拒绝保存——请向用户确认后再定稿。
    """
    try:
        roadmap_data = _parse_json_param(roadmap_json, "路线图")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    profile = load_profile()
    parsed = parse_roadmap(json.dumps(roadmap_data, ensure_ascii=False))

    # 先校验后落盘（BUG-007）：硬校验问题或审计 FAIL 时不写档案，防止假保存
    hard_issues = _check_roadmap_hard(parsed, profile)
    audit = (profile.plan or {}).get("audit") or {}
    last_verdict = audit.get("latest_verdict") or ""

    blocking: list[str] = list(hard_issues)
    if last_verdict == "FAIL":
        blocking.insert(0,
            f"上一轮路线图审计 verdict=FAIL（{audit.get('updated_at', '')[:16]}），"
            f"{len(audit.get('latest_issues') or [])} 项未通过尚未复审计"
        )
    if blocking and not force:
        return error_response(
            "VALIDATION_FAILED",
            "路线图未通过校验，未保存（防「以为已定稿」的假保存）：\n"
            + "\n".join(f"- {b}" for b in blocking)
            + "\n\n下一动作：按问题清单修正后重新调用 save_roadmap；"
            "剩余风险已明确告知用户但仍要求定稿时，可显式传 force=true 带问题保存。",
            {
                "hard_issues": hard_issues,
                "audit": {
                    "latest_verdict": last_verdict,
                    "updated_at": audit.get("updated_at", ""),
                    "fail_rounds": audit.get("fail_rounds", 0),
                },
            },
        )

    # 复评升级写回全局起点（BUG-004 配套）：最后一次 start_level_after 作为新起点
    phases_loaded = parsed.get("roadmap", parsed).get("phases", [])
    applied_strict_after = ""
    for phase in phases_loaded:
        after = str(phase.get("start_level_after", "") or "").strip()
        if after and _level_rank(after) >= 0:
            applied_strict_after = after
    if applied_strict_after:
        if profile.gap:
            profile.gap["start_level"] = applied_strict_after
        else:
            profile.gap = {"start_level": applied_strict_after}

    # 保存旧版本快照
    if profile.plan:
        save_plan_snapshot(source="before_roadmap")

    # 解析并写入 plan；新路线图 = 新阶段体系，历史审计记录作废
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
    for phase in phases_loaded:
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

    # 软提示：层级/届别字段缺失等（审计清单覆盖面，不拒绝）
    soft_reports = _collect_soft_reports(parsed, profile)

    # 定稿即交付：自动生成路线图活地图 HTML（随时可重新生成）
    map_path = ""
    try:
        map_html = _render_roadmap_map(profile)
        map_path = _write_html(map_html, kind="roadmap")
    except Exception:
        map_path = ""

    warnings_text = ""
    if warnings_list:
        warnings_text = "\n\n依据待确认：\n" + "\n".join(f"- {w}" for w in warnings_list)

    soft_text = ""
    if soft_reports:
        soft_text = "\n\n校验提示（不阻塞，但请向用户确认）：\n" + "\n".join(f"- {s}" for s in soft_reports)

    force_text = ""
    if blocking and force:
        force_text = (
            "\n\n[force 带问题定稿] 本次保存显式接受了以下风险（已记录）：\n"
            + "\n".join(f"- {b}" for b in blocking)
            + "\n请向用户复述这些风险，避免「带病定稿」被静默当成合格版本。"
        )

    return _json({
        "message": (
            f"路线图已保存。\n\n{report}{force_text}{soft_text}{warnings_text}\n\n"
            f"路线图 HTML 已生成：{map_path}——双击即看，无需服务器；"
            "这是路线图的「活地图」（阶段/KPI/里程碑/任务全貌 + 勾选打卡，进度在浏览器本地保存），"
            "可随时用 export_dashboard(mode=\"roadmap\") 重新生成最新版。\n"
            "资产总览：双击 index.html（在 ~/CareerKit/ 下，报告/地图/仪表盘的统一入口）。\n"
            "向用户交付时先说明整条路线为什么这样排（阶段跨度/过渡理由），再给 HTML 路径。\n\n"
            "接下来调用 generate_tasks 生成任务列表；生成后引导用户按路线图开始第一阶段执行"
            "（或先 detail_current_phase 细化当前阶段的打卡路线）。"
        ),
        "next_steps": ["generate_tasks"],
        "context": {
            "phase": "roadmap_saved",
            "version": profile.version,
            "jd_warnings": warnings_list,
            "soft_reports": soft_reports,
            "accepted_risks": blocking if (blocking and force) else [],
        },
    })


@mcp.tool()
def save_roadmap_audit(audit_json: str) -> str:
    """保存路线图审计结果到档案（save_roadmap 会读取最新 verdict 决定是否放行定稿）。

    何时调用：career-roadmap-auditor 每完成一轮审计（PASS 或 FAIL）都要调用本工具落库。

    Args:
        audit_json: 审计结果的 JSON 字符串

    Schema:
        {
            "verdict": "PASS",            // PASS / FAIL（必填）
            "issues": [                   // FAIL 时必填，PASS 时留空
                {"checklist_id": "start", "problem": "起点档位无打分依据", "fix": "补 rubric 评分"}
            ],
            "summary": "一轮 FAIL：3 项待修"   // 可选：一句话结论
        }

    出口规则：同一版本累计 2 轮 FAIL 后，迭代之外还有两条出路——
    ① 修正 issues 后重审；② 向用户明示剩余未通过项与风险，用户确认后
    用 save_roadmap(force=true) 带问题定稿。禁止静默放弃或无限重审。
    """
    try:
        data = _parse_json_param(audit_json, "审计结果")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    verdict = str(data.get("verdict", "")).strip().upper()
    if verdict not in ("PASS", "FAIL"):
        return error_response(
            "INVALID_PARAM",
            f"verdict 必须是 PASS 或 FAIL，当前值：{verdict!r}",
            {"verdict": verdict},
        )
    issues = data.get("issues") or []
    if verdict == "FAIL" and not issues:
        return error_response(
            "INVALID_PARAM",
            "verdict=FAIL 时必须带 issues 明细（checklist_id/problem/fix），否则修正无从下手",
        )
    if not isinstance(issues, list):
        return error_response("INVALID_PARAM", "issues 必须是数组", {})

    profile = load_profile()
    if not (profile.plan or {}).get("roadmap"):
        return error_response(
            "MISSING_DATA",
            "档案里还没有路线图——请先 save_roadmap 保存雏形，再审计。",
            {"missing": "plan.roadmap"},
        )

    plan = profile.plan
    audit = plan.get("audit") or {"rounds": []}
    rounds = audit.get("rounds") or []
    if not isinstance(rounds, list):
        rounds = []

    now = datetime.now().isoformat()
    entry = {
        "round": len(rounds) + 1,
        "verdict": verdict,
        "issues": issues if verdict == "FAIL" else [],
        "summary": str(data.get("summary", "") or "")[:200],
        "saved_at": now,
    }
    fail_rounds = (audit.get("fail_rounds") or 0) + (1 if verdict == "FAIL" else 0)

    plan["audit"] = {
        "rounds": rounds + [entry],
        "latest_verdict": verdict,
        "latest_issues": issues if verdict == "FAIL" else [],
        "fail_rounds": fail_rounds,
        "updated_at": now,
    }
    profile.touch()
    save_profile(profile)

    lines = [
        f"审计结果已落库（第 {entry['round']} 轮，verdict={verdict}）。",
        "——save_roadmap 只认可最新这份记录：每次审计后都要重新落库，定稿校验用的就是它。",
    ]
    next_steps: list[str] = []
    if verdict == "PASS":
        lines.append("审计通过：可以调用 save_roadmap 定稿。")
        next_steps.append("save_roadmap")
    else:
        lines.append(f"累计 FAIL {fail_rounds} 轮。两条出路：① 按修正项修复后重新审计；"
                     "② 向用户明示剩余风险后用 save_roadmap(force=true) 带问题定稿（需用户确认）。")
        if fail_rounds >= 2:
            lines.append(
                "已到两轮 FAIL 口径上限：不建议第 3 轮对同一版本无限重审——"
                "要么结构性修正（重做阶段序列），要么 force 定稿并让用户签字画押剩余风险。"
            )
        for i in issues:
            if isinstance(i, dict):
                lines.append(f"- [{i.get('checklist_id', '?')}] {i.get('problem', '')} → {i.get('fix', '')}")
        next_steps.append("save_roadmap")

    return _json({
        "message": "\n".join(lines),
        "next_steps": next_steps,
        "context": {
            "round": entry["round"],
            "verdict": verdict,
            "fail_rounds": fail_rounds,
        },
    })
