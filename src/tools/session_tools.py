"""建档与分析输入类 MCP 工具。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ..mcp_app import mcp
from .errors import InvalidJsonError, error_response
from .profile import get_active_profile_name, load_profile, merge_section, save_profile
from .resume_parser import extract_text
from .session import get_welcome_message
from .tool_helpers import _json, _parse_json_param


@mcp.tool()
def start_session() -> str:
    """初始化新的职业规划会话。

    何时调用：用户开始新的职业规划时首先调用此工具。
    返回欢迎信息，引导用户开始建档流程。

    工作流程：start_session → intake(who) → intake(have) → intake(want) → finalize_profile
    """
    return (
        f"{get_welcome_message()}\n\n"
        f"当前档案：{get_active_profile_name()}\n"
        "下一步：请调用 intake 工具填充档案信息。\n"
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
        "   实际掌握到什么程度？\n"
        "2. 证据（evidence）必须来自用户确认，**不得照抄简历原文**；\n"
        "   未经用户确认的技能标 `verified: false`，确认过的标 `verified: true`。\n"
        "3. 学历/城市/届别等身份信息直接可用；技能与项目必须验证后再写入 have。\n\n"
        "请调用 intake 工具填充：\n"
        '- "who" section：姓名、联系方式、教育背景、当前状态\n'
        '- "have" section：技能、工作经历、项目经验、证书（每项带 evidence 与 verified）\n\n'
        '示例：intake(section="who", data=\'{"name":"张三", "education":"..."}\')\n'
        "下一步：先向用户求证关键技能证据，再调用 intake(section=\"have\")；"
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
            - have: 你有什么（技能、经历、资源）；关键技能请附带证据与置信度
            - want: 你想要什么（目标岗位、行业、薪资）
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

    profile = merge_section(section, data)
    result = (
        f"已记录到「{section}」。当前档案版本：v{profile.version}\n"
        "下一步：继续补齐其他 section；who/have/want 都有内容后调用 finalize_profile。"
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
            摸排是硬性必选步骤（BUG-001）：have 有技能但无用户确认证据时，
            本工具拒绝放行，除非用户明确表示跳过，此时 LLM 传 skip_probing=True
            并记录留痕——不得以置信度高或简历字面为由自动跳过。

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
        or any(
            isinstance(s, dict)
            and s.get("evidence")
            and (s.get("user_verified") or s.get("verified"))
            for s in skills
        )
    )
    needs_probe = bool(skills) and not has_evidence

    if needs_probe and not skip_probing:
        return error_response(
            "PROBING_REQUIRED",
            "档案中的技能没有用户确认过的证据，摸排是硬性必选步骤（BUG-001）：\n"
            "简历有美化成分——按简历字面水平做差距分析会系统性失真，"
            "不能以 confidence=高 或 evidence 照抄简历来绕过。\n"
            "请先对关键技能逐项向用户求证：\n"
            "  1. 这个项目是不是你独立完成的？\n"
            "  2. 团队里有没有人 review 你的代码？\n"
            "  3. 某个难点具体怎么解决的？实际掌握到什么程度？\n"
            "然后把确认过的证据（evidence）写入技能条目并标 user_verified=true。\n\n"
            "唯一跳过方式：用户明确表示不需要摸排时，LLM 以 finalize_profile(skip_probing=True) "
            "继续，此跳过会被记录留痕。",
            {"needs_probe": True, "skip_via": "finalize_profile(skip_probing=True)"},
        )

    # 记录摸排状态：技能有证据 / 用户主动跳过
    if needs_probe and skip_probing:
        profile.probe_skipped = True
    elif not needs_probe:
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

    want 中的 raw（如"想转行"这种模糊表述）不算实质目标——正是 explore_goals 的场景。
    """
    want = profile.want or {}
    for key in ("target_role", "role", "position", "direction", "industry",
                "job_family", "target_company", "target_companies"):
        if want.get(key):
            return True
    if profile.target_jd:
        return True
    return False


def _collect_skills(have: dict) -> list:
    """聚合 have 中的技能条目（兼容 skills / core_skills / skill_evidence）。

    Returns:
        技能条目列表（dict 或 str）
    """
    skills: list = []
    for key in ("skills", "core_skills"):
        val = have.get(key, [])
        if isinstance(val, list):
            skills.extend(val)
        elif isinstance(val, dict):
            skills.append(val)
    ev = have.get("skill_evidence", [])
    if isinstance(ev, list):
        skills.extend(ev)
    return skills


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
        jd_data = json.loads(jd_text)
    except json.JSONDecodeError as exc:
        return error_response(
            "INVALID_JSON",
            "JD 不是合法 JSON。请提供结构化 JD："
            '{"company":..., "role":..., "requirements":[...]}（至少含其中一项）；'
            "或将 JD 文件交给 import_jd_file 解析。",
            {"raw": jd_text[:200], "parse_error": str(exc)},
        )

    if not isinstance(jd_data, dict):
        return error_response(
            "INVALID_JSON",
            f"JD JSON 必须是对象（dict），收到的是 {type(jd_data).__name__}。",
            {"received": jd_text[:200]},
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
    profile.touch()
    save_profile(profile)

    return (
        f"已导入目标 JD。当前档案版本：v{profile.version}\n\n"
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
        " 请用上面 JD 的真实内容填充字段（company/role/requirements/description 至少一项），"
        "禁止原样复制示例占位文本。\n"
        "下一步：调用 import_jd 导入结构化字段。"
    )
