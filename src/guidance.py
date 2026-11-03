"""引导词系统——Career Kit 全部用户可见文案与下一步决策的唯一事实源。

第一性原理
==========
1. 用户任何时刻只该被问一个决策；其余信息都是解释与交付说明。
2. 每一轮都要回答四件事：我在哪、为什么做、会拿到什么、接下来选什么。
3. 引导状态由档案推导，不依赖模型记忆；工具每次返回都带上它。
4. 用户文案与执行指令分离：``USER_BRIEF`` / ``GUIDE`` 给用户，
   工具名、字段名、内部代号只留在模型侧。

设计约束
========
- 本模块不导入任何 tool 模块，只读 ``CareerProfile`` 的属性，避免循环依赖。
- 所有用户可见文案集中在这里；其它文件只允许引用，不复制。
- 状态推导是纯函数：同样的档案永远得到同样的下一步。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# 旅程：6 个阶段，顺序固定，节奏由用户掌握
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    why: str
    deliverable: str


JOURNEY_STEPS: tuple[Step, ...] = (
    Step(
        "profile",
        "建档摸底",
        "先弄清你的真实水平和目标，后面的判断才有依据",
        "一份你确认过的档案",
    ),
    Step(
        "research",
        "市场调研",
        "用真实岗位数据替代猜测，每条都能点开验证",
        "一份带来源链接的市场报告",
    ),
    Step(
        "gap",
        "差距分析",
        "看清差在哪、差多大、先补什么",
        "一份可执行的差距清单",
    ),
    Step(
        "roadmap",
        "路线图规划",
        "把目标拆成有顺序的阶段和任务，阶段顺序定、节奏自己掌握",
        "一张可打卡的职业地图",
    ),
    Step(
        "execute",
        "执行打卡",
        "按关卡推进，完成即沉淀为能力证据",
        "可验证的能力证据",
    ),
    Step(
        "review",
        "持续陪跑",
        "用事实复盘，目标变了随时重新规划",
        "一份周期复盘",
    ),
)

_STEP_INDEX = {step.id: i for i, step in enumerate(JOURNEY_STEPS, 1)}
STEP_TOTAL = len(JOURNEY_STEPS)

FAMILIARITY_OPTIONS: tuple[str, ...] = (
    "完全不了解，想先看看",
    "有一些想法，想验证",
    "已经有明确目标",
)

VERDICT_LABELS: dict[str, str] = {
    "PASS": "通过",
    "PASS_WITH_NOTES": "通过，但有建议",
    "FAIL": "发现硬矛盾",
}


def verdict_label(verdict: str) -> str:
    """把内部审计枚举翻成人话。"""
    return VERDICT_LABELS.get(str(verdict), "待审计")


# ---------------------------------------------------------------------------
# 状态推导
# ---------------------------------------------------------------------------


def _guidance(profile: Any) -> dict[str, Any]:
    value = getattr(profile, "guidance", None)
    return value if isinstance(value, dict) else {}


def is_legacy(profile: Any) -> bool:
    """已有分析/规划/任务的档案不补首屏引导，避免打断续跑用户。"""
    plan = getattr(profile, "plan", None) or {}
    return bool(
        getattr(profile, "gap", None)
        or (isinstance(plan, dict) and plan.get("roadmap"))
        or getattr(profile, "tasks", None)
    )


def brief_shown(profile: Any) -> bool:
    return bool(_guidance(profile).get("brief_shown_at")) or is_legacy(profile)


def goal_confirmed(profile: Any) -> bool:
    """目标是否由用户确认过；老档案视为已确认。"""
    return bool(_guidance(profile).get("goal_confirmed_at")) or is_legacy(profile)


def mark_brief_shown(profile: Any) -> None:
    guidance = dict(_guidance(profile))
    guidance.setdefault("brief_shown_at", datetime.now().isoformat())
    profile.guidance = guidance


def mark_goal_confirmed(profile: Any) -> None:
    guidance = dict(_guidance(profile))
    guidance["goal_confirmed_at"] = datetime.now().isoformat()
    profile.guidance = guidance


def reset_goal_confirmation(profile: Any) -> None:
    """目标被改写（尤其是模型推断写入）时，重新要求用户确认。"""
    guidance = dict(_guidance(profile))
    guidance.pop("goal_confirmed_at", None)
    profile.guidance = guidance


def _want_text(profile: Any) -> tuple[str, str, str]:
    want = getattr(profile, "want", None) or {}
    if not isinstance(want, dict):
        return "", "", ""
    role = str(want.get("target_role") or want.get("role") or want.get("target") or "")
    city = str(want.get("city") or "")
    year = str(want.get("graduation_year") or "")
    return role, city, year


def goal_question(profile: Any) -> str:
    role, city, year = _want_text(profile)
    if not role:
        return (
            "你想往哪个方向走？可以说岗位、行业，或者一句模糊的想法；"
            "我不需要你现在就定死，会先帮你对照真实市场再确认。"
        )
    city = city or "（待确认）"
    year = year or "（待确认）"
    return (
        f"我先确认目标：你想投「{role}」，城市 {city}，届别 {year}，对吗？"
        "有出入直接改，确认后我再开始分析。"
    )


def warnings(profile: Any) -> list[str]:
    """事实性提醒：数据缺口、过期分析。不催促、不评判。"""
    notes: list[str] = []
    research = getattr(profile, "research", None) or {}
    if isinstance(research, dict):
        failed = [
            s for s in (research.get("source_status") or [])
            if isinstance(s, dict) and s.get("status") == "failed"
        ]
        if failed:
            names = "、".join(str(s.get("source") or "未知源") for s in failed[:3])
            notes.append(f"{len(failed)} 个数据源失败（{names}），缺口已写进报告")
    if getattr(profile, "gap_stale_at", ""):
        notes.append("目标 JD 已更新，旧差距分析过期，需要重新分析")
    return notes


@dataclass
class Guide:
    step: Step
    index: int
    total: int
    status: str
    ask: str
    options: list[str] = field(default_factory=list)
    next_action: str = ""
    warnings: list[str] = field(default_factory=list)
    brief_needed: bool = False

    @property
    def position(self) -> str:
        return f"第 {self.index} / {self.total} 步 · {self.step.name}"


def _guide(
    step_id: str,
    status: str,
    ask: str,
    *,
    options: list[str] | None = None,
    next_action: str = "",
    profile: Any = None,
    brief_needed: bool = False,
) -> Guide:
    step = JOURNEY_STEPS[_STEP_INDEX[step_id] - 1]
    return Guide(
        step=step,
        index=_STEP_INDEX[step_id],
        total=STEP_TOTAL,
        status=status,
        ask=ask,
        options=options or [],
        next_action=next_action,
        warnings=warnings(profile) if profile is not None else [],
        brief_needed=brief_needed,
    )


def build_guide(profile: Any) -> Guide:
    """从档案推导「当前位置 + 本轮唯一决策」。"""
    if not brief_shown(profile):
        return _guide(
            "profile",
            "brief",
            "你对毕业后的方向了解多少？",
            options=list(FAMILIARITY_OPTIONS),
            next_action="用户回答后，按对应分支继续；不要先要简历或目标",
            profile=profile,
            brief_needed=True,
        )

    if not goal_confirmed(profile):
        want = getattr(profile, "want", None) or {}
        scan_done = bool(isinstance(want, dict) and want.get("scan_completed_at"))
        if not want and not scan_done:
            return _guide(
                "profile",
                "familiarity",
                "你对毕业后的方向了解多少？",
                options=list(FAMILIARITY_OPTIONS),
                next_action=(
                    "完全不了解 → 提议扫盲；有一些想法 → 先问方向，再确认城市/届别；"
                    "已有目标 → 直接确认方向/城市/届别。用户回答后不要重复问同一题。"
                ),
                profile=profile,
            )
        return _guide(
            "profile",
            "goal",
            goal_question(profile),
            options=["对，就是这样", "方向要改", "城市/届别要改"],
            next_action="用户确认后调用 intake(section='want', data 里带 user_confirmed=true)，再继续",
            profile=profile,
        )

    summary = getattr(profile, "summary", "") or ""
    who = getattr(profile, "who", None) or {}
    have = getattr(profile, "have", None) or {}
    if not summary or not who or not have:
        return _guide(
            "profile",
            "profile",
            "有简历文件吗？有的话给我路径；没有就简单说说你的经历，我会逐项向你求证。",
            options=["我有简历，给路径", "我口述经历", "先不补，直接看市场"],
            next_action="收齐 who/have 后调用 finalize_profile；技能必须由你确认，不能照抄简历",
            profile=profile,
        )

    research = getattr(profile, "research", None) or {}
    if not (isinstance(research, dict) and research.get("report_md")):
        return _guide(
            "research",
            "research",
            "下一步做市场调研：抓真实岗位和同背景经历，约半分钟。要现在开始吗？",
            options=["开始调研", "先跳过，直接分析"],
            next_action="同意后走 research_market → gather_research_data",
            profile=profile,
        )

    gap = getattr(profile, "gap", None) or {}
    if not gap:
        return _guide(
            "gap",
            "gap",
            "下一步做差距分析：基于调研数据告诉你差在哪、先补什么。要现在开始吗？",
            options=["开始分析", "先看看调研报告"],
            next_action="开始后按 analyze_gaps → save_gap_analysis 执行",
            profile=profile,
        )

    plan = getattr(profile, "plan", None) or {}
    roadmap = plan.get("roadmap") if isinstance(plan, dict) else None
    if not roadmap:
        return _guide(
            "roadmap",
            "roadmap",
            "下一步定路线图：把目标拆成有顺序的阶段。要先看阶段序列吗？",
            options=["开始规划", "先改分析结论"],
            next_action="按 generate_roadmap 的 step_template 分步执行",
            profile=profile,
        )

    tasks = getattr(profile, "tasks", None) or []
    if not tasks:
        return _guide(
            "execute",
            "tasks",
            "路线图已就绪。下一步生成任务清单，然后从第一阶段开始。",
            options=["生成任务", "先看职业地图"],
            next_action="generate_tasks 后直接引导用户开始第一项",
            profile=profile,
        )

    finished = ("completed", "skipped")
    if all(getattr(t, "status", "") in finished for t in tasks):
        return _guide(
            "review",
            "review",
            "所有任务已完成。要不要做一次周期复盘，看看下一步往哪走？",
            options=["做复盘", "直接定新目标"],
            next_action="get_weekly_review；目标变了先 analyze_gaps 重新分析",
            profile=profile,
        )

    return _guide(
        "execute",
        "execute",
        "下一步推进当前阶段的任务；完成一项就打卡，进度会沉淀为能力证据。",
        options=["看下一步任务", "看整体进度", "复盘最近进展"],
        next_action="get_next_tasks；完成后 checkin_task",
        profile=profile,
    )


# ---------------------------------------------------------------------------
# 渲染：用户文案与模型指令分离
# ---------------------------------------------------------------------------


def user_brief() -> str:
    """首屏简介：固定文案，模型原样发给用户。"""
    lines = [
        "Career Kit 是你的 AI 职业陪练。从起步到上岸全流程 6 步，每步你都能拿到实际的东西：",
        "",
    ]
    for i, step in enumerate(JOURNEY_STEPS, 1):
        lines.append(f"{i}. {step.name}——{step.why}；你会拿到：{step.deliverable}")
    lines += [
        "",
        "你不需要懂工具或流程。每轮我只问你一个问题，你回答即可；"
        "顺序定、节奏自己掌握，随时可以跳过或改方向。",
        "现在从第 1 步开始——",
    ]
    return "\n".join(lines)


def render_guide(guide: Guide) -> str:
    """给模型看的引导块；模型必须把内容转述给用户，且只问 ``ask``。"""
    lines = [
        "[GUIDE]",
        f"位置：{guide.position}",
        f"为什么做这一步：{guide.step.why}",
        f"完成后你会拿到：{guide.step.deliverable}",
        f"本轮只问一个问题：{guide.ask}",
    ]
    if guide.options:
        lines.append("可选回答：" + " / ".join(guide.options))
    if guide.next_action:
        lines.append(f"用户回答后的动作：{guide.next_action}")
    for note in guide.warnings:
        lines.append(f"事实提醒：{note}")
    if guide.brief_needed:
        lines.append("首次进入：先发上面的 [USER_BRIEF]，再问下面的问题。")
    lines += [
        "转述纪律：不要出现工具名、字段名、JD01/CS03 这类内部代号；"
        "不要一次问多个问题。",
        "[GUIDE END]",
    ]
    return "\n".join(lines)


def guide_for(profile: Any) -> str:
    """当前档案的引导块；首次进入时自动附带 [USER_BRIEF]。"""
    guide = build_guide(profile)
    parts: list[str] = []
    if guide.brief_needed:
        parts += ["[USER_BRIEF]", user_brief(), "[USER_BRIEF END]", ""]
    parts.append(render_guide(guide))
    return "\n".join(parts)


def opening_blocks(profile: Any) -> str:
    """首屏别名：简介（若需要）+ 当前引导。"""
    return guide_for(profile)


__all__ = [
    "FAMILIARITY_OPTIONS",
    "JOURNEY_STEPS",
    "STEP_TOTAL",
    "Guide",
    "Step",
    "brief_shown",
    "build_guide",
    "goal_confirmed",
    "goal_question",
    "guide_for",
    "is_legacy",
    "mark_brief_shown",
    "mark_goal_confirmed",
    "opening_blocks",
    "render_guide",
    "reset_goal_confirmation",
    "user_brief",
    "verdict_label",
    "warnings",
]
