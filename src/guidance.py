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
# 旅程：12 个阶段，顺序固定，节奏由用户掌握
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
        "职业档案构建",
        "先建立可核验的档案，后面的判断才有依据",
        "一份你确认过的职业档案",
    ),
    Step(
        "target",
        "目标岗位定位",
        "先定方向和城市，后面所有分析才有坐标",
        "一个你确认过的目标岗位",
    ),
    Step(
        "market",
        "市场基线调研",
        "用真实岗位与面经建立市场基线，每条都能点开验证",
        "一份带来源的市场基线报告",
    ),
    Step(
        "gap",
        "能力差距诊断",
        "看清差在哪、差多大、先补什么",
        "一份可执行的差距诊断",
    ),
    Step(
        "plan",
        "培养方案规划",
        "把目标拆成有顺序的阶段和任务，阶段顺序定、节奏自己掌握",
        "一张可打卡的基线职业地图",
    ),
    Step(
        "company",
        "目标企业筛选",
        "把目标从档位落到具体企业，确认要盯的名单",
        "一份已确认的目标企业池",
    ),
    Step(
        "evidence",
        "岗位与面经采集",
        "用目标企业的真实 JD 与面经替代想象",
        "一份带来源的岗位与面经证据池",
    ),
    Step(
        "requirement",
        "企业需求分析",
        "从证据里提炼企业真正高频要求的技能与门槛",
        "一份有样本支撑的企业需求画像",
    ),
    Step(
        "alignment",
        "执行方案校准",
        "用企业需求校准培养方案，明确每条调整的证据",
        "一份执行版路线图与变更清单",
    ),
    Step(
        "execution",
        "任务执行与打卡",
        "按关卡推进，完成即沉淀为能力证据",
        "可验证的能力证据与打卡记录",
    ),
    Step(
        "applications",
        "求职投递管理",
        "记录真实投递与状态变化，看清转化漏斗",
        "一份投递漏斗记录",
    ),
    Step(
        "review",
        "周期复盘与计划调整",
        "用事实复盘，目标变了随时重新规划",
        "一份周期复盘与调整记录",
    ),
)

_STEP_INDEX = {step.id: i for i, step in enumerate(JOURNEY_STEPS, 1)}
STEP_TOTAL = len(JOURNEY_STEPS)

FAMILIARITY_OPTIONS: tuple[str, ...] = (
    "完全不了解，想先看看",
    "有一些想法，想验证",
    "已经有明确目标",
)

def login_action(login_command: str) -> dict[str, Any]:
    """BOSS 扫码登录的交互契约：优先由 Agent 用 harness 直接执行脚本。

    用户只需要在浏览器里扫码，不需要自己复制命令、开终端。
    仅当 harness 不能执行命令时，才退化为把命令交给用户。
    """
    return {
        "harness_can_run": True,
        "user_instruction": "我可以直接帮你打开登录窗口，你只需要在浏览器里扫码；完成后告诉我继续。",
        "agent_action": (
            "先问用户是否现在登录；同意后直接用终端/Bash 工具运行 login_command。"
            "脚本会打开系统浏览器并等待扫码——请用户扫码，扫码成功后重试原操作。"
            "不要把命令丢给用户手动执行；只有当前 harness 无法运行命令时才让用户自己执行。"
        ),
        "login_command": login_command,
    }


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
    role = str(
        want.get("target_role")
        or want.get("role")
        or want.get("target")
        or want.get("direction")
        or want.get("position")
        or want.get("industry")
        or ""
    )
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
    what: str = ""
    method: str = ""
    how_to_read: str = ""
    rules_hint: str = ""

    @property
    def position(self) -> str:
        return f"第 {self.index} / {self.total} 步 · {self.step.name}"


# 每个状态的「在做什么 / 怎么做 / 结果怎么读」——先解释，再判定
_STATUS_META: dict[str, tuple[str, str, str]] = {
    "brief": (
        "介绍 Career Kit，并确认你对毕业方向的了解程度",
        "先带你看完整 12 步，再只问一个问题；不需要准备材料",
        "按真实想法回答即可，没有标准答案",
    ),
    "familiarity": (
        "确认你对毕业方向的了解程度",
        "听完你的回答再决定是否先做行业扫盲",
        "不了解也没关系，扫盲是可选的",
    ),
    "goal": (
        "确认你的目标（方向 / 城市 / 届别）",
        "我复述推断值，你确认或直接改",
        "目标是计划的起点；确认后才会进入分析",
    ),
    "profile": (
        "建档摸底：把简历素材变成你确认过的真实水平",
        "简历 + 逐项求证；技能要由你说明作者身份和把控度",
        "这里记录的是你确认过的事实，不是简历原文",
    ),
    "target": (
        "目标岗位定位：确认方向、城市与届别",
        "我复述推断值，你确认或直接改",
        "目标是所有分析和计划的坐标；有出入直接改",
    ),
    "market": (
        "市场调研：用真实岗位和同背景经历替代猜测",
        "抓真实 JD，逐条补详情；来源会标在报告里",
        "每条数据带来源链接；失败源会如实标注",
    ),
    "gap": (
        "差距分析：看简历过筛、面试通过、经历匹配三维差距",
        "结合调研数据与你的自评，给出差距清单和优先顺序",
        "匹配度是参考，不是审判；每项差距都有依据",
    ),
    "plan": (
        "培养方案规划：先判定起点档位，再设计阶段序列",
        "起点按 5 个维度加权打分；档位是命中率参考，不是准入许可",
        "结果怎么读：档位不是能力上限，你可以改任何一维的依据",
    ),
    "company": (
        "目标企业筛选：把方向落到具体企业名单",
        "先按档位和行业推荐，再让你增删确认",
        "企业名单只决定采集范围，不是投递承诺",
    ),
    "evidence": (
        "岗位与面经采集：抓目标企业的真实 JD 与面经",
        "只抓已确认名单里的企业；每批约 30-90 秒",
        "没有详情的岗位不会进入证据池；失败源会如实标注",
    ),
    "requirement": (
        "企业需求分析：从证据里统计高频要求与硬门槛",
        "数字由代码统计，我只解释优先级与公司差异",
        "样本少时会标低置信度，不把个别 JD 当全局结论",
    ),
    "alignment": (
        "执行方案校准：用企业需求调整培养方案",
        "每条调整都要引用证据；确认后才替换路线图",
        "没有证据的变更不会写入方案",
    ),
    "tasks": (
        "把当前阶段拆成可执行任务",
        "每个任务会给出怎么做、用什么资源、怎么算完成",
        "任务按「一次坐下可完成」设计；打卡方式随任务给出",
    ),
    "execution": (
        "执行打卡：按当前阶段任务逐项推进",
        "完成一项就打卡；daily 记天数，percent 记比例",
        "进度是事实记录，不设时限；快了可以加深，慢了可以调顺序",
    ),
    "applications": (
        "求职投递管理：记录真实投递与状态变化",
        "只记录你亲口说的事实，不估计状态",
        "漏斗基于事件历史，面试后被拒仍计入面试",
    ),
    "review": (
        "周期复盘：用事实看这一段发生了什么",
        "汇总打卡、阶段和求职漏斗，给规则化建议",
        "复盘不催促；下一步由你决定",
    ),
    "research": (
        "市场调研：用真实岗位和同背景经历替代猜测",
        "抓真实 JD，逐条补详情；来源会标在报告里",
        "每条数据带来源链接；失败源会如实标注",
    ),
    "roadmap": (
        "培养方案规划：先判定起点档位，再设计阶段序列",
        "起点按 5 个维度加权打分；档位是命中率参考，不是准入许可",
        "结果怎么读：档位不是能力上限，你可以改任何一维的依据",
    ),
    "align": (
        "执行方案校准：用企业需求调整培养方案",
        "每条调整都要引用证据；确认后才替换路线图",
        "没有证据的变更不会写入方案",
    ),
    "execute": (
        "执行打卡：按当前阶段任务逐项推进",
        "完成一项就打卡；daily 记天数，percent 记比例",
        "进度是事实记录，不设时限；快了可以加深，慢了可以调顺序",
    ),
}


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
    what, method, how_to_read = _STATUS_META.get(status, ("", "", ""))
    rules_hint = ""
    if status in ("gap", "plan", "roadmap"):
        rules_hint = "规则或口径不清楚时，读 career-kit://docs/rules 或直接问我"
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
        what=what,
        method=method,
        how_to_read=how_to_read,
        rules_hint=rules_hint,
    )


_CORE_STAGE_KEYS: tuple[tuple[str, str], ...] = (
    ("profile", "profile_id"),
    ("target", "target_spec_id"),
    ("market", "market_baseline_id"),
    ("gap", "gap_report_id"),
    ("plan", "baseline_plan_id"),
    ("company", "company_pool_id"),
    ("evidence", "evidence_run_id"),
    ("requirement", "requirement_profile_id"),
    ("alignment", "execution_plan_id"),
    ("execution", "execution_state_id"),
    ("applications", "application_state_id"),
    ("review", "review_report_id"),
)


def _core_state(profile: Any) -> dict[str, Any]:
    value = getattr(profile, "core_state", None)
    return value if isinstance(value, dict) else {}


def _legacy_flags(profile: Any) -> dict[str, bool]:
    plan = getattr(profile, "plan", None) or {}
    research = getattr(profile, "research", None) or {}
    want = getattr(profile, "want", None) or {}
    tasks = getattr(profile, "tasks", None) or []
    applications = getattr(profile, "applications", None) or []
    has_plan = isinstance(plan, dict) and bool(plan.get("roadmap"))
    has_gap = bool(getattr(profile, "gap", None))
    has_research = isinstance(research, dict) and bool(
        research.get("report_md") or research.get("jd_samples") or research.get("cases")
    )
    return {
        "profile": bool(
            getattr(profile, "summary", "")
            or getattr(profile, "who", None)
            or getattr(profile, "have", None)
        ),
        "target": isinstance(want, dict) and bool(want),
        "research": has_research,
        "gap": has_gap,
        "plan": has_plan,
        "tasks": bool(tasks),
        "applications": bool(applications),
    }


def _profile_guide(profile: Any) -> Guide:
    return _guide(
        "profile",
        "profile",
        "有简历文件吗？有的话给我路径；没有就简单说说你的经历，我会逐项向你求证。",
        options=["我有简历，给路径", "我口述经历", "先不补，直接看市场"],
        next_action="收齐 who/have 后调用 finalize_profile；技能必须由你确认，不能照抄简历",
        profile=profile,
    )


def _target_guide(profile: Any) -> Guide:
    return _guide(
        "target",
        "target",
        goal_question(profile),
        options=["对，就是这样", "方向要改", "城市/届别要改"],
        next_action="目标缺失时先用 explore_goals 选定方向；确认后写入目标，再继续调研",
        profile=profile,
    )


def _market_guide(profile: Any) -> Guide:
    return _guide(
        "market",
        "market",
        "下一步做市场调研：抓真实岗位和同背景经历。按来源数量约 30-90 秒，"
        "超过 90 秒建议拆批。要现在开始吗？",
        options=["开始调研", "先跳过，直接分析"],
        next_action="同意后走 research_market → gather_research_data",
        profile=profile,
    )


def _gap_guide(profile: Any) -> Guide:
    return _guide(
        "gap",
        "gap",
        "下一步做差距分析：基于调研数据告诉你差在哪、先补什么。要现在开始吗？",
        options=["开始分析", "先看看调研报告"],
        next_action="开始后按 analyze_gaps → save_gap_analysis 执行",
        profile=profile,
    )


def _plan_guide(profile: Any) -> Guide:
    return _guide(
        "plan",
        "plan",
        "下一步定路线图：把目标拆成有顺序的阶段。要先看阶段序列吗？",
        options=["开始规划", "先改分析结论"],
        next_action="按 generate_roadmap 的 step_template 分步执行",
        profile=profile,
    )


def _company_guide(profile: Any) -> Guide:
    return _guide(
        "company",
        "company",
        "路线图已就绪。下一步筛选目标企业：先按档位和行业给你一份名单，你再增删确认。"
        "要先看名单吗？",
        options=["推荐目标企业", "先跳过，按基线执行"],
        next_action="select_target_companies；用户确认名单后才进入岗位与面经采集",
        profile=profile,
    )


def _evidence_guide(profile: Any) -> Guide:
    return _guide(
        "evidence",
        "evidence",
        "目标企业已确认。下一步采集真实 JD 与面经，作为需求分析和方案校准的依据。"
        "要现在开始吗？",
        options=["开始采集", "先换一批企业"],
        next_action="collect_company_evidence；只抓已确认名单里的企业",
        profile=profile,
    )


def _requirement_guide(profile: Any) -> Guide:
    return _guide(
        "requirement",
        "requirement",
        "证据已就绪。下一步统计企业高频要求与硬门槛，并解释优先级。要现在分析吗？",
        options=["开始分析", "先看证据池"],
        next_action="analyze_company_requirements → save_requirement_profile",
        profile=profile,
    )


def _alignment_guide(profile: Any) -> Guide:
    return _guide(
        "alignment",
        "alignment",
        "企业需求已分析。下一步用真实要求校准培养方案，生成执行版路线图。要现在校准吗？",
        options=["开始校准", "先按基线路线图执行"],
        next_action="plan_execution_alignment → save_execution_alignment；"
                    "用户跳过时直接 detail_current_phase 或 generate_tasks",
        profile=profile,
    )


def _execution_guide(profile: Any, *, ready: bool) -> Guide:
    if not ready:
        return _guide(
            "execution",
            "execution",
            "下一步把当前阶段拆成可执行任务：每个任务会给出怎么做、用什么资源、"
            "怎么算完成。要现在细化吗？",
            options=["开始细化", "先按里程碑生成粗任务", "先看职业地图"],
            next_action="detail_current_phase → save_current_detail → generate_tasks；"
                        "用户拒绝细化时可直接 generate_tasks",
            profile=profile,
        )
    return _guide(
        "execution",
        "execution",
        "下一步推进当前阶段的任务；完成一项就打卡，进度会沉淀为能力证据。"
        "也可以顺手登记投递或做周期复盘。",
        options=["看下一步任务", "登记投递", "做周检视/计划检查"],
        next_action="get_next_tasks；完成后 checkin_task；"
                    "投递进展用 record_application / delete_application；"
                    "周期复盘用 get_weekly_review / check_plan_fit",
        profile=profile,
    )


def _review_guide(profile: Any) -> Guide:
    return _guide(
        "review",
        "review",
        "当前阶段任务已完成。要不要做一次周期复盘，看看下一步往哪走？",
        options=["做复盘", "登记投递", "直接定新目标"],
        next_action="get_weekly_review / check_plan_fit；目标变了先 analyze_gaps 重新分析",
        profile=profile,
    )


def _guide_from_core_state(profile: Any, state: dict[str, Any]) -> Guide:
    if not state.get("profile_id"):
        return _profile_guide(profile)
    if not state.get("target_spec_id"):
        return _target_guide(profile)
    if not state.get("market_baseline_id"):
        return _market_guide(profile)
    if not state.get("gap_report_id"):
        return _gap_guide(profile)
    if not state.get("baseline_plan_id"):
        return _plan_guide(profile)
    if not state.get("company_pool_id"):
        return _company_guide(profile)
    if not state.get("evidence_run_id"):
        return _evidence_guide(profile)
    if not state.get("requirement_profile_id"):
        return _requirement_guide(profile)

    stage = str(state.get("stage") or "")
    applied = bool(state.get("execution_plan_id")) and (
        stage in ("executing", "execution") or bool(state.get("execution_state_id"))
    )
    if not applied:
        return _alignment_guide(profile)
    return _execution_guide(profile, ready=bool(state.get("execution_state_id")))


def _guide_from_legacy_fields(profile: Any) -> Guide:
    flags = _legacy_flags(profile)
    if not flags["profile"]:
        return _profile_guide(profile)
    if not flags["target"]:
        return _target_guide(profile)

    downstream = flags["gap"] or flags["plan"] or flags["tasks"]
    if not (flags["research"] or downstream):
        return _market_guide(profile)
    if not (flags["gap"] or flags["plan"] or flags["tasks"]):
        return _gap_guide(profile)
    if not (flags["plan"] or flags["tasks"]):
        return _plan_guide(profile)

    if flags["tasks"] or flags["applications"]:
        tasks = list(getattr(profile, "tasks", None) or [])
        finished = ("completed", "skipped")
        if tasks and all(getattr(task, "status", "") in finished for task in tasks):
            return _review_guide(profile)
        return _execution_guide(profile, ready=True)
    return _company_guide(profile)


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

    state = _core_state(profile)
    if state:
        return _guide_from_core_state(profile, state)
    return _guide_from_legacy_fields(profile)


# ---------------------------------------------------------------------------
# 渲染：用户文案与模型指令分离
# ---------------------------------------------------------------------------


def user_brief() -> str:
    """首屏简介：固定文案，模型原样发给用户。"""
    lines = [
        "Career Kit 是你的 AI 职业陪练。先用一分钟说清楚它是什么、能帮你做什么：",
        "",
        "**这是什么**",
        "Career Kit 是运行在你电脑上的职业规划服务。我通过 MCP（让 AI 能调用本地工具的协议）",
        "调用它：抓真实招聘数据、保存你的档案和进度、把目标拆成可执行任务。",
        "档案在 ~/.career-kit，报告和路线图在 ~/CareerKit，都在本机，不上传。",
        "",
        "**能帮你做什么**",
        "1. 用真实岗位和面经，告诉你市场要什么；",
        "2. 对照你的真实水平，告诉你差在哪、先补什么；",
        "3. 把目标拆成有顺序的阶段和任务，并记录执行进度。",
        "",
        "**怎么用**",
        "像聊天一样回答即可。每轮我只问一个问题；随时可以说「跳过」「改方向」「看进度」。",
        "你不用懂工具名或流程，我会在每一步告诉你拿到了什么、下一步做什么。",
        "",
        "从起步到上岸全流程 12 步，每步你都能拿到实际的东西：",
        "",
    ]
    for i, step in enumerate(JOURNEY_STEPS, 1):
        lines.append(f"{i}. {step.name}——{step.why}；你会拿到：{step.deliverable}")
    lines += [
        "",
        "顺序定、节奏自己掌握。规则不清楚随时问我；现在从第 1 步开始——",
    ]
    return "\n".join(lines)


def render_guide(guide: Guide) -> str:
    """给模型看的引导块；模型必须把内容转述给用户，且只问 ``ask``。"""
    lines = [
        "[GUIDE]",
        f"位置：{guide.position}",
        f"为什么做这一步：{guide.step.why}",
        f"完成后你会拿到：{guide.step.deliverable}",
    ]
    if guide.what:
        lines.append(f"本轮要做什么：{guide.what}")
    if guide.method:
        lines.append(f"怎么做：{guide.method}")
    if guide.how_to_read:
        lines.append(f"结果怎么读：{guide.how_to_read}")
    lines.append(f"本轮只问一个问题：{guide.ask}")
    if guide.options:
        lines.append("可选回答：" + " / ".join(guide.options))
    for note in guide.warnings:
        lines.append(f"事实提醒：{note}")
    lines.append("[GUIDE_MODEL]")
    if guide.next_action:
        lines.append(f"用户回答后的动作：{guide.next_action}")
    if guide.rules_hint:
        lines.append(f"规则入口：{guide.rules_hint}")
    if guide.brief_needed:
        lines.append("首次进入：先发上面的 [USER_BRIEF]，再问下面的问题。")
    lines += [
        "转述纪律：只把 [GUIDE] 到 [GUIDE_MODEL] 之间的内容转述给用户；"
        "不要出现工具名、字段名、JD01/CS03 这类内部代号；不要一次问多个问题。",
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
    "login_action",
    "mark_brief_shown",
    "mark_goal_confirmed",
    "opening_blocks",
    "render_guide",
    "reset_goal_confirmation",
    "user_brief",
    "verdict_label",
    "warnings",
]
