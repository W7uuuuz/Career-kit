"""目标探索与差距分析 MCP 工具。"""

from __future__ import annotations

from ..mcp_app import mcp
from ..models import JourneyEntry
from .errors import InvalidJsonError, error_response
from .gap_analyzer import format_gap_report
from .methodology import build_methodology_context
from .probing import (
    SELF_ASSESSMENT_INSTRUCTIONS,
    ai_authored_skill_names,
    collect_skills as _collect_skills,
    find_self_assessment_issues,
    is_verified_skill,
)
from .profile import load_profile, save_profile
from .session_tools import _has_goal, _summarize_dict
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def explore_goals() -> str:
    """目标选择——用户没有明确职业方向时，通过对话探索并选定目标。

    返回方法论上下文。LLM 按照方法论指引，用三轴定位（能力轴=have ×
    兴趣轴=对话挖掘 × 市场轴=fetch_company_jobs 真实数据）提出 2-3 个候选
    方向（带假设与 Fit Filters），引导用户选择，最后用 intake(section="want")
    落定目标。

    何时调用：
    - 用户说「我不知道想做什么」/「帮我选方向」/ 完全没有目标时
    - 建档后发现 want 为空或方向模糊（如只有「想转行」没有具体目标）

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
            f"档案中已有目标：{want_summary}\n\n"
            "如果用户只是想把现有规划继续推进，直接走 analyze_gaps 即可，无需 explore_goals。\n"
            "如果用户明确想换个方向（如「我之前选的不合适」），则继续本流程重新探索，"
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
        "再想想你明确不想做什么，这两点比「热门行业」更有用。"
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
            "3. 用 search_cases / fetch_company_jobs 抓真实岗位与同背景案例支撑候选方向，"
            "绝不用 LLM 知识编造「热门方向」\n"
            "4. 主动给出 2-3 个候选方向（标注假设 + Fit Filters + 零基础友好度），让用户纠正\n"
            "5. 对锁定方向给出三档目标（冲/稳/保）：挑战档=比当前能力高一档需补短板，"
            "一般档=经路线图提升后大概率够到，兜底档=当前即可覆盖的下限；"
            "每档给具体公司+岗位，难度依据来自真实 JD 要求、薪资来自含薪来源；"
            "无真实数据就如实标注缺失，绝不编造，允许用户按档组合选择\n"
            "6. 引导用户选择（1-10 打分），选定后用 intake(section='want') 写入档案，"
            "如实记录 experience_level（含选定的目标档位）\n"
            "7. 提示用户可继续 analyze_gaps 差距分析；方向不合适可随时回来重新探索\n\n"
            "步骤预告用得像菜单：候选方向定下来前要抓真实数据支撑——"
            "先告诉用户「接下来我会：① 摸现状 → ② 用 search_cases 搜同背景案例佐证方向 "
            "（成功经验打分带学历标签）→ ③ 出候选方向让挑」，让用户对等待有心理预期"
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
    # 避免对「无目标」做差距分析产出无意义报告
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
        or any(is_verified_skill(s) for s in skills)
    )
    if skills and not has_evidence and not profile.probe_skipped:
        return error_response(
            "PROBING_REQUIRED",
            "档案中的技能没有用户确认过的证据，摸排是硬性必选步骤：\n"
            "请先对关键技能逐项向用户求证（独立完成/讲难点/掌握程度），"
            "写入 user_verified=true 的证据后再分析。\n"
            "不能以 confidence=高 或 evidence 照抄简历绕过。\n\n"
            f"{SELF_ASSESSMENT_INSTRUCTIONS}\n\n"
            "唯一跳过方式：用户明确表示不需要摸排时，重新 finalize_profile(skip_probing=True) "
            "再继续分析。",
            {"needs_probe": True, "skip_via": "finalize_profile(skip_probing=True)"},
        )

    # 摸排硬门禁（BUG-021 双保险）：缺作者身份/把控度自评时同样拒绝分析
    self_issues = find_self_assessment_issues(have)
    if skills and self_issues and not profile.probe_skipped:
        return error_response(
            "PROBING_REQUIRED",
            "档案技能缺「作者身份与把控度自评」——AI 编程时代「独立完成」"
            "可能是「AI 生成+人工验证」，不校准会系统性高估手写能力：\n"
            + "\n".join(f"- {i}" for i in self_issues)
            + f"\n\n{SELF_ASSESSMENT_INSTRUCTIONS}\n\n"
            "补齐后重新 finalize_profile（或用户明确跳过时 skip_probing=True，留痕）。",
            {
                "needs_probe": True,
                "missing": self_issues,
                "skip_via": "finalize_profile(skip_probing=True)",
            },
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
        "step_template": [
            {
                "step": 1,
                "name": "现状盘点",
                "action": "用大白话把档案的真实水平讲给用户：届别/城市/目标；技能清单及逐项把控度"
                          "（authorship 分布要点名哪些是 AI 生成/辅助——AI 编程时代这是最关键的背景项）；"
                          "简历信任度（self_assessment）。不倒字段名，这是用户第一次看清自己的真实状况",
                "output": {
                    "goal": "目标岗位与公司",
                    "have_summary": "技能与经历一句话盘点",
                    "authorship_dist": {"self_written": 0, "ai_assisted": 0, "ai_generated": 0, "referenced": 0},
                    "weakest": "把控度最低的技能及影响",
                },
                "checkpoint": True,
                "checkpoint_note": "展示现状后等用户认领/纠正，再开始搜寻案例",
            },
            {
                "step": 2,
                "name": "读取调研",
                "action": "档案已有市场调研（profile.research）时直接引用：把调研里的"
                          "岗位样本与同背景案例按来源展示给用户（每条标来源平台/url/时间/学历标签），"
                          "不得重复全量抓取；个别不足用 search_cases 定向补充。"
                          "档案还没有调研时，先给用户一句软提示（下轮回复建议先走"
                          " research_market → gather_research_data，报告会落盘可查证），"
                          "用户不愿意就当场用 search_cases 搜集案例顶上——"
                          "展示时必须如实说明「这批是临时搜的，正式调研报告还没有」；"
                          "抓不到或全源失败就把现状如实报给用户并引导补充材料，绝不编造",
                "output": {
                    "cases_shown": 0,
                    "research_used": False,
                    "success_experience": 0,
                    "interview_requirements": 0,
                    "common_requirements": "从案例提炼的共性要求",
                    "missing": "失败/缺失来源的如实说明",
                },
                "checkpoint": False,
                "checkpoint_note": "展示搜寻结果后无异议直接进分析；用户要补充案例就停下来",
            },
            {
                "step": 3,
                "name": "两维分析",
                "action": "先用两句话告诉用户方法论：为什么从「简历过筛」和「面试通过」两个维度看差距"
                          "（一个决定能不能被看见，一个决定能不能被选中）；然后基于真实数据逐维输出分析，"
                          "每个表格/清单必须带「为什么」和依据（来源的 JD/案例/用户自评），"
                          "AI 作者身份技能按把控度分层",
                "output": {
                    "screening_findings": [{"finding": "", "why": "", "evidence": ""}],
                    "interview_findings": [{"finding": "", "why": "", "evidence": ""}],
                    "match_score_draft": 0,
                },
                "checkpoint": False,
                "checkpoint_note": "讲清「为什么」即可继续，无需用户逐项确认",
            },
            {
                "step": 4,
                "name": "结果预览与定稿",
                "action": "把完整差距分析预览给用户：打分表（各维度分+扣分依据）、差距表、风险清单、"
                          "优先行动；用户确认后调用 save_gap_analysis(gap_json)；有异议先修正再保存",
                "output": "save_gap_analysis(gap_json)",
                "checkpoint": True,
                "checkpoint_note": "用户看过预览确认后才落盘；落盘后引导 generate_roadmap",
            },
        ],
        "instructions": (
            "步骤预告（提高心理预期）：第一轮回复先向用户报完整菜单——"
            "「我现在做 4 步：① 现状盘点 ② 读取调研（引用你的市场调研报告）"
            "③ 两维分析 ④ 结果预览，你确认后落盘」——报完再动手，禁止无预告直接执行。\n"
            "播报三件套：每个工具调用前说「做什么 + 大约多久 + 你会看到什么」"
            "（案例搜寻约十几秒）——全程禁止静默连调工具。\n"
            "请严格按 step_template 的 4 步顺序执行，禁止一步到位，"
            "每步必须产生用户看得见的输出：\n"
            "1. step 1 现状盘点（等用户认领/纠正）后再进入读取调研\n"
            "2. step 2 读取调研：档案 research 有报告（research.report_md 非空）就直接引用——"
            "   把岗位样本与同背景案例按来源展示（标来源/学历标签/抓取时间），不得重复全量抓取，"
            "   不足处用 search_cases 定向补充；没有调研报告则先给一句软提示"
            "   （建议先 research_market → gather_research_data，报告落盘可查证），"
            "   用户不愿意再当场 search_cases 兜底——并如实说明「正式调研报告还没有，这是临时搜的」；\n"
            "   注意：若会话中没有 search_cases 工具（可能连了错误实例），岗位/案例样本不足时\n"
            "   必须明确降级——在分析结果里标注「案例对标数据缺口」，禁止静默跳过或编造案例；\n"
            "3. step 3 分析前先核对 have 技能的作者身份与把控度（authorship / control_level）：\n"
            "   - authorship=ai_assisted/ai_generated 或 control_level<6 的技能是\n"
            "     「能讲清架构、能驱动验证」而非「能手写」——不得在 strengths 里赋予\n"
            "     「可手撕源码级」的面试深度，match_score 按自评校准后的真实水平评估；\n"
            "   - 存在这类技能时：skill_gaps 必须新增「手写实现/现场逐行讲解」类差距\n"
            "     （source 标「用户自评」），resume_red_flags 必须新增「代码主要 AI 生成」\n"
            "     条目（signal/risk/evidence_fix 三件套），interview_preparation.must_prepare\n"
            "     按把控度分层（先补能逐行讲清，再冲源码级）——质量门会硬检查 AI 作者身份风险；\n"
            "   - 不贬损 AI-native 工程价值：生产落地、验证迭代照常计入优势，\n"
            "     目标 JD 的 AI 编码工具加分项照常对齐；\n"
            "   - 未经用户确认（无 user_verified）的技能先追问证据（做过什么项目/讲一个难点）\n"
            "     再分析，避免基于简历字面水平做系统性失真判断\n"
            "4. 每条 skill_gaps 必须带 source（真实数据来源：抓取的 JD / 导入材料 / 用户自评），\n"
            "   match_score 为 0-100；save_gap_analysis 有内容质量门，无依据/编造的结果会被拒绝\n"
            "5. 所有表格/清单必须带「为什么」：只给结论不给依据的分析不完整，会被用户看不懂\n"
            "6. step 4 的结果预览用户确认后，调用 save_gap_analysis(gap_json) 保存结构化结果"
        ),
    })


def _validate_gap_content(gap_data: dict, have: dict) -> list[str]:
    """差距分析内容质量门（BUG-002/003 收尾）：把「不编造真实数据」落成代码。

    结构校验由 _parse_json_param / format_gap_report 负责（能否解析、能否渲染）；
    此处只挡内容性缺陷，是 MCP 层对 LLM 输出的硬约束：
    - match_score 必须是 0-100 的数字（不能缺、不能是乱值）
    - skill_gaps 非空，且每条必须有 skill 与 source（真实数据来源）
    - resume_red_flags（若提供）每条必须有 signal / risk / evidence_fix
    - 技能 authorship 为 ai_assisted/ai_generated 时（BUG-021），resume_red_flags
      必须含「AI 生成/手写」相关风险条目——AI 作者身份风险不得静默吞掉
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

    # BUG-021 轻量门：AI 作者身份风险必须显式进 red_flags，不得静默吞掉
    issues.extend(_ai_authorship_flag_issues(gap_data, ai_authored_skill_names(have)))

    return issues


def _ai_authorship_flag_issues(gap_data: dict, ai_names: list[str]) -> list[str]:
    """BUG-021 轻量门：AI 生成/辅助技能的作者身份风险必须显式进 red_flags。

    关键词命中要求宽（AI/手写/生成任一），只在存量技能确有 ai_* 标记时触发，
    误伤面小；目的是防止 LLM 把「代码主要 AI 生成」这个最大面试风险静默消化。
    """
    if not ai_names:
        return []
    red_flags = gap_data.get("resume_red_flags") or []
    if not isinstance(red_flags, list):
        return ["resume_red_flags 必须是数组——AI 作者身份风险需要显式条目承载"]
    combined = "".join(
        str(rf.get(k, ""))
        for rf in red_flags if isinstance(rf, dict)
        for k in ("signal", "risk", "evidence_fix", "narrative_fix")
    )
    if "AI" in combined or "手写" in combined or "生成" in combined:
        return []
    return [
        "技能 " + "、".join(ai_names) +
        " 的 authorship 为 AI 生成/辅助，但 resume_red_flags 没有含「AI 生成/手写」"
        "的风险条目——不得静默消化作者身份风险，必须显式给出面试应对"
    ]


@mcp.tool()
def save_gap_analysis(gap_json: str) -> str:
    """保存差距分析结果。

    何时调用：在 analyze_gaps 返回分析任务，LLM 完成分析后调用此工具保存结果。

    Args:
        gap_json: 差距分析的 JSON 字符串

    Schema（与 sop/resume_screening.yaml 的 output_schema 一致——以该 YAML 为唯一权威）:
        {
            "match_score": 65,            // 匹配度评分（0-100）
            "match_level": "partial_match",
            "start_level": "小厂",         // 起点层级：大厂/中厂/小厂/暂不可入（路线图使用）
            "strengths": [                // 优势（对象数组）
                {
                    "area": "前端开发",             // 领域
                    "description": "1年经验",       // 描述
                    "resume_highlight": "...",      // 可选：简历怎么写
                    "interview_talk": "..."         // 可选：面试怎么讲
                }
            ],
            "resume_red_flags": [         // 简历负面信号（可选但强烈建议提供）
                {
                    "signal": "代码主要 AI 生成",   // 负面信号
                    "risk": "现场手撕代码站不住",   // 风险说明
                    "evidence_fix": "补 2 个完整手写项目"  // 补证据动作
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
                "study_plan": {"unit_1": ["..."], "unit_2": ["..."]}   // 学习单元（不排时间，不用 week）
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
    - 技能 authorship 为 ai_assisted/ai_generated 时，resume_red_flags 必须有
      「AI 生成/手写」相关风险条目——AI 作者身份风险不得静默吞掉
    """
    try:
        gap_data = _parse_json_param(gap_json, "差距分析")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    profile = load_profile()

    # 内容质量门（BUG-002/003 收尾）：结构合法还不够——无依据/编造的内容一律拒绝落盘
    content_issues = _validate_gap_content(gap_data, profile.have or {})
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

    profile.gap = gap_data
    profile.gap_stale_at = ""  # 新分析覆盖旧 JD 的过期标记
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
