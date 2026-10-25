"""周检视——周期性事实复盘。

只呈现统计事实与规则化建议，不设时限、不催促；时间数字
（如「距上次打卡 N 天」）仅作为事实陈述，不是超期判断。
停摆的风险由用户自主决定，产品只保证「打开会话就能看到事实」。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..models import CareerProfile, Task, TaskStatus
from .application_tracker import (
    format_application_list,
    format_funnel_report,
    funnel_stats,
)
from .task_manager import current_phase_view

# 建议条数上限：防止建议膨胀成说教
_MAX_SUGGESTIONS = 3

# 转化结论的样本门槛：投递低于此值不下归因结论
_SAMPLE_MIN = 5

# 已完结口径（与 task_manager 一致）
_FINISHED = (TaskStatus.COMPLETED, TaskStatus.SKIPPED)

_STATUS_LABELS = {
    "screening": "进初筛/笔试",
    "interview": "进面试",
    "offer": "拿到offer",
    "rejected": "收拒信",
}


def _parse_iso(value: str | None) -> datetime | None:
    """容错解析 ISO 时间；非法值返回 None（不崩、不计入统计）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _in_window(iso: str | None, start: datetime, now: datetime) -> bool:
    dt = _parse_iso(iso)
    return dt is not None and start <= dt <= now


def days_since_last_checkin(profile: CareerProfile, now: datetime | None = None) -> int | None:
    """距最近一次打卡的天数；从无打卡记录返回 None。"""
    if not profile.checkins:
        return None
    now = now or datetime.now()
    last = max(
        (_parse_iso(c.timestamp) for c in profile.checkins), default=None
    )
    if last is None:
        return None
    return max(0, (now - last).days)


def summarize_period(
    profile: CareerProfile, days: int = 7, now: datetime | None = None
) -> dict[str, Any]:
    """汇总指定时间窗的执行、阶段与求职漏斗事实。"""
    now = now or datetime.now()
    start = now - timedelta(days=days)

    checkins = [c for c in profile.checkins if _in_window(c.timestamp, start, now)]
    completed: list[Task] = []
    skipped: list[Task] = []
    for t in profile.tasks:
        if t.status == TaskStatus.COMPLETED and _in_window(t.completed_at, start, now):
            completed.append(t)
        elif t.status == TaskStatus.SKIPPED and _in_window(t.completed_at, start, now):
            skipped.append(t)
    active_days = sorted({c.timestamp[:10] for c in checkins})

    # 阶段进度：期初（start 时点已完成数）vs 期末（now）
    roadmap = profile.plan.get("roadmap", profile.plan)
    phases = roadmap.get("phases", []) if isinstance(roadmap, dict) else []
    phase_rows = []
    for idx, phase in enumerate(phases):
        phase_id = phase.get("id") or f"phase_{idx + 1}"
        phase_tasks = [t for t in profile.tasks if t.phase_id == phase_id]
        done_now = sum(1 for t in phase_tasks if t.status in _FINISHED)
        done_at_start = sum(
            1 for t in phase_tasks
            if t.status in _FINISHED
            and (_parse_iso(t.completed_at) or now) <= start
        )
        phase_rows.append({
            "name": phase.get("name") or phase_id,
            "done_at_start": done_at_start,
            "done_now": done_now,
            "total": len(phase_tasks),
        })

    # 求职漏斗：窗口内增量（每家只计一次）+ 累计漏斗
    apps = profile.applications
    new_apps = [a for a in apps if _in_window(a.applied_at, start, now)]

    def _apps_reached(statuses: set[str]) -> int:
        return sum(
            1 for a in apps
            if any(
                e.get("status") in statuses and _in_window(e.get("at"), start, now)
                for e in a.events
            )
        )

    delta = {
        "new_applications": len(new_apps),
        "screened": _apps_reached({"screening", "interview", "offer"}),
        "interviewed": _apps_reached({"interview", "offer"}),
        "offers": _apps_reached({"offer"}),
        "rejected": _apps_reached({"rejected"}),
    }
    funnel_now = funnel_stats(profile)

    facts = {
        "days": days,
        "start": start,
        "now": now,
        "checkin_count": len(checkins),
        "active_days": active_days,
        "completed": completed,
        "skipped": skipped,
        "phase_rows": phase_rows,
        "funnel_delta": delta,
        "funnel_now": funnel_now,
        "days_since_checkin": days_since_last_checkin(profile, now),
    }
    facts["suggestions"] = _build_suggestions(profile, facts)
    return facts


def _build_suggestions(profile: CareerProfile, facts: dict[str, Any]) -> list[str]:
    """规则化生成建议（最多 3 条）。只基于数据与完成标准，不替用户排时间。"""
    suggestions: list[str] = []
    funnel = facts["funnel_now"]
    total = funnel["total"]

    # 1) 无投递记录：温和提示登记事实，不催投
    if total == 0:
        suggestions.append(
            "还没有投递记录——已经投的可以随时用 record_application 登记，"
            "漏斗统计需要事实输入。"
        )

    # 2) 过筛率低且样本足够：归因简历（样本不足不下结论）
    if (
        total >= _SAMPLE_MIN
        and funnel["rates"]["screen"] is not None
        and funnel["rates"]["screen"] <= 0.25
    ):
        suggestions.append(
            f"投递 {total} 家仅 {funnel['screened']} 家进初筛/面试，"
            "瓶颈大概率在简历——建议回到差距分析的 resume_optimization 复盘简历。"
        )

    # 3) 面试转化低：归因面试准备
    if funnel["interviewed"] >= 2 and funnel["offers"] == 0:
        suggestions.append(
            f"已进 {funnel['interviewed']} 家面试但暂无 offer——"
            "建议用差距分析的 interview_preparation 做专项准备，"
            "并结合面经总结复盘。"
        )

    # 4) 打卡停滞（事实陈列）+ 当前阶段高优先级未启动
    view = current_phase_view(profile)
    if view is not None:
        high_open = [t for t in view["next_tasks"] if t.priority == "high"]
        if facts["days_since_checkin"] is not None and facts["days_since_checkin"] >= 7:
            suggestions.append(
                f"最近一次打卡在 {facts['days_since_checkin']} 天前；"
                f"当前阶段「{view['phase_name']}」还有 {view['total'] - view['done']} 项未完成"
                + ("，几项高优先级任务尚未开始，下次从优先级最高的一项开始即可。"
                   if high_open else "。")
            )

    return suggestions[:_MAX_SUGGESTIONS]


def _task_lines(tasks: list[Task], empty_text: str) -> list[str]:
    if not tasks:
        return [f"- {empty_text}"]
    return [f"- {t.name}" for t in tasks]


def format_weekly_review(profile: CareerProfile, facts: dict[str, Any]) -> str:
    """把 summarize_period 的事实渲染为 Markdown 周检视。"""
    shown = datetime.now()
    start: datetime = facts["start"]
    now: datetime = facts["now"]
    header = (
        f"## 周检视（{start.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}，"
        f"近 {facts['days']} 天）"
    )

    lines = [header, ""]

    # 执行
    lines.append("### 执行")
    if facts["checkin_count"]:
        lines.append(
            f"- 打卡 {facts['checkin_count']} 次 · 活跃 {len(facts['active_days'])} 天"
            f" · 完成 {len(facts['completed'])} 个任务 · 跳过 {len(facts['skipped'])} 个"
        )
    else:
        last_days = facts["days_since_checkin"]
        tail = f"（最近一次打卡在 {last_days} 天前）" if last_days is not None else "（尚无打卡记录）"
        lines.append(f"- 窗口内无打卡{tail}")
    lines += _task_lines(facts["completed"], "窗口内无完成任务")

    # 阶段进度变化
    rows = facts["phase_rows"]
    if rows:
        lines += ["", "### 阶段进度"]
        for row in rows:
            mark = "[x]" if row["total"] and row["done_now"] == row["total"] else "[ ]"
            delta = row["done_now"] - row["done_at_start"]
            suffix = f"（窗口内 +{delta}）" if delta > 0 else ""
            lines.append(
                f"- {mark} {row['name']}：{row['done_now']}/{row['total']}{suffix}"
            )

    # 求职进展
    lines += ["", "### 求职进展"]
    delta = facts["funnel_delta"]
    if facts["funnel_now"]["total"]:
        lines.append(
            f"- 窗口内：新投递 {delta['new_applications']} · {_STATUS_LABELS['screening']} "
            f"{delta['screened']} · {_STATUS_LABELS['interview']} {delta['interviewed']} "
            f"· {_STATUS_LABELS['offer']} {delta['offers']} · {_STATUS_LABELS['rejected']} {delta['rejected']}"
        )
    else:
        lines.append("- 窗口内无投递动态（档案尚无投递记录）")
    lines.append(format_funnel_report(profile))
    recent_apps = format_application_list(profile, limit=5)
    if recent_apps:
        lines.append(recent_apps)

    # 事实提示
    note_lines = []
    view = current_phase_view(profile)
    if view is not None:
        high_open = [
            t for t in view["next_tasks"]
            if t.priority == "high" and t.status == TaskStatus.PENDING
        ]
        note_lines.append(
            f"- 当前阶段「{view['phase_name']}」进行中（{view['done']}/{view['total']}）"
            + (f"，{len(high_open)} 个高优先级任务尚未开始" if high_open else "")
        )
    if note_lines:
        lines += ["", "### 值得注意（事实陈述）"] + note_lines

    # 建议（规则化，最多 3 条）
    if facts["suggestions"]:
        lines += ["", "### 建议"]
        for i, s in enumerate(facts["suggestions"], 1):
            lines.append(f"{i}. {s}")
    lines += [
        "",
        "---",
        f"快照时间：{shown.strftime('%Y-%m-%d %H:%M')} · 继续执行用 get_next_tasks，"
        "复盘认可后继续；想调整随时说。数据缺什么补什么，不催不赶。",
    ]
    return "\n".join(lines)
