"""目标探索与差距分析 MCP 工具。"""

from __future__ import annotations

from ..mcp_app import mcp
from ..models import JourneyEntry
from .errors import error_response
from .gap_analyzer import format_gap_report
from .methodology import build_methodology_context
from .profile import load_profile, save_profile
from .session_tools import _collect_skills, _has_goal, _summarize_dict
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def explore_goals() -> str:
    """目标选择——用户没有明确职业方向时，通过对话探索并选定目标。

    返回方法论上下文。LLM 按照方法论指引，用三轴定位（能力轴=have ×
    兴趣轴=对话挖掘 × 市场轴=fetch_company_jobs 真实数据）提出 2-3 个候选
    方向（带假设与 Fit Filters），引导用户选择，最后用 intake(section="want")
    落定目标。

    何时调用：
    - 用户说"我不知道想做什么" / "帮我选方向" / 完全没有目标时
    - 建档后发现 want 为空或方向模糊（如只有"想转行"没有具体目标）

    前置条件：档案已有 who/have（用户现状）。
    后续步骤：用户选定后 intake(section="want") 写入，然后走 analyze_gaps。
    """
    profile = load_profile()

    if not profile.who and not profile.have:
        return error_response(
            "MISSING_DATA",
            "档案中还没有现状信息（who/have）。请先调用 intake 填充你是谁、会什么，"
            "再帮你探索方向。",
            {"missing": ["who", "have"]},
        )

    # 已有实质目标时先确认：避免用户已有明确方向却被无意义地带入重新探索
    if _has_goal(profile):
        want_summary = _summarize_dict(profile.want or {})
        return (
            f" 档案中已有目标：{want_summary}\n\n"
            "如果用户只是想把现有规划继续推进，直接走 analyze_gaps 即可，无需 explore_goals。\n"
            "如果用户明确想换个方向（如'我之前选的不合适'），则继续本流程重新探索，"
            "选定后用 intake(section='want') 覆盖目标。\n"
            "请先向用户确认意图再决定下一步。"
        )

    # 加载目标选择方法论
    try:
        ctx = build_methodology_context("goal_selection", profile)
    except (FileNotFoundError, ValueError) as e:
        return error_response("MISSING_DATA", f"目标选择方法论加载失败：{e}", {})

    # 记录到 journey
    profile.append_journey(JourneyEntry(
        phase="analysis",
        decision="启动目标选择",
    ))
    save_profile(profile)

    who_text = _summarize_dict(profile.who or {}) or "尚未填写身份信息"
    skills = _collect_skills(profile.have or {})
    skill_text = "、".join(
        str(s.get("skill")) if isinstance(s, dict) else str(s) for s in skills[:5]
    ) or "尚未确认技能"
    user_summary = (
        f"你目前是：{who_text}；已确认的能力：{skill_text}。"
        "方向还没定，不急着下结论，先用真实岗位验证兴趣。"
    )
    next_question = (
        "如果不考虑现实限制，你最想做哪类工作？"
        "再想想你明确不想做什么，这两点比“热门行业”更有用。"
    )

    return _json({
        "user_summary": user_summary,
        "next_question": next_question,
        "methodology": ctx["methodology"],
        "profile": ctx["profile"],
        "existing_journey": [
            {"phase": j.phase, "decision": j.decision, "timestamp": j.timestamp}
            for j in (profile.journey or [])[-5:]
        ],
        "next_steps": ["list_data_sources", "fetch_company_jobs", "intake(section='want')"],
        "instructions": (
            "先把 user_summary 用自己的话简短告诉用户，再问 next_question；"
            "不要把 methodology 原文、Phase 编号或字段名倒给用户。\n"
            "请按照目标选择方法论指引，通过对话帮用户选定职业方向：\n"
            "1. 先用 get_workflow_status / 档案信息摸清用户现状（零基础就如实对待，不美化）\n"
            "2. 用对话挖掘兴趣轴与约束轴（Genie Goal 式提问，2-3 个问题一轮，不啰嗦）\n"
            "3. 用 list_data_sources → fetch_company_jobs 抓真实岗位数据支撑候选方向，"
            "绝不用 LLM 知识编造'热门方向'\n"
            "4. 主动给出 2-3 个候选方向（标注假设 + Fit Filters + 零基础友好度），让用户纠正\n"
            "5. 对锁定方向给出三档目标（冲/稳/保）：挑战档=比当前能力高一档需补短板，"
            "一般档=经路线图提升后大概率够到，兜底档=当前即可覆盖的下限；"
            "每档给具体公司+岗位，难度依据来自真实 JD 要求、薪资来自含薪来源；"
            "无真实数据就如实标注缺失，绝不编造，允许用户按档组合选择\n"
            "6. 引导用户选择（1-10 打分），选定后用 intake(section='want') 写入档案，"
            "如实记录 experience_level（含选定的目标档位）\n"
            "7. 提示用户可继续 analyze_gaps 差距分析；方向不合适可随时回来重新探索"
        ),
    })


@mcp.tool()
def analyze_gaps() -> str:
    """对比现状（have）与目标（want/target_jd），输出差距分析。

    返回方法论上下文。LLM 按照方法论指引，基于已抓取的真实数据
    分析差距，然后调用 save_gap_analysis(gap_json) 保存结果。

    前置条件：档案已通过 finalize_profile 确认。
    后续步骤：LLM 分析后调用 save_gap_analysis，然后调用 generate_roadmap。
    """
    profile = load_profile()

    if not profile.have and not profile.want:
        return error_response(
            "MISSING_DATA",
            "档案中缺少 have（现状）或 want（目标）信息。请先调用 intake 填充。",
            {"missing": ["have", "want"]},
        )

    # 链路守卫：没有实质目标（want 为空/仅模糊表述）时先 explore_goals，
    # 避免对"无目标"做差距分析产出无意义报告
    if not _has_goal(profile):
        return error_response(
            "MISSING_DATA",
            "档案中还没有明确的职业方向（want 为空或只有模糊表述）。",
            {
                "missing": "want",
                "suggestion": (
                    "先调用 explore_goals 用三轴定位（能力×兴趣×真实市场数据）"
                    "帮用户选定方向，再用 intake(section='want') 落定目标后重试。"
                ),
            },
        )

    # 摸排硬门禁（BUG-001 双保险）：finalize 已被跳过摸排（用户主动跳过除外）时拒绝分析。
    # confidence 自标不算证据，evidence 必须用户确认。
    have = profile.have or {}
    skills = _collect_skills(have)
    has_evidence = bool(
        have.get("evidence")
        or have.get("capability_evidence")
        or any(
            isinstance(s, dict)
            and s.get("evidence")
            and (s.get("user_verified") or s.get("verified"))
            for s in skills
        )
    )
    if skills and not has_evidence and not profile.probe_skipped:
        return error_response(
            "PROBING_REQUIRED",
            "档案中的技能没有用户确认过的证据，摸排是硬性必选步骤（BUG-001）：\n"
            "请先对关键技能逐项向用户求证（独立完成/讲难点/掌握程度），"
            "写入 user_verified=true 的证据后再分析。\n"
            "不能以 confidence=高 或 evidence 照抄简历绕过。\n"
            "唯一跳过方式：用户明确表示不需要摸排时，重新 finalize_profile(skip_probing=True) "
            "再继续分析。",
            {"needs_probe": True, "skip_via": "finalize_profile(skip_probing=True)"},
        )

    # 加载两个方法论
    ctx1 = build_methodology_context("resume_screening", profile)
    ctx2 = build_methodology_context("interview_prep", profile)

    # 记录到 journey
    profile.append_journey(JourneyEntry(
        phase="analysis",
        decision="启动差距分析",
    ))
    save_profile(profile)

    return _json({
        "next_steps": ["fetch_company_jobs", "save_gap_analysis"],
        "methodologies": [ctx1["methodology"], ctx2["methodology"]],
        "profile": ctx1["profile"],
        "existing_journey": [
            {"phase": j.phase, "decision": j.decision, "timestamp": j.timestamp}
            for j in (profile.journey or [])[-5:]
        ],
        "instructions": (
            "请按照上述方法论指引：\n"
            "1. 先用 fetch_company_jobs 搜索目标企业的真实岗位（先 list_data_sources 查看可用企业）\n"
            "2. 用 fetch_jd_detail 获取 JD 全文和同背景案例\n"
            "   —— 若抓取不可用（无网/需登录/无数据源），不要停摆：改用用户导入的 target_jd\n"
            "   （import_jd / import_jd_file）或已填 want 作为数据来源，source 标注真实出处\n"
            "3. 基于真实数据从简历过筛和面试通过两个维度分析差距\n"
            "4. 分析前先核对 have 技能的证据来源：若技能条目的 evidence 未经用户确认\n"
            "   （无 user_verified 标记），先追问证据（做过什么项目/讲一个难点）再分析，\n"
            "   避免基于简历字面水平做系统性失真判断\n"
            "5. 每条 skill_gaps 必须带 source（真实数据来源：抓取的 JD / 导入材料），\n"
            "   match_score 为 0-100；save_gap_analysis 有内容质量门，无依据/编造的结果会被拒绝\n"
            "6. 调用 save_gap_analysis(gap_json) 保存结构化结果"
        ),
    })


def _validate_gap_content(gap_data: dict) -> list[str]:
    """差距分析内容质量门（BUG-002/003 收尾）：把「不编造真实数据」落成代码。

    结构校验由 _parse_json_param / format_gap_report 负责（能否解析、能否渲染）；
    此处只挡内容性缺陷，是 MCP 层对 LLM 输出的硬约束：
    - match_score 必须是 0-100 的数字（不能缺、不能是乱值）
    - skill_gaps 非空，且每条必须有 skill 与 source（真实数据来源）
    - resume_red_flags（若提供）每条必须有 signal / risk / evidence_fix
    返回问题列表（空 = 通过）。
    """
    issues: list[str] = []

    score = gap_data.get("match_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not (0 <= score <= 100):
        issues.append(f"match_score 必须是 0-100 的数字，收到「{score}」——不能缺或写非数值")

    gaps = gap_data.get("skill_gaps")
    if not isinstance(gaps, list) or not gaps:
        issues.append("skill_gaps 不能为空——差距分析必须产出至少一条技能差距")
    else:
        for i, g in enumerate(gaps):
            if not isinstance(g, dict) or not str(g.get("skill", "")).strip():
                issues.append(f"skill_gaps[{i}] 缺 skill 字段")
                continue
            if not str(g.get("source", "")).strip():
                issues.append(
                    f"skill_gaps[{i}]「{g['skill']}」缺 source（数据来源）——"
                    "差距必须锚定真实数据（抓取/导入的 JD、用户材料），不可凭 LLM 知识编造"
                )

    red_flags = gap_data.get("resume_red_flags")
    if red_flags:
        if not isinstance(red_flags, list):
            issues.append("resume_red_flags 必须是数组")
        else:
            for i, rf in enumerate(red_flags):
                if not isinstance(rf, dict):
                    issues.append(f"resume_red_flags[{i}] 必须是对象")
                    continue
                missing = [k for k in ("signal", "risk", "evidence_fix")
                           if not str(rf.get(k, "")).strip()]
                if missing:
                    issues.append(
                        f"resume_red_flags[{i}] 缺字段 {missing}——"
                        "每条负面信号必须给出风险说明与补证据动作"
                    )

    return issues


@mcp.tool()
def save_gap_analysis(gap_json: str) -> str:
    """保存差距分析结果。

    何时调用：在 analyze_gaps 返回分析任务，LLM 完成分析后调用此工具保存结果。

    Args:
        gap_json: 差距分析的 JSON 字符串

    Schema（与 sop/resume_screening.yaml、sop/interview_prep.yaml 的 output_schema 一致）:
        {
            "match_score": 65,            // 匹配度评分（0-100）
            "match_level": "partial_match",
            "strengths": [                // 优势（对象数组）
                {
                    "area": "前端开发",             // 领域
                    "description": "1年经验",       // 描述
                    "resume_highlight": "...",      // 可选：简历怎么写
                    "interview_talk": "..."         // 可选：面试怎么讲
                }
            ],
            "resume_optimization": {      // 简历过筛维度
                "ats_keywords": ["Python", "Agent"],
                "missing_keywords": ["RAG"],
                "highlight_projects": [
                    {"project": "...", "how_to_package": "...", "quantified_result": "..."}
                ],
                "resume_tips": ["..."],
                "missing_experiences": [
                    {"experience": "...", "how_to_create": "..."}
                ]
            },
            "interview_preparation": {    // 面试通过维度
                "must_prepare": [
                    {"topic": "...", "type": "八股|项目|场景", "priority": "high",
                     "estimated_time": "...", "prepare_advice": "..."}
                ],
                "project_deep_dive": [
                    {"project": "...", "likely_questions": ["..."],
                     "key_points": ["..."], "star_story": "S:... T:... A:... R:..."}
                ],
                "system_design_topics": [{"topic": "...", "framework": "..."}],
                "behavioral_questions": [{"question": "...", "story_template": "..."}],
                "study_plan": {"week_1": ["..."], "week_2": ["..."]}
            },
            "skill_gaps": [               // 技能差距（对象数组）
                {
                    "skill": "TypeScript",
                    "priority": "high",          // high/medium/low
                    "current_level": "无",
                    "required_level": "熟练",    // 注意：字段名是 required_level
                    "is_hidden": false,          // 可选：true 表示 JD 未写但实际考核
                    "how_to_improve": "...",
                    "source": "BOSS直聘 JD"      // 数据来源，必填
                }
            ],
            "priority_actions": [         // 优先行动项（对象数组）
                {"action": "学习 TypeScript 基础", "timeline": "...", "impact": "...", "difficulty": "..."}
            ],
            "market_context": "..."       // 市场背景（来自真实抓取数据汇总）
        }

    内容质量门（硬约束，BAD 数据会被拒绝落盘）：
    - match_score 必须是 0-100 的数字
    - skill_gaps 非空，且每条必须带 source（真实数据来源，抓取/导入）
    - resume_red_flags 若提供，每条必须有 signal / risk / evidence_fix
    """
    try:
        gap_data = _parse_json_param(gap_json, "差距分析")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    # 内容质量门（BUG-002/003 收尾）：结构合法还不够——无依据/编造的内容一律拒绝落盘
    content_issues = _validate_gap_content(gap_data)
    if content_issues:
        return error_response(
            "INCOMPLETE_ANALYSIS",
            "差距分析未通过内容质量门（防止无依据/编造）：\n"
            + "\n".join(f"- {i}" for i in content_issues)
            + "\n\n差距必须锚定真实数据来源（抓取/导入的 JD、用户材料）；"
            "补齐后重新调用 save_gap_analysis。",
            {"issues": content_issues},
        )

    # 先生成报告——格式非法时在此暴露，避免把半成品写进档案
    report = format_gap_report(gap_data)

    profile = load_profile()
    profile.gap = gap_data
    profile.touch()
    save_profile(profile)

    # 记录到 journey
    profile.append_journey(JourneyEntry(
        phase="analysis",
        analysis={"match_score": gap_data.get("match_score"), "gaps_count": len(gap_data.get("skill_gaps", []))},
        decision="用户确认差距分析",
    ))
    save_profile(profile)

    return _json({
        "message": (
            f"差距分析已保存。\n\n{report}\n\n"
            "下一步：调用 generate_roadmap 生成路线图。"
        ),
        "next_steps": ["generate_roadmap"],
        "context": {
            "phase": "gap_saved",
            "match_score": gap_data.get("match_score"),
            "gaps_count": len(gap_data.get("skill_gaps", [])),
        },
    })
