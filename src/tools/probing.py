"""技能摸排共享逻辑——作者身份与把控度自评（BUG-021）。

背景：真实运行测试发现，简历重度美化（代码全部 AI 生成、人只做验证迭代）时，
「独立完成 / 无 review / 讲难点」三问全部为真即可通过摸排——2018 年代的
防代写清单防不了「AI 生成 + 人工验证」这种 2026 主流形态，档案基线系统性虚高。

本模块集中三件事：
1. 简历自评三问的统一话术（SELF_ASSESSMENT_INSTRUCTIONS）——
   供 parse_resume / finalize 门禁 / analyze 双保险 / 命令剧本共用，防漂移；
2. 自评缺口的机检（find_self_assessment_issues）——
   authorship / control_level / self_assessment 的硬校验；
3. 技能聚合（collect_skills）——从 session_tools 迁来，双保险工具共用。
"""

from __future__ import annotations

from typing import Any

# 作者身份四档：手写 / AI 生成+人验证迭代 / AI 生成未深查 / 参考他人
AUTHORSHIP_VALUES = ("self_written", "ai_assisted", "ai_generated", "referenced")

# ai_* 才需要把「AI 生成」风险显式暴露到差距分析
AI_AUTHORED = ("ai_assisted", "ai_generated")

SELF_ASSESSMENT_INSTRUCTIONS = (
    "**简历自评三问（BUG-021，与求证同轮一起问；authorship/control_level 必须"
    "来自用户本人回答，AI 不得代填）：**\n"
    "① 总问：简历有美化成分（包括 AI 写的代码——项目算你的，但作者身份要说清）。"
    "诚实回答：简历里哪几条描述你面试现场站得住、哪些站不住？\n"
    "② 每条技能标 authorship（四选一）：self_written=手写 | "
    "ai_assisted=AI 生成+你验证迭代 | ai_generated=AI 生成未深查 | referenced=参考他人\n"
    "③ 每条技能自评把控度 control_level（0-10）：能讲架构=3，能逐行讲清=6，"
    "能手写重写=8+。整份简历落 have.self_assessment："
    '{"resume_trust": "high|medium|low", "notes": "哪几条站得住/站不住"}'
)


def collect_skills(have: dict) -> list:
    """聚合 have 中的技能条目（兼容 skills / core_skills / skill_evidence）。

    Returns:
        技能条目列表（dict 或 str）
    """
    skills: list = []
    for key in ("skills", "core_skills"):
        val = (have or {}).get(key, [])
        if isinstance(val, list):
            skills.extend(val)
        elif isinstance(val, dict):
            skills.append(val)
    ev = (have or {}).get("skill_evidence", [])
    if isinstance(ev, list):
        skills.extend(ev)
    return skills


def is_verified_skill(skill: Any) -> bool:
    """技能是否带用户确认过的证据（user_verified / verified 均兼容）。"""
    return (
        isinstance(skill, dict)
        and bool(skill.get("evidence"))
        and bool(skill.get("user_verified") or skill.get("verified"))
    )


def _has_self_assessment(have: dict) -> bool:
    """have.self_assessment 是否已写入（dict 需非空值，str 需非空）。"""
    sa = have.get("self_assessment")
    if isinstance(sa, dict):
        return any(str(v).strip() for v in sa.values())
    if isinstance(sa, str):
        return bool(sa.strip())
    return False


def _valid_control_level(value: Any) -> bool:
    """0-10 整数（bool 不算整数）。"""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 10
    )


def find_self_assessment_issues(have: dict) -> list[str]:
    """返回摸排自评缺口清单（空 = 通过）。

    校验规则（BUG-021 硬门禁的数据基础）：
    - 存在任何技能条目 → 必须写入 have.self_assessment（简历整体自评）；
    - 每条有用户确认证据（verified）的 dict 技能 → 必须有 authorship（四档枚举）
      与 control_level（0-10 整数）；
    - 纯字符串技能无法挂字段 → 只要求全局 self_assessment 说明作者身份。
    """
    have = have or {}
    issues: list[str] = []
    skills = collect_skills(have)
    if not skills:
        return issues

    if not _has_self_assessment(have):
        issues.append("缺 have.self_assessment（简历整体自评：resume_trust + notes）")

    for idx, skill in enumerate(skills):
        if not isinstance(skill, dict) or not is_verified_skill(skill):
            continue
        name = str(skill.get("skill") or f"技能[{idx}]")
        authorship = skill.get("authorship")
        if authorship not in AUTHORSHIP_VALUES:
            issues.append(
                f"技能「{name}」缺 authorship（四选一：self_written / ai_assisted / "
                "ai_generated / referenced）"
            )
        level = skill.get("control_level")
        if not _valid_control_level(level):
            issues.append(
                f"技能「{name}」缺 control_level（0-10 把控度自评："
                "能讲架构=3，能逐行讲清=6，能手写重写=8+）"
            )
    return issues


def ai_authored_skill_names(have: dict) -> list[str]:
    """authorship 标记为 AI 生成/辅助的技能名（供差距分析质量门使用）。"""
    names: list[str] = []
    for idx, skill in enumerate(collect_skills(have or {})):
        if not isinstance(skill, dict):
            continue
        if skill.get("authorship") in AI_AUTHORED:
            names.append(str(skill.get("skill") or f"技能[{idx}]"))
    return names
