"""建档与分析输入类 MCP 工具。"""

from __future__ import annotations

from datetime import datetime

from ..mcp_app import mcp
from .errors import InvalidJsonError, error_response
from .industry_state import industry_of, mark_industry_change
from .probing import (
    SELF_ASSESSMENT_INSTRUCTIONS,
    collect_skills as _collect_skills,  # noqa: F401  re-export 供 analysis_tools 兼容导入
    find_self_assessment_issues,
    is_verified_skill,
)
from .profile import get_active_profile_name, load_profile, merge_section, save_profile
from .resume_parser import extract_text
from .session import get_welcome_message
from .tool_helpers import _parse_json_param, server_fingerprint_line


@mcp.tool()
def start_session() -> str:
    """初始化新的职业规划会话。

    何时调用：用户开始新的职业规划时首先调用此工具。
    按档案状态自动分流：空档案走建档引导；已有任务的档案直接给续跑指引，
    不再把老用户当新用户重新问一遍简历和目标。

    工作流程：start_session → intake(who) → intake(have) → intake(want) → finalize_profile
    """
    profile = load_profile()
    pending = [t for t in profile.tasks if t.status != "completed"]

    if pending:
        # 续跑指引：不投放全量手册，与 get_workflow_status 方向一致（不把已有档案当空档案）
        completed = len(profile.tasks) - len(pending)
        has_gap = bool(profile.gap)
        stale_note = (
            "；目标 JD 在分析之后更新过——需先 analyze_gaps 重新分析，再考虑重新规划"
            if profile.gap_stale_at else ""
        )
        return (
            "—— 继续模式：检测到已有进行中的档案，不展示全量手册 ——\n\n"
            f"当前档案 {get_active_profile_name()}：{len(profile.tasks)} 个任务、"
            f"{len(pending)} 个未完成（已完成 {completed}）"
            + (f"；差距分析已存在（match {profile.gap.get('match_score', '?')}）" if has_gap else "")
            + stale_note
            + "\n\n本会话应从续跑开始，而不是按新用户建档：\n"
            "1. 跳过建档提问，直接调用 get_next_tasks 展示当前阶段任务，问用户想推进哪一项\n"
            "2. 用户报告完成 → checkin_task 打卡（完成即沉淀能力证据）\n"
            "3. 用户说目标变了 / 想换方向 → 按 get_workflow_status 提示重新分析规划\n"
            "4. 用户明确要重新建档 → switch_profile 或 delete_profile 后走全量手册\n"
            "5. 用户只想要市场调研概览 → research_market → gather_research_data\n\n"
            f"[服务自检] {server_fingerprint_line()}"
        )

    summary_note = ""
    if profile.summary:
        summary_note = (
            "档案摘要：" + profile.summary
            + "（续档：补齐缺失信息；已分析过的内容不要重新问）\n"
        )

    # 扫盲继续模式：用户已经看过行业快照，不再重复问“要不要扫盲”
    if (profile.want or {}).get("scan_completed_at") and not _has_goal(profile):
        scan_summary = (profile.want or {}).get("scan_summary") or []
        summary_lines = "\n".join(f"- {item}" for item in scan_summary[:5])
        return (
            "—— 扫盲继续模式：已生成行业快照，不重复抓取 ——\n\n"
            f"当前档案：{get_active_profile_name()}\n"
            f"{summary_note}"
            f"{summary_lines}\n\n"
            "下一步：先问用户「看完这些，有没有哪个方向想进一步了解？」\n"
            "有方向 → intake(section='want') 记录目标，再走 analyze_gaps；\n"
            "没方向 → 换一个方向看，或先聊兴趣和约束；不要停在知识讲解。\n"
            "扫盲不是规划门禁，用户不想继续时可直接结束。\n\n"
            f"[服务自检] {server_fingerprint_line()}"
        )

    return (
        f"{get_welcome_message()}\n\n"
        f"当前档案：{get_active_profile_name()}\n"
        f"{summary_note}"
        f"\n[服务自检] {server_fingerprint_line()}\n"
        "\n下一步：请先按第一轮规则判断用户认知，再决定是否调用 "
        "get_industry_snapshot；不要直接索要简历或目标。\n"
        '示例：intake(section="who", data=\'{"name":"张三", "education":"计算机本科"}\')'
    )


@mcp.tool()
def parse_resume(file_path: str) -> str:
    """解析简历文件，提取文本内容。支持 PDF、DOCX、Markdown、TXT 格式。

    Args:
        file_path: 简历文件的绝对路径
    """
    try:
        text = extract_text(file_path)
    except FileNotFoundError as e:
        return error_response("MISSING_DATA", str(e), {"file_path": file_path})
    except ValueError as e:
        return error_response("INVALID_JSON", str(e), {"file_path": file_path})

    return (
        f"--- RESUME CONTENT ---\n{text}\n--- END ---\n\n"
        "以上是候选素材，不是已确认的事实。\n\n"
        "**简历有美化成分——写入档案前必须先验证：**\n"
        "1. 对关键技能/项目逐项向用户求证：这个项目是不是你独立完成的？\n"
        "   团队里有没有人 review 你的代码？某个难点具体怎么解决的？\n"
        "   实际掌握到什么程度？\n\n"
        f"2. {SELF_ASSESSMENT_INSTRUCTIONS}\n\n"
        "3. 证据（evidence）必须来自用户确认，**不得照抄简历原文**；\n"
        "   未经用户确认的技能标 `verified: false`，确认过的标 `verified: true`。\n"
        "4. 学历/城市/届别等身份信息直接可用；技能与项目必须验证后再写入 have。\n\n"
        "请调用 intake 工具填充：\n"
        '- "who" section：姓名、联系方式、教育背景、当前状态\n'
        '- "have" section：技能、工作经历、项目经验、证书——每个技能条目附 '
        "evidence / user_verified / authorship / control_level，"
        "并写入 have.self_assessment 整份简历自评\n\n"
        '示例：intake(section="who", data=\'{"name":"张三", "education":"..."}\')\n'
        "下一步：自评与求证完成后调用 intake(section=\"have\")；"
        "目标明确后调用 intake(section=\"want\")。"
    )


@mcp.tool()
def intake(section: str, data: str) -> str:
    """逐步填充档案信息。

    何时调用：在 start_session 之后，根据用户描述逐步填充档案。
    每次调用填充一个 section，可以多次调用。

    Args:
        section: 填充到哪个 section，只接受 who / have / want
            - who: 你是谁（姓名、教育、状态）
            - have: 你有什么（技能、经历、资源）；关键技能请附带证据与置信度，
                并标 authorship（作者身份）+ control_level（把控度自评 0-10），
                整份简历自评写入 have.self_assessment
            - want: 你想要什么（目标岗位、行业、薪资）
                - 扫盲阶段可写 industry_id / awareness_level / scan_consent
                - 深度规划确认行业后写 industry / industry_id
        data: 用户提供的信息，必须是 JSON 对象字符串
            示例：'{"name":"张三", "education":"计算机本科", "skills":["Python", "React"]}'
            非法 JSON 会被拒绝且不写入档案
    """
    if section not in ("who", "have", "want"):
        return error_response(
            "INVALID_SECTION",
            f"section 必须是 who/have/want，收到的是「{section}」",
            {"received": section, "valid": ["who", "have", "want"]},
        )

    # 先校验再写入：坏 JSON 静默入库会污染工作流状态判定（BUG-007）
    try:
        _parse_json_param(data, f"{section} 数据")
    except InvalidJsonError as exc:
        return error_response(exc.code, exc.message, exc.details)

    before = load_profile()
    old_industry = ""
    if section == "want":
        old_industry = industry_of(before.want)
    profile = merge_section(section, data)
    result = (
        f"已记录到「{section}」。当前档案版本：v{profile.version}\n"
        "下一步：继续补齐其他 section；who/have/want 都有内容后调用 finalize_profile。"
    )

    # 行业变更：旧调研/差距/路线图不再代表新目标，标记过期由工作流提示重跑。
    if section == "want" and mark_industry_change(
        profile, old_industry, industry_of(profile.want)
    ):
        profile.touch()
        save_profile(profile)
        result += (
            "\n\n行业已变更：旧的市场调研/差距分析/路线图可能不再适用，"
            "已标记分析过期；请重新调研/分析后再规划。"
        )

    # 毕业届引导（届别校验的数据基础）：who 未含 graduation_year 时提醒补充
    if section == "who":
        who = profile.who or {}
        if not who.get("graduation_year") and not who.get("graduation"):
            result += (
                "\n\n毕业届提示：届别校验（路线图不排用户投不进的岗位）需要毕业年份。"
                "若方便请补充：intake(section='who', data='{\"graduation_year\": \"2028\"}')（如 2028 届）。"
                "不补充也不影响流程，届别校验会自动跳过。"
            )

    return result


@mcp.tool()
def finalize_profile(skip_probing: bool = False) -> str:
    """确认档案信息完整，生成摘要，解锁分析工具。

    Args:
        skip_probing: 是否跳过「简历技能摸排」（默认 False）。
            摸排是硬性必选步骤：have 有技能但无用户确认证据
            （user_verified）或缺 authorship/control_level/self_assessment 自评时，
            本工具拒绝放行，除非用户明确表示跳过，此时 LLM 传 skip_probing=True
            并记录留痕——不得以置信度高或简历字面为由自动跳过，
            也不得由 AI 代填 authorship/control_level。

    何时调用：当用户已经通过 intake 填充了 who/have/want 三个 section 后调用。
    不要在档案不完整时调用此工具。

    前置条件：至少 who/have/want 中有一个 section 有内容。
    后续步骤：调用 analyze_gaps 开始差距分析。
    """
    profile = load_profile()

    # 摸排硬门禁（BUG-001）：先检查再生成摘要——有技能但无用户确认证据时不放行
    have = profile.have or {}
    skills = _collect_skills(have)
    has_evidence = bool(
        have.get("evidence")
        or have.get("capability_evidence")
        or any(is_verified_skill(s) for s in skills)
    )
    needs_probe = bool(skills) and not has_evidence

    if needs_probe and not skip_probing:
        return error_response(
            "PROBING_REQUIRED",
            "档案中的技能没有用户确认过的证据，摸排是硬性必选步骤：\n"
            "简历有美化成分——按简历字面水平做差距分析会系统性失真，"
            "不能以 confidence=高 或 evidence 照抄简历来绕过。\n"
            "请先对关键技能逐项向用户求证：\n"
            "  1. 这个项目是不是你独立完成的？\n"
            "  2. 团队里有没有人 review 你的代码？\n"
            "  3. 某个难点具体怎么解决的？实际掌握到什么程度？\n\n"
            f"{SELF_ASSESSMENT_INSTRUCTIONS}\n\n"
            "然后把确认过的证据（evidence）写入技能条目并标 user_verified=true，"
            "同时写入 authorship / control_level 与 have.self_assessment。\n\n"
            "唯一跳过方式：用户明确表示不需要摸排时，LLM 以 finalize_profile(skip_probing=True) "
            "继续，此跳过会被记录留痕。",
            {"needs_probe": True, "skip_via": "finalize_profile(skip_probing=True)"},
        )

    # 摸排硬门禁（BUG-021 自评）：证据齐全但缺作者身份/把控度自评时仍不放行
    self_issues = find_self_assessment_issues(have)
    needs_self_assessment = bool(skills) and bool(self_issues)

    if needs_self_assessment and not skip_probing:
        return error_response(
            "PROBING_REQUIRED",
            "技能证据已确认，但缺「作者身份与把控度自评」——"
            "AI 编程时代「独立完成」可能是「AI 生成+人工验证」，"
            "按简历字面水平分析会系统性高估手写能力：\n"
            + "\n".join(f"- {i}" for i in self_issues)
            + f"\n\n{SELF_ASSESSMENT_INSTRUCTIONS}\n\n"
            "唯一跳过方式：用户明确表示不需要时 finalize_profile(skip_probing=True)（留痕）。",
            {
                "needs_probe": True,
                "missing": self_issues,
                "skip_via": "finalize_profile(skip_probing=True)",
            },
        )

    # 记录摸排状态：技能有证据 / 用户主动跳过
    if skip_probing and (needs_probe or needs_self_assessment):
        profile.probe_skipped = True
    elif not needs_probe and not needs_self_assessment:
        profile.probe_skipped = False

    # 生成简单的结构化摘要
    parts = []
    if profile.who:
        parts.append(f"身份：{_summarize_dict(profile.who)}")
    if profile.have:
        parts.append(f"现状：{_summarize_dict(profile.have)}")
    if profile.want:
        parts.append(f"目标：{_summarize_dict(profile.want)}")

    profile.summary = "；".join(parts) if parts else "（档案为空）"
    save_profile(profile)

    # 跳过留痕提示
    skip_note = ""
    if profile.probe_skipped:
        skip_note = (
            "\n\n已按用户要求跳过技能摸排（留痕）。后续分析基于未验证的简历字面水平，"
            "可能存在系统性失真——请在下游分析中对此保持谨慎。"
        )

    # 目标缺失提醒：没有明确方向时不应直接 analyze_gaps，应先 explore_goals
    goal_reminder = ""
    if not _has_goal(profile):
        goal_reminder = (
            "\n\n目标缺失：档案中还没有明确的职业方向（want 只有模糊表述或为空）。\n"
            "先调用 explore_goals 用三轴定位（能力×兴趣×真实市场数据）帮用户选定方向，"
            "再用 intake(section='want') 落定，然后才进入 analyze_gaps。"
        )

    return (
        f"档案已确认。\n\n摘要：{profile.summary}{skip_note}{goal_reminder}\n\n"
        "下一步：调用 analyze_gaps 开始差距分析。"
    )


def _summarize_dict(d: dict) -> str:
    """将字典转为简洁的文本摘要。"""
    items = [f"{k}={v}" for k, v in d.items() if k != "raw"]
    if not items and "raw" in d:
        return str(d["raw"])
    return "，".join(items)


def _has_goal(profile) -> bool:
    """是否已有可分析的实质目标（want 关键字段或 target_jd）。

    want 中的 raw（如「想转行」这种模糊表述）不算实质目标——正是 explore_goals 的场景。
    """
    want = profile.want or {}
    for key in ("target_role", "role", "position", "direction", "industry",
                "job_family", "target_company", "target_companies"):
        if want.get(key):
            return True
    return bool(profile.target_jd)


@mcp.tool()
def import_jd(jd_text: str) -> str:
    """导入目标岗位的 JD（职位描述）。

    Args:
        jd_text: JD 的结构化 JSON 文本
            示例：'{"company":"字节跳动","role":"AI Agent 工程师","requirements":["LangGraph","RAG"]}'
            空串 / 非 JSON / 非对象输入会被拒绝，不会污染档案。
    """
    # target_jd 只接受结构化 JSON（BUG-010/BUG-011）：
    # 空串、纯文本、非 dict 一律拒绝，绝不静默以 {"raw": text} 入库
    if not jd_text or not jd_text.strip():
        return error_response(
            "INVALID_JSON",
            "JD 内容为空。请提供目标岗位的 JD 文本后重试。",
            {"received": ""},
        )

    try:
        jd_data = _parse_json_param(jd_text, "JD")
    except InvalidJsonError as exc:
        return error_response(
            "INVALID_JSON",
            "JD 不是合法 JSON。请提供结构化 JD："
            '{"company":..., "role":..., "requirements":[...]}（至少含其中一项）；'
            "或将 JD 文件交给 import_jd_file 解析。",
            {"raw": str(jd_text)[:200], "parse_error": exc.message},
        )

    # 最小校验（BUG-010）：缺岗位业务字段的 JD 拒绝导入，防示例/垃圾污染 target_jd
    biz_fields = (
        "company", "role", "position", "title", "job",
        "requirements", "description", "job_description",
        "responsibilities", "responsibility",
    )
    if not any(jd_data.get(k) for k in biz_fields):
        return error_response(
            "INVALID_JSON",
            "target_jd 缺少岗位关键字段（company/role/requirements/description 等），拒绝导入。"
            "请基于真实 JD 内容填充字段后再调用 import_jd。",
            {"received": jd_text[:200]},
        )

    profile = load_profile()
    profile.target_jd = jd_data
    profile.section_updated_at["target_jd"] = datetime.now().isoformat()
    # 换 JD 后旧分析失效：非空 gap 标记 stale，workflow 会强制重新分析
    stale_note = ""
    if profile.gap:
        profile.gap_stale_at = datetime.now().isoformat()
        stale_note = (
            "\n\n注意：档案里已有旧目标的差距分析，已标记为过期——"
            "下一步必须调用 analyze_gaps 重新分析，再决定是否重新规划，"
            "不要直接基于旧分析生成路线图。"
        )
    profile.touch()
    save_profile(profile)

    return (
        f"已导入目标 JD。当前档案版本：v{profile.version}"
        f"{stale_note}\n\n"
        "下一步：调用 analyze_gaps 开始差距分析。"
    )


@mcp.tool()
def import_jd_file(file_path: str) -> str:
    """从文件导入目标岗位的 JD（职位描述）。支持 PDF、DOCX、Markdown、TXT 格式。

    Args:
        file_path: JD 文件的绝对路径
    """
    try:
        text = extract_text(file_path)
    except FileNotFoundError as e:
        return error_response("MISSING_DATA", str(e), {"file_path": file_path})
    except ValueError as e:
        return error_response("INVALID_JSON", str(e), {"file_path": file_path})

    return (
        f"--- JD CONTENT ---\n{text}\n--- END ---\n\n"
        "根据以上 JD 内容，请调用 import_jd 工具导入，字段结构如下：\n"
        'import_jd(jd_text=\'{"company": "<公司名>", "role": "<岗位名>", "requirements": ["<要求1>", "<要求2>"]}\')\n'
        "请用上面 JD 的真实内容填充字段（company/role/requirements/description 至少一项），"
        "禁止原样复制示例占位文本。\n"
        "下一步：调用 import_jd 导入结构化字段。"
    )
