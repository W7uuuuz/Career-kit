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

from .core.state import State, StateSnapshot, resolve_state

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

# 首轮采集卡：只有一个决策（给简历 / 一次回 4 项）。
INTAKE_CARD = (
    "有简历就直接发我（文件或路径），我会读出学历、届别、经历和技能；\n"
    "没有简历，就一次回我 4 项：\n"
    "1) 方向/岗位（不确定写「不知道」）\n"
    "2) 城市\n"
    "3) 届别 + 学历/专业\n"
    "4) 实习/项目（没有写「没有」）"
)

INTAKE_OPTIONS: tuple[str, ...] = (
    "我有简历，给路径",
    "我一次说 4 项",
    "先只定方向",
)

BOSS_LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"

EXPECTED_OUTCOME_OPTIONS: tuple[str, ...] = (
    "大厂/平台",
    "先上车再发展",
    "稳定优先",
    "薪资优先",
    "成长/技术优先",
)

# 主线任务全部完成后的结束语：第 10/11 步之后是持续维护，不是新阶段
MAINTENANCE_CLOSING = (
    "主线任务已完成——后续是持续维护，不是新阶段："
    "继续投递、记录面试反馈、做周期检视即可。"
    "遇到目标变化、面试反馈或计划失配，随时回来重新校准。"
)


def login_action(login_command: str) -> dict[str, Any]:
    """BOSS 扫码登录的交互契约：优先由 Agent 用 harness 直接执行脚本。

    用户只需要在浏览器里扫码，不需要自己复制命令、开终端。
    仅当 harness 不能执行命令时，才退化为把命令交给用户。
    同一会话只提示一次登录；失败时给恢复建议，不反复追问。
    """
    return {
        "harness_can_run": True,
        "login_tool": "boss_login",
        "login_tool_action": "boss_login(action=\"login\")",
        "login_url": BOSS_LOGIN_URL,
        "user_instruction": (
            "我可以直接帮你打开登录窗口，你只需要在浏览器里扫码。"
            "会弹出一个专用浏览器，请忽略可能出现的默认新标签页；"
            "打开后如果不在登录页，请点右上角「登录/扫码」；"
            "扫码成功后窗口会保持打开，不会自动关闭，后续抓取直接复用；"
            "若登录后迟迟没有反应，可以打断这次会话，直接告诉我。"
        ),
        "agent_action": (
            "同一会话只提示一次，不要反复问「要不要登录」；用户同意后优先调用 "
            "boss_login(action=\"login\")（harness 直接执行，用户只扫码）。"
            "登录成功后浏览器窗口保持常驻，直接重试原操作；需要关闭时调用 "
            "boss_login(action=\"close\")。不要把命令丢给用户手动执行；"
            "只有 boss_login 不可用时，才用终端/Bash 运行 login_command 兜底。"
            "若登录后迟迟无响应，请用户打断本次会话并直接告诉 Agent，再按失败原因给恢复建议。"
        ),
        "login_command": login_command,
    }


PHASE_TYPE_LABELS: dict[str, str] = {
    "learn": "学习",
    "project": "项目",
    "intern": "实习",
    "research": "调研",
}


def phase_type_label(phase_type: str) -> str:
    """把内部阶段类型翻成用户能懂的中文，英文只在内部使用。"""
    return PHASE_TYPE_LABELS.get(str(phase_type or "").strip().lower(), "阶段")


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


def _has_sections(profile: Any) -> bool:
    return bool(
        getattr(profile, "who", None)
        or getattr(profile, "have", None)
        or getattr(profile, "want", None)
        or getattr(profile, "summary", "")
    )


def brief_shown(profile: Any) -> bool:
    """简介只发一次：已经填过任何 section 的档案不再重复首屏。"""
    return bool(_guidance(profile).get("brief_shown_at")) or _has_sections(profile)


def goal_confirmed(profile: Any) -> bool:
    """目标是否由用户确认过。"""
    return bool(_guidance(profile).get("goal_confirmed_at"))


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
    who = getattr(profile, "who", None) or {}
    year = ""
    if isinstance(who, dict):
        year = str(who.get("graduation_year") or "")
    if not year:
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


def _case_destinations(profile: Any, limit: int = 3) -> list[str]:
    """从已有调研案例里提取同背景去向；只引用真实抓到的公司/岗位，不编造。"""
    research = getattr(profile, "research", None) or {}
    cases = research.get("cases") if isinstance(research, dict) else None
    destinations: list[str] = []
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        if str(case.get("kind") or "success_experience") != "success_experience":
            continue
        destination = "、".join(
            str(value).strip()
            for value in (case.get("company"), case.get("position"))
            if str(value or "").strip()
        )
        if not destination:
            destination = str(case.get("title") or "").strip()[:30]
        if destination and destination not in destinations:
            destinations.append(destination)
        if len(destinations) >= limit:
            break
    return destinations


def expected_outcome_question(profile: Any) -> str:
    """目标与差距之间的最后一问：你最终想要什么结果？

    有同背景案例时引用真实去向；没有就说明后续调研会补，不编造。
    """
    destinations = _case_destinations(profile)
    if destinations:
        lead = "调研里同背景的去向包括：" + "、".join(destinations) + "。"
    else:
        lead = "目前还没有同背景去向样本，后续调研会补上。"
    return (
        f"{lead}开始差距分析前先对齐目标：你最终想要什么结果？"
        "是大厂/平台、先上车再发展、稳定优先、薪资优先，还是成长/技术优先？"
        "这会决定差距按哪把尺子量。"
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
    advisories = getattr(profile, "advisories", None)
    if isinstance(advisories, dict):
        gap_items = ((advisories.get("gap") or {}).get("items") or [])
        roadmap_items = ((advisories.get("roadmap") or {}).get("items") or [])
        if gap_items:
            notes.append(f"差距分析有 {len(gap_items)} 条质量建议待处理")
        if roadmap_items:
            notes.append(f"路线图有 {len(roadmap_items)} 条质量建议待处理")
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
    kind: str = "decision"
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
        "介绍 Career Kit，并邀请你给简历或一次说清基本情况",
        "先带你看完整 12 步，再只问一个决策；不需要准备材料",
        "有简历就发简历，没有就一次回 4 项，没有标准答案",
    ),
    "intake_wait": (
        "把你刚才说的信息写入档案",
        "先把刚才的信息整理进档案，本轮不用再向你提问",
        "信息已经足够，本轮不用再向用户新增问题",
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
        "4 步：范围宣告 → 批量抓取 → 报告落地 → 衔接分析；抓真实 JD 并逐条补详情",
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
    "execution": (
        "持续推进与维护：按当前阶段任务逐项推进，并把投递与复盘纳入日常",
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
    kind: str = "decision",
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
        kind=kind,
        what=what,
        method=method,
        how_to_read=how_to_read,
        rules_hint=rules_hint,
    )


def _profile_guide(profile: Any) -> Guide:
    return _guide(
        "profile",
        "profile",
        "信息已收齐，下一步把它整理成一份可核验的职业档案。",
        options=["开始整理"],
        next_action="finalize_profile；若技能证据未确认，先按摸排纪律确认 "
                    "authorship / control_level / self_assessment",
        profile=profile,
    )


def _target_guide(profile: Any) -> Guide:
    return _guide(
        "target",
        "goal",
        goal_question(profile),
        options=["对，就是这样", "方向要改", "城市/届别要改"],
        next_action=(
            "用户没有方向 → explore_goals；用户给出方向 → "
            "intake(section='want', data 里带 user_confirmed=true)；"
            "只确认缺失项：已亲口说过的方向/城市/届别直接采用，不再重复询问"
        ),
        profile=profile,
    )


def _market_guide(profile: Any) -> Guide:
    return _guide(
        "market",
        "market",
        "我现在按档案里的目标和城市开始调研：抓真实岗位和同背景经历。"
        "大约 30-50 秒；有要增减的公司直接说。",
        next_action="若调研范围含 BOSS：先 boss_login(action='status')，未就绪直接 "
                    "boss_login(action='login')，登录成功后再 gather_research_data；"
                    "不要先跑批再补登录。否则直接走 research_market → gather_research_data，"
                    "不要问是否开始；用户提出增减公司时先调整范围再抓取",
        profile=profile,
    )


def _gap_guide(profile: Any) -> Guide:
    return _guide(
        "gap",
        "gap",
        expected_outcome_question(profile),
        options=list(EXPECTED_OUTCOME_OPTIONS),
        next_action=(
            "用户回答后先 intake(section='want', data 带 expected_outcome=用户原话或选项，"
            "user_confirmed=true)，再按 analyze_gaps → save_gap_analysis 执行；"
            "不要替用户选择结果预期"
        ),
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
        "路线图已就绪。下一步可以按企业适配校准：先按档位和行业给你一份名单，"
        "你再增删确认；也可以先跳过，按基线路线图执行。要怎么做？",
        options=["生成目标企业名单", "先跳过，按基线执行"],
        next_action=(
            "选企业适配 → select_target_companies（推荐，完成后链路可校准执行版）；"
            "选按基线执行 → detail_current_phase → generate_tasks，"
            "会记录企业适配跳过事实，后续可随时补"
        ),
        profile=profile,
    )


def _evidence_guide(profile: Any) -> Guide:
    return _guide(
        "evidence",
        "evidence",
        "名单已确认，我现在直接抓名单企业的真实 JD 与面经，每批约 30-90 秒。"
        "需要薪资行情就说一声，我补充 BOSS 直聘；名单要改也可以直接说。",
        options=["补充 BOSS 薪资", "名单要改"],
        next_action="用户选补充 BOSS 时，未登录先 boss_login(action='login')，"
                    "登录成功后再传 include_boss=true, boss_confirmed=true 调 "
                    "collect_company_evidence；不要二次询问是否登录；"
                    "否则直接调用 collect_company_evidence，不要问是否开始；"
                    "名单要改则回到 select_target_companies",
        profile=profile,
    )


def _requirement_guide(profile: Any) -> Guide:
    return _guide(
        "requirement",
        "requirement",
        "证据已就绪，我现在直接统计企业高频要求与硬门槛，并解释优先级。"
        "想先看证据池明细随时说。",
        options=["先看证据池"],
        next_action="直接调用 analyze_company_requirements → save_requirement_profile，"
                    "不要问是否开始",
        profile=profile,
    )


def _alignment_guide(profile: Any) -> Guide:
    return _guide(
        "alignment",
        "alignment",
        "企业需求已分析。下一步用真实要求校准培养方案，生成执行版路线图。要现在校准吗？",
        options=["开始校准"],
        next_action="plan_execution_alignment → save_execution_alignment；"
                    "校准完成后重新生成当前阶段任务",
        profile=profile,
    )


def _execution_guide(profile: Any, snapshot: StateSnapshot) -> Guide:
    plan = getattr(profile, "plan", None) or {}
    detail_ready = isinstance(plan, dict) and bool(plan.get("current_detail"))
    has_tasks = bool(getattr(profile, "tasks", None) or [])
    if detail_ready and not has_tasks:
        return _guide(
            "execution",
            "execution",
            "当前阶段详细路线已就绪。下一步把它合并成可打卡任务。",
            options=["推荐：生成任务", "先看职业地图"],
            next_action="generate_tasks（合并详细路线与打卡点）；随后 get_next_tasks",
            profile=profile,
        )
    if snapshot.state in (State.EXECUTING, State.MAINTENANCE):
        return _guide(
            "execution",
            "execution",
            "当前是持续推进与维护：按当前阶段任务做，完成一项就打卡，"
            "进度会沉淀为能力证据。也可以生成投递清单、登记投递或做周期复盘；"
            "主线完成后同样是持续维护，不是新阶段。",
            options=["推荐：先看下一步任务", "生成投递清单", "登记已投递", "做周检视/计划检查"],
            next_action="get_next_tasks；完成后 checkin_task；"
                        "批量投递用 build_application_list；"
                        "投递进展用 record_application / delete_application；"
                        "周期复盘用 get_weekly_review / check_plan_fit",
            profile=profile,
        )
    return _guide(
        "execution",
        "execution",
        "下一步把当前阶段拆成可执行任务：每个任务会给出怎么做、用什么资源、"
        "怎么算完成。推荐现在细化；也可以先按里程碑生成粗任务，或先看职业地图。",
        options=["推荐：细化当前阶段", "先按里程碑生成粗任务", "先看职业地图"],
        next_action="detail_current_phase → save_current_detail → generate_tasks；"
                    "用户拒绝细化时可直接 generate_tasks",
        profile=profile,
    )


# StateSnapshot -> GUIDE 状态词；状态词只决定用户看到的话术，不再决定位置。
_STATE_STATUS: dict[State, str] = {
    State.EMPTY: "brief",
    State.PROFILE_COLLECTING: "goal",
    State.PROFILE_READY: "profile",
    State.MARKET_PENDING: "market",
    State.GAP_PENDING: "gap",
    State.BASELINE_PLAN_PENDING: "plan",
    State.COMPANY_PENDING: "company",
    State.EVIDENCE_PENDING: "evidence",
    State.REQUIREMENT_DRAFT: "requirement",
    State.REQUIREMENT_READY: "alignment",
    State.EXECUTION_PLAN_DRAFT: "alignment",
    State.EXECUTION_READY: "execution",
    State.EXECUTING: "execution",
    State.MAINTENANCE: "execution",
}


def _empty_guide(profile: Any, *, brief_needed: bool) -> Guide:
    return _guide(
        "profile",
        "brief",
        INTAKE_CARD,
        options=list(INTAKE_OPTIONS),
        next_action=(
            "用户给简历 → parse_resume → intake(section='bundle')；"
            "一次回 4 项 → intake(section='bundle', user_confirmed=用户是否亲口确认)；"
            "用户亲口陈述即确认，不要追加第二个确认决策"
        ),
        profile=profile,
        brief_needed=brief_needed,
        kind="intake",
    )


def _finalize_guide(
    guide: Guide, snapshot: StateSnapshot
) -> Guide:
    """位置、状态与下一步只来自同一个 StateSnapshot。"""
    guide.index = snapshot.stage_index
    guide.status = _STATE_STATUS[snapshot.state]
    # 只有存在可选决策时才加决策前缀；MARKET_PENDING 等无 options 的引导
    # 直接开始执行，不再出现「是否先做市场调研」这类二次确认。
    if guide.options:
        guide.ask = f"{snapshot.user_decision}：{guide.ask}"
    if snapshot.next_tool:
        decision = f"下一步：{snapshot.next_tool}"
        guide.next_action = (
            f"{guide.next_action}；{decision}" if guide.next_action else decision
        )
    return guide


def _guide_from_state(profile: Any, snapshot: StateSnapshot) -> Guide:
    """按 StateSnapshot 选择既有话术，不再各自解释 progress/goal。"""
    state = snapshot.state
    if state is State.EMPTY:
        guide = _empty_guide(profile, brief_needed=not brief_shown(profile))
    elif state is State.PROFILE_COLLECTING:
        guide = _target_guide(profile)
    elif state is State.PROFILE_READY:
        guide = _profile_guide(profile)
    elif state is State.MARKET_PENDING:
        guide = _market_guide(profile)
    elif state is State.GAP_PENDING:
        guide = _gap_guide(profile)
    elif state is State.BASELINE_PLAN_PENDING:
        guide = _plan_guide(profile)
    elif state is State.COMPANY_PENDING:
        guide = _company_guide(profile)
    elif state is State.EVIDENCE_PENDING:
        guide = _evidence_guide(profile)
    elif state is State.REQUIREMENT_DRAFT:
        guide = _requirement_guide(profile)
    elif state in (State.REQUIREMENT_READY, State.EXECUTION_PLAN_DRAFT):
        guide = _alignment_guide(profile)
    else:
        guide = _execution_guide(profile, snapshot)
    return _finalize_guide(guide, snapshot)


def build_guide(profile: Any) -> Guide:
    """从唯一状态快照推导「当前位置 + 本轮唯一决策」。"""
    snapshot = resolve_state(profile)
    return _guide_from_state(profile, snapshot)


# ---------------------------------------------------------------------------
# 渲染：用户文案与模型指令分离
# ---------------------------------------------------------------------------


def user_brief() -> str:
    """首屏简介：固定文案，模型原样发给用户。"""
    lines = [
        "Career Kit 是你的 AI 职业陪练。先用一分钟说清楚它是什么、能帮你做什么：",
        "",
        "**这是什么**",
        "Career Kit 是运行在你电脑上的职业规划服务。我通过本地工具抓真实招聘数据、",
        "保存你的档案和进度、把目标拆成可执行任务。档案和报告都在本机，不上传。",
        "",
        "**能帮你做什么**",
        "1. 用真实岗位和面经，告诉你市场要什么；",
        "2. 对照你的真实水平，告诉你差在哪、先补什么；",
        "3. 把目标拆成有顺序的阶段和任务，并记录执行进度。",
        "",
        "**怎么走**",
        "全流程共 12 步，归为三段：",
        "1. 定位（第 1-4 步）——建立你确认过的档案，定下目标岗位、城市和届别，"
        "再用真实市场数据看清差距；",
        "2. 规划（第 5-9 步）——把目标拆成有顺序的阶段方案，筛选目标企业、"
        "抓取真实 JD 与面经，并完成执行前校准；",
        "3. 执行（第 10-12 步）——按任务持续推进与打卡，记录投递与周期复盘，"
        "随时按事实调整计划。",
        "",
        "像聊天一样回答即可，每轮我只问一个真正需要你决定的问题。",
        "顺序定、节奏自己掌握；规则不清楚随时问我；现在从第 1 步开始——",
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
    if guide.options:
        if guide.kind == "intake":
            lines.append(f"本轮需要你提供：{guide.ask}")
        else:
            lines.append(f"本轮只问一个决策：{guide.ask}")
        lines.append("可选回答：" + " / ".join(guide.options))
    else:
        lines.append(f"本轮不用等确认，直接说明并继续：{guide.ask}")
    for note in guide.warnings:
        lines.append(f"事实提醒：{note}")
    lines.append("[GUIDE_MODEL]")
    if guide.next_action:
        lines.append(f"用户回答后的动作：{guide.next_action}")
    if guide.rules_hint:
        lines.append(f"规则入口：{guide.rules_hint}")
    if guide.brief_needed:
        lines.append("首次进入：先发上面的 [USER_BRIEF]，再按下面的采集卡提问。")
    lines += [
        "转述纪律：只把 [GUIDE] 到 [GUIDE_MODEL] 之间的内容转述给用户；"
        "不要出现工具名、字段名、JD01/CS03 这类内部代号；不要追加第二个决策。",
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
    "BOSS_LOGIN_URL",
    "EXPECTED_OUTCOME_OPTIONS",
    "FAMILIARITY_OPTIONS",
    "INTAKE_CARD",
    "INTAKE_OPTIONS",
    "JOURNEY_STEPS",
    "MAINTENANCE_CLOSING",
    "PHASE_TYPE_LABELS",
    "STEP_TOTAL",
    "Guide",
    "Step",
    "brief_shown",
    "build_guide",
    "expected_outcome_question",
    "goal_confirmed",
    "goal_question",
    "guide_for",
    "login_action",
    "mark_brief_shown",
    "mark_goal_confirmed",
    "opening_blocks",
    "phase_type_label",
    "render_guide",
    "reset_goal_confirmation",
    "user_brief",
    "verdict_label",
    "warnings",
]
