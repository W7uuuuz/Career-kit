"""求职漏斗——投递记录、状态流转与转化统计。

转化率基于 events 事件历史而非当前状态：「面试后被拒」的面试记录不能丢，
否则漏斗失真。产品不规划时间：本模块只记录事实，不做催促或超期判断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import Application, ApplicationStatus, CareerProfile

VALID_STATUSES = {
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
}

# 已完结状态：不再视作活跃投递（重复检查放行）
_FINISHED_STATUSES = {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}

# 事件口径：漏斗分层数据（event-based，不看当前 status）
_ADVANCED_STATUSES = {ApplicationStatus.SCREENING, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER}
_INTERVIEW_STATUSES = {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER}

# 样本门槛：投递数低于此值时转化率标注仅供参考
MIN_SAMPLE_FOR_RATES = 5

_STATUS_LABELS = {
    "applied": "已投递",
    "screening": "初筛/笔试",
    "interview": "面试中",
    "offer": "已获offer",
    "rejected": "已拒绝",
    "withdrawn": "已撤回",
}


def next_application_id(profile: CareerProfile) -> str:
    """生成不冲突的投递 ID：现有最大编号 + 1。"""
    max_num = 0
    for app in profile.applications:
        if app.id.startswith("app_"):
            try:
                max_num = max(max_num, int(app.id[4:]))
            except ValueError:
                continue
    return f"app_{max_num + 1:03d}"


def find_active_duplicate(
    profile: CareerProfile, company: str, role: str, exclude_id: str = ""
) -> Application | None:
    """同公司+同岗位的活跃投递（未拒绝/未撤回），返回第一条；不存在返回 None。"""
    company_norm = company.strip().lower()
    role_norm = role.strip().lower()
    for app in profile.applications:
        if exclude_id and app.id == exclude_id:
            continue
        if app.status in _FINISHED_STATUSES:
            continue
        if (
            app.company.strip().lower() == company_norm
            and app.role.strip().lower() == role_norm
        ):
            return app
    return None


def add_application(
    profile: CareerProfile,
    company: str,
    role: str = "",
    status: str = ApplicationStatus.APPLIED,
    channel: str = "",
    source: str = "",
    notes: str = "",
) -> Application:
    """新建投递记录：applied_at/updated_at 默认当前时间，写入首条状态事件。"""
    now = datetime.now().isoformat()
    app = Application(
        id=next_application_id(profile),
        company=company.strip(),
        role=role.strip(),
        channel=channel.strip(),
        status=status,
        applied_at=now,
        updated_at=now,
        source=source.strip(),
        notes=notes,
        events=[{"status": status, "at": now}],
    )
    if notes:
        app.events[0]["note"] = notes
    profile.add_application(app)
    return app


def update_application_status(
    profile: CareerProfile, app: Application, status: str, note: str = ""
) -> bool:
    """更新投递状态：状态变化才追写事件。返回是否发生变更。"""
    if status == app.status:
        return False
    app.transition(status, note)
    profile.touch()
    return True


def funnel_stats(profile: CareerProfile) -> dict[str, Any]:
    """漏斗统计：全部基于事件历史。

    - total：全部投递记录数
    - screened：出现过初筛/面试/offer 事件的记录数
    - interviewed：出现过面试/offer 事件的记录数
    - offers：出现过 offer 事件的记录数
    - rejected：出现过拒绝事件的记录数
    - rates：分母为 0 时置 null
    - sample_sufficient：total >= MIN_SAMPLE_FOR_RATES
    """
    apps = profile.applications

    def _has(app: Application, statuses: set[str]) -> bool:
        return any(e.get("status") in statuses for e in app.events)

    screened = sum(1 for a in apps if _has(a, _ADVANCED_STATUSES))
    interviewed = sum(1 for a in apps if _has(a, _INTERVIEW_STATUSES))
    offers = sum(1 for a in apps if _has(a, {ApplicationStatus.OFFER}))
    rejected = sum(1 for a in apps if _has(a, {ApplicationStatus.REJECTED}))
    total = len(apps)

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 2) if den > 0 else None

    return {
        "total": total,
        "active": sum(1 for a in apps if a.status not in _FINISHED_STATUSES),
        "screened": screened,
        "interviewed": interviewed,
        "offers": offers,
        "rejected": rejected,
        "rates": {
            "screen": _rate(screened, total),
            "interview": _rate(interviewed, screened),
            "offer": _rate(offers, interviewed),
        },
        "sample_sufficient": total >= MIN_SAMPLE_FOR_RATES,
    }


def _funnel_line(stats: dict[str, Any]) -> str:
    """单行漏斗概览：投递 → 过筛（x%）→ 面试（x%）→ offer（x%）。"""
    rates = stats["rates"]

    def _pct(rate: Any) -> str:
        return f"{int(rate * 100)}%" if isinstance(rate, (int, float)) else "-"

    line = (
        f"投递 {stats['total']} → 过筛 {stats['screened']}（{_pct(rates['screen'])}）"
        f" → 面试 {stats['interviewed']}（{_pct(rates['interview'])}）"
        f" → offer {stats['offers']}（{_pct(rates['offer'])}）"
    )
    if not stats["sample_sufficient"]:
        line += "（样本不足，比率仅供参考）"
    return line


def format_funnel_report(profile: CareerProfile) -> str:
    """漏斗文本报告，供 get_progress / 周检视 / 仪表盘共用。"""
    if not profile.applications:
        return "## 求职漏斗\n暂无投递记录（记录后自动统计：用 record_application）"
    stats = funnel_stats(profile)
    lines = ["## 求职漏斗", _funnel_line(stats), ""]
    lines.append(
        f"- 当前活跃：{stats['active']} · 已拒绝：{stats['rejected']}"
        " · 结局以事件历史为准（面试后被拒仍计入面试数）"
    )
    return "\n".join(lines)


def format_application_list(
    profile: CareerProfile, limit: int = 10, title: str = "投递记录"
) -> str:
    """格式化最近投递清单（最新在前）。"""
    if not profile.applications:
        return f"## {title}\n暂无投递记录"
    lines = [f"## {title}", ""]
    for app in reversed(profile.applications[-limit:]):
        label = _STATUS_LABELS.get(app.status, app.status)
        role = f" · {app.role}" if app.role else ""
        lines.append(f"- **{app.company}**{role} · {label} · {app.id}")
    return "\n".join(lines)


def application_summary(app: Application) -> dict[str, Any]:
    """单条投递的结构化摘要（工具返回值用）。"""
    return {
        "id": app.id,
        "company": app.company,
        "role": app.role,
        "channel": app.channel,
        "status": app.status,
        "status_label": _STATUS_LABELS.get(app.status, app.status),
        "applied_at": app.applied_at,
        "updated_at": app.updated_at,
        "source": app.source,
        "notes": app.notes,
        "events": app.events,
    }
